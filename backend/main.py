"""
main.py
=======
The FastAPI backend (Stage 1). This is part of LAYER 2 — plain always-on Python,
no Claude tokens. It exposes everything the dashboard needs:

  GET  /api/mode                 current paper/live status (for the banner)
  POST /api/mode/live            switch to LIVE (guarded; needs "GO LIVE")
  POST /api/mode/paper           switch back to PAPER
  POST /api/kill                 engage kill switch (cancel orders + halt)
  POST /api/kill/reset           clear kill switch
  GET  /api/portfolio            equity, cash, today's P&L, all-time P&L
  GET  /api/positions            open positions from Bybit
  GET  /api/orders               trade/order history (SQLite)
  GET  /api/stats                return / win rate / Sharpe / max drawdown
  GET  /api/config               current trading config
  PUT  /api/config               save trading config (validated)
  GET  /api/decisions            list of decision files (index)
  GET  /api/decisions/latest     latest full decision JSON
  GET  /api/transcript/latest    latest debate transcript per agent
  POST /api/decisions/action     approve / reject a decision (exec wired Stage 4)
  GET  /api/health               connectivity check to the active environment

Run:  uvicorn backend.main:app --reload --port 8000   (from the project root)
"""

from __future__ import annotations
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import os
import shutil
from pathlib import Path

from . import db, exchange, stats, decisions_io, engine, scanner
from .scheduler import scheduler
from .config import mode_manager, PROJECT_ROOT, has_mainnet_keys
from .models import TradingConfig, GoLiveRequest, DecisionAction, AutomationConfig


@asynccontextmanager
async def lifespan(app: FastAPI):
    # On boot: create tables, seed config. Mode is ALWAYS paper at startup
    # (enforced by ModeManager's constructor).
    db.init_db()
    # Resume the persisted mode — but ONLY into live if mainnet keys exist.
    saved = db.get_saved_mode()
    if saved == "live" and has_mainnet_keys():
        mode_manager.restore_mode("live")
        db.add_alert("warning", "system",
                     "⚠ Resumed in LIVE / REAL FUNDS mode from saved state. Auto-trading "
                     "(if enabled) is now active on real money.")
    else:
        db.add_alert("info", "system", f"Backend started in {mode_manager.mode.upper()} mode.")
    # Start the always-on mechanical scan loop (no Claude tokens). Disable with
    # SCHEDULER_ENABLED=0 (used by tests).
    if os.getenv("SCHEDULER_ENABLED", "1") != "0":
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Bybit Multi-Agent Trading — Layer 2 API", lifespan=lifespan)

# The Vite dev server runs on a different port, so allow it during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
#  Mode / safety
# ---------------------------------------------------------------------------

@app.get("/api/mode")
def get_mode():
    return mode_manager.status()


@app.post("/api/mode/live")
def go_live(req: GoLiveRequest):
    result = mode_manager.go_live(req.confirmation)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    exchange.reset_clients()   # rebuild ccxt client with mainnet keys
    db.save_mode("live")       # persist so a restart resumes live
    return mode_manager.status()


@app.post("/api/mode/paper")
def go_paper():
    mode_manager.go_paper()
    exchange.reset_clients()
    db.save_mode("paper")      # persist so a restart resumes paper
    return mode_manager.status()


@app.post("/api/kill")
def kill():
    """Hard kill switch: cancel resting orders on the exchange, then halt.
    Order execution itself lands in Layer 2 (Stage 4); here we at least try to
    cancel open orders and flip the halt flag so nothing new goes out.
    """
    mode_manager.engage_kill_switch()
    canceled = 0
    try:
        client = exchange.get_client()
        for o in client.fetch_open_orders():
            try:
                client.cancel_order(o["id"], o["symbol"])
                canceled += 1
            except Exception:
                pass
    except Exception:
        pass
    return {"kill_switch_active": True, "orders_canceled": canceled}


@app.post("/api/kill/reset")
def kill_reset():
    mode_manager.reset_kill_switch()
    return {"kill_switch_active": False}


# ---------------------------------------------------------------------------
#  Portfolio / positions / history / stats
# ---------------------------------------------------------------------------

def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _usdt_coin(balance: dict) -> dict:
    """The raw Bybit USDT coin record (all values denominated in USDT)."""
    try:
        for c in balance["info"]["result"]["list"][0].get("coin", []) or []:
            if c.get("coin") == "USDT":
                return c
    except Exception:
        pass
    return {}


def _usdt_equity(balance: dict) -> tuple[float, float]:
    """Return (equity, available) in USDT.

    IMPORTANT: we use the per-coin USDT fields, which are denominated in USDT.
    The account-level `totalEquity` is in USD, and Bybit (esp. demo) marks
    1 USDT slightly off 1 USD — mixing USD equity with USDT cash invents a phantom
    P&L. Staying in USDT keeps everything consistent. coin.equity already includes
    unrealized PnL, so it's realtime."""
    c = _usdt_coin(balance)
    equity = _f(c.get("equity"))
    avail = _f(c.get("availableToWithdraw"))
    if equity > 0:
        if avail == 0:
            # cross-margin sometimes leaves coin.availableToWithdraw blank
            try:
                avail = _f(balance["info"]["result"]["list"][0].get("totalAvailableBalance"))
            except Exception:
                avail = _f(c.get("walletBalance"))
        return equity, avail
    # Fallbacks if the raw coin record isn't present.
    total = balance.get("total", {}) or {}
    free = balance.get("free", {}) or {}
    return _f(total.get("USDT")), _f(free.get("USDT"))


@app.get("/api/portfolio")
def get_portfolio():
    balance = exchange.fetch_balance()
    positions = exchange.fetch_positions()
    equity, cash = _usdt_equity(balance)
    unrealized = sum(float(p.get("unrealizedPnl") or 0) for p in positions)

    # Snapshot equity for the curve/drawdown — but THROTTLE to ~once a minute so
    # fast polling doesn't flood the curve or skew the (hourly-assumed) Sharpe.
    # Only this environment's history (paper vs live are separate accounts).
    curve = db.list_equity(mode=mode_manager.mode)
    snapshot_due = True
    if curve:
        try:
            last_dt = datetime.fromisoformat(curve[-1]["ts"])
            if (datetime.now(timezone.utc) - last_dt).total_seconds() < 60:
                snapshot_due = False
        except Exception:
            pass
    if equity > 0 and snapshot_due:
        db.record_equity(equity, cash, unrealized, mode_manager.mode)

    # Max-drawdown auto-stop: if the curve has fallen past the configured limit,
    # engage the kill switch here too (not only at execution time).
    breached, dd, limit = engine.drawdown_guard()
    if breached and not mode_manager.kill_switch_active:
        mode_manager.engage_kill_switch()

    # DEPOSIT-PROOF P&L: trading P&L = realized (closed trades) + unrealized (open).
    # (Using equity − baseline would count deposits/withdrawals as profit.)
    closed = exchange.fetch_closed_trades(db.get_trading_config().get("symbol_universe"))
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    day_start_ms = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    realized_all = sum(t.get("realized") or 0 for t in closed)
    realized_today = sum(t.get("realized") or 0 for t in closed if (t.get("closed_at") or 0) >= day_start_ms)
    todays_rows = [r for r in curve if r["ts"].startswith(today)]
    unreal_start = float(todays_rows[0].get("unrealized") or 0) if todays_rows else unrealized
    all_time_pnl = realized_all + unrealized
    todays_pnl = realized_today + (unrealized - unreal_start)

    return {
        "mode": mode_manager.mode,
        "total_value": round(equity, 2),
        "available_balance": round(cash, 2),
        "unrealized_pnl": round(unrealized, 2),
        "todays_pnl": round(todays_pnl, 2),
        "all_time_pnl": round(all_time_pnl, 2),
        "open_positions": len(positions),
        "drawdown_pct": dd,
        "max_drawdown_pct": limit,
        "drawdown_breached": breached,
        "balance_error": balance.get("error"),
    }


def _sltp(p: dict) -> tuple:
    """Stop-loss / take-profit attached to a position (Bybit stores them there)."""
    info = p.get("info") or {}
    sl = p.get("stopLossPrice") or info.get("stopLoss")
    tp = p.get("takeProfitPrice") or info.get("takeProfit")
    sl = _f(sl) if str(sl) not in ("", "0", "0.0", "None", "0E-8") else None
    tp = _f(tp) if str(tp) not in ("", "0", "0.0", "None", "0E-8") else None
    return (sl or None), (tp or None)


@app.get("/api/positions")
def get_positions():
    out = []
    for p in exchange.fetch_positions():
        sl, tp = _sltp(p)
        out.append({
            "symbol": p.get("symbol"),
            "side": p.get("side"),
            "size": p.get("contracts"),
            "entry_price": p.get("entryPrice"),
            "mark_price": p.get("markPrice"),
            "unrealized_pnl": p.get("unrealizedPnl"),
            "liquidation_price": p.get("liquidationPrice"),
            "leverage": p.get("leverage"),
            "stop_loss": sl,
            "take_profit": tp,
        })
    return out


@app.get("/api/orders")
def get_orders(limit: int = 200):
    return db.list_orders(limit=limit)


@app.get("/api/equity")
def get_equity():
    return db.list_equity(mode=mode_manager.mode)


def _fetch_closed_trades(per_sym: int = 100) -> list[dict]:
    """Bybit closed-PnL records (realized) across the universe, newest first."""
    return exchange.fetch_closed_trades(db.get_trading_config().get("symbol_universe"), per_sym)


@app.get("/api/trades")
def get_trades(limit: int = 200):
    """Current (open) trades + closed trade history with realized P&L."""
    open_trades = []
    for p in exchange.fetch_positions():
        sl, tp = _sltp(p)
        open_trades.append({
            "symbol": p.get("symbol"), "side": p.get("side"), "size": p.get("contracts"),
            "entry": p.get("entryPrice"), "mark": p.get("markPrice"),
            "unrealized": p.get("unrealizedPnl"), "leverage": p.get("leverage"),
            "liquidation": p.get("liquidationPrice"), "stop_loss": sl, "take_profit": tp,
        })
    closed = _fetch_closed_trades()
    return {
        "open": open_trades,
        "closed": closed[:limit],
        "closed_source": "bybit-closed-pnl" if closed else "none",
    }


def _stats_window(period: str, start: str, end: str):
    """Return (from_iso, to_iso, from_ms, to_ms) for a stats period."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    if period == "today":
        frm = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "1w":
        frm = now - timedelta(days=7)
    elif period == "1m":
        frm = now - timedelta(days=30)
    elif period == "custom" and start:
        frm = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    else:
        frm = None  # all time
    to = (datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
          if period == "custom" and end else now)
    return (frm.isoformat() if frm else None, to.isoformat(),
            int(frm.timestamp() * 1000) if frm else 0, int(to.timestamp() * 1000))


@app.get("/api/stats")
def get_stats(period: str = "all", start: str = "", end: str = ""):
    """Strategy stats over a window. Win rate / closed / profit factor come from
    Bybit's REALIZED closed trades; return/Sharpe/drawdown from the equity curve."""
    frm_iso, to_iso, frm_ms, to_ms = _stats_window(period, start, end)

    eq = [r for r in db.list_equity(mode=mode_manager.mode)
          if (not frm_iso or r["ts"] >= frm_iso) and r["ts"] <= to_iso]
    equity = [r["equity"] for r in eq]

    closed = [t for t in _fetch_closed_trades()
              if frm_ms <= (t.get("closed_at") or 0) <= to_ms]
    wins = [t for t in closed if (t.get("realized") or 0) > 0]
    gross_win = sum(t["realized"] for t in wins)
    gross_loss = abs(sum(t["realized"] for t in closed if (t.get("realized") or 0) <= 0))
    realized = sum(t.get("realized") or 0 for t in closed)
    unrealized = sum(_f(p.get("unrealizedPnl")) for p in exchange.fetch_positions())
    # DEPOSIT-PROOF return: (realized in window + current unrealized) over the
    # window's starting equity — deposits don't inflate the numerator.
    base = equity[0] if equity and equity[0] else None
    total_return = ((realized + unrealized) / base * 100) if base else 0.0

    return {
        "period": period,
        "total_return_pct": round(total_return, 2),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "sharpe": round(stats.sharpe(stats._returns(equity)), 2),
        "max_drawdown_pct": round(stats.max_drawdown(equity) * 100, 2),
        "num_closed_trades": len(closed),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (999.0 if gross_win else 0.0),
        "realized_pnl": round(sum(t.get("realized") or 0 for t in closed), 2),
    }


@app.get("/api/pnl")
def get_pnl():
    """DEPOSIT/WITHDRAWAL-PROOF P&L breakdown: trading P&L = unrealized (open
    positions) + realized (closed trades). Never uses equity−baseline, so adding
    or pulling funds can't show up as profit/loss."""
    balance = exchange.fetch_balance()
    positions = exchange.fetch_positions()
    equity = _usdt_equity(balance)[0]
    unrealized = sum(_f(p.get("unrealizedPnl")) for p in positions)
    closed = exchange.fetch_closed_trades(db.get_trading_config().get("symbol_universe"))
    realized = sum(t.get("realized") or 0 for t in closed)   # Bybit closedPnl = net of fees
    total_pnl = realized + unrealized
    return {
        "mode": mode_manager.mode,
        "total_value": round(equity, 2),
        "total_pnl": round(total_pnl, 2),
        "unrealized": round(unrealized, 2),
        "realized_booked": round(realized, 2),
        "num_closed": len(closed),
        "note": "Total = Unrealized + Realized (closed trades). Realized is net of fees & "
                "funding (Bybit closed-PnL). Deposits/withdrawals are excluded.",
    }


# ---------------------------------------------------------------------------
#  Config
# ---------------------------------------------------------------------------

@app.get("/api/config")
def get_config():
    return db.get_trading_config()


@app.put("/api/config")
def put_config(cfg: TradingConfig):
    # MERGE into the existing config instead of replacing it — otherwise any
    # key not in the pydantic model would be silently wiped on every UI save.
    merged = db.get_trading_config()
    merged.update(cfg.model_dump())
    db.save_trading_config(merged)
    return db.get_trading_config()


# ---------------------------------------------------------------------------
#  Decisions / transcript (Layer 1 output)
# ---------------------------------------------------------------------------

@app.get("/api/decisions")
def get_decisions():
    decisions_io.sync_index()   # pick up any newly-written files
    return db.list_decisions()


@app.get("/api/decisions/latest")
def get_latest_decision():
    d = decisions_io.latest_decision()
    if not d:
        raise HTTPException(status_code=404, detail="No decisions yet.")
    return d


@app.get("/api/ohlcv")
def get_ohlcv(symbol: str, timeframe: str = "15m", limit: int = 120):
    """Price candles for one symbol — powers the click-a-position chart."""
    candles = []
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception:
        candles = []
    if not candles:  # fall back to public mainnet data
        try:
            import ccxt
            pub = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
            candles = pub.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"OHLCV unavailable: {e}")
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": [{"t": c[0], "o": c[1], "h": c[2], "l": c[3], "c": c[4], "v": c[5]} for c in candles],
    }


@app.get("/api/decisions/file")
def get_decision_file(name: str):
    """Full content of one past decision (for the all-decisions history view)."""
    d = decisions_io.read_decision(name)
    if not d:
        raise HTTPException(status_code=404, detail="Decision file not found.")
    return {
        "filename": name,
        "timestamp": d.get("timestamp"),
        "symbol": d.get("symbol"),
        "transcript": d.get("transcript", {}),
        "final_decision": {k: d.get(k) for k in
                           ("action", "symbol", "size", "entry", "stop_loss",
                            "take_profit", "confidence", "rationale")},
    }


@app.get("/api/transcript/latest")
def get_latest_transcript():
    t = decisions_io.latest_transcript()
    if not t:
        raise HTTPException(status_code=404, detail="No transcript yet.")
    return t


@app.post("/api/decisions/action")
def decision_action(action: DecisionAction):
    """Approve -> execute on Bybit via the Layer 2 engine (in the active mode).
    Reject -> just record the rejection. The engine enforces the kill switch and
    the max-drawdown auto-stop before any order goes out."""
    d = decisions_io.read_decision(action.filename)
    if not d:
        raise HTTPException(status_code=404, detail="Decision not found.")

    if not action.approve:
        db.set_decision_status(action.filename, "rejected")
        return {"filename": action.filename, "status": "rejected",
                "executed": False, "message": "Decision rejected — no order placed."}

    db.set_decision_status(action.filename, "approved")
    result = engine.execute_decision(d, decision_file=action.filename)
    return {"filename": action.filename,
            "status": "executed" if result["ok"] else "approved",
            "executed": result["ok"],
            "message": result["message"],
            "order_id": result.get("order_id"),
            "mode": mode_manager.mode}


@app.get("/api/engine/preflight")
def engine_preflight():
    """Expose the safety checks (kill switch + drawdown) for the UI to show."""
    breached, dd, limit = engine.drawdown_guard()
    return {
        "kill_switch_active": mode_manager.kill_switch_active,
        "drawdown_pct": dd,
        "max_drawdown_pct": limit,
        "drawdown_breached": breached,
        "can_trade": not (mode_manager.kill_switch_active or breached),
    }


# ---------------------------------------------------------------------------
#  Health
# ---------------------------------------------------------------------------

@app.get("/api/debug/balance")
def debug_balance():
    """Raw balance view for troubleshooting (no secrets). Shows where funds are
    so we can tell Unified vs Funding vs Spot apart."""
    b = exchange.fetch_balance()
    info = b.get("info", {}) or {}
    accounts = []
    try:
        for acct in info.get("result", {}).get("list", []):
            accounts.append({
                "accountType": acct.get("accountType"),
                "totalEquity": acct.get("totalEquity"),
                "totalWalletBalance": acct.get("totalWalletBalance"),
                "totalPerpUPL": acct.get("totalPerpUPL"),
                "totalAvailableBalance": acct.get("totalAvailableBalance"),
                "coins": [{"coin": c.get("coin"), "walletBalance": c.get("walletBalance"),
                           "unrealisedPnl": c.get("unrealisedPnl")}
                          for c in acct.get("coin", []) if _f(c.get("walletBalance")) != 0],
            })
    except Exception:
        pass
    return {
        "mode": mode_manager.mode,
        "paper_backend": mode_manager.status().get("paper_backend"),
        "ccxt_total_USDT": (b.get("total") or {}).get("USDT"),
        "ccxt_free_USDT": (b.get("free") or {}).get("USDT"),
        "error": b.get("error"),
        "accounts": accounts,
    }


@app.get("/api/backtest")
def run_backtest(symbol: str, timeframe: str = "1h", days: int = 90,
                 threshold: float = 50, sl_pct: float = 2.0, tp_pct: float = 4.0,
                 size_pct: float = 5.0, leverage: float = 3.0, fee_pct: float = 0.055):
    """Replay the mechanical screener over history and return stats + equity curve."""
    from . import backtest
    return backtest.run(symbol, timeframe=timeframe, days=days, threshold=threshold,
                        sl_pct=sl_pct, tp_pct=tp_pct, size_pct=size_pct,
                        leverage=leverage, fee_pct=fee_pct)


@app.get("/api/backtest/composite")
def run_backtest_composite(symbol: str, days: int = 90, threshold: float = 65,
                           timeframes: str = ""):
    """Backtest what the LIVE pipeline actually trades: multi-TF composite +
    regime gate + ATR stops + break-even/trail + time-stop + risk sizing.
    Pulls the management params from the saved config."""
    from . import backtest
    cfg = db.get_trading_config()
    tfs = [t for t in timeframes.split(",") if t] or cfg.get("scan_timeframes")
    return backtest.run_composite(
        symbol, timeframes=tfs, days=days, threshold=threshold,
        atr_stop_mult=float(cfg.get("atr_stop_mult", 1.5)),
        atr_tp_mult=float(cfg.get("atr_tp_mult", 3.0)),
        size_pct=float(cfg.get("position_size_pct", 5)),
        leverage=float(cfg.get("leverage", 3)),
        risk_per_trade_pct=float(cfg.get("risk_per_trade_pct", 1.0)),
        regime_min_adx=float(cfg.get("regime_min_adx", 22)),
        breakeven_atr=float(cfg.get("breakeven_atr", 1.0)),
        trail_atr_mult=float(cfg.get("trail_atr_mult", 1.5)),
        max_holding_hours=float(cfg.get("max_holding_hours", 48)))


@app.get("/api/backtest/sweep")
def run_backtest_sweep(symbol: str, days: int = 90):
    """Sweep auto_trade_confidence thresholds on the composite backtest —
    find where the edge actually peaks instead of guessing."""
    from . import backtest
    cfg = db.get_trading_config()
    return backtest.sweep(symbol, timeframes=cfg.get("scan_timeframes"), days=days,
                          atr_stop_mult=float(cfg.get("atr_stop_mult", 1.5)),
                          atr_tp_mult=float(cfg.get("atr_tp_mult", 3.0)),
                          size_pct=float(cfg.get("position_size_pct", 5)),
                          leverage=float(cfg.get("leverage", 3)),
                          risk_per_trade_pct=float(cfg.get("risk_per_trade_pct", 1.0)),
                          regime_min_adx=float(cfg.get("regime_min_adx", 22)),
                          breakeven_atr=float(cfg.get("breakeven_atr", 1.0)),
                          trail_atr_mult=float(cfg.get("trail_atr_mult", 1.5)),
                          max_holding_hours=float(cfg.get("max_holding_hours", 48)))


@app.get("/api/backtest/walkforward")
def run_backtest_walkforward(symbol: str, days: int = 180, folds: int = 3):
    """Walk-forward validation: tune on train, verify on unseen test slices.
    Trust ONLY the out-of-sample numbers."""
    from . import backtest
    cfg = db.get_trading_config()
    return backtest.walk_forward(symbol, timeframes=cfg.get("scan_timeframes"),
                                 days=days, folds=folds,
                                 atr_stop_mult=float(cfg.get("atr_stop_mult", 1.5)),
                                 atr_tp_mult=float(cfg.get("atr_tp_mult", 3.0)),
                                 size_pct=float(cfg.get("position_size_pct", 5)),
                                 leverage=float(cfg.get("leverage", 3)),
                                 risk_per_trade_pct=float(cfg.get("risk_per_trade_pct", 1.0)),
                                 regime_min_adx=float(cfg.get("regime_min_adx", 22)),
                                 breakeven_atr=float(cfg.get("breakeven_atr", 1.0)),
                                 trail_atr_mult=float(cfg.get("trail_atr_mult", 1.5)),
                                 max_holding_hours=float(cfg.get("max_holding_hours", 48)))


@app.get("/api/learner")
def learner_stats():
    """The feedback loop's state: samples, accuracy, per-condition win rates."""
    from . import learner
    import json as _json
    try:
        if learner.STATS_PATH.exists():
            return _json.loads(learner.STATS_PATH.read_text())
    except Exception:
        pass
    return {"meta": {"ok": False, "message": "No learner stats yet — needs closed trades."}}


@app.post("/api/learner/refit")
def learner_refit():
    """Force a retrain on all labeled closed trades."""
    from . import learner
    return learner.refit()


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mode": mode_manager.mode,
        "connectivity": exchange.connectivity_check(),
    }


# ---------------------------------------------------------------------------
#  Scanner (multi-timeframe screener) + automation
# ---------------------------------------------------------------------------

@app.get("/api/scan")
def get_scan():
    """Latest multi-timeframe scan table (all pairs x all scan timeframes),
    decorated with each pair's latest AI decision (action + confidence) if any."""
    s = scanner.latest()
    if not s:
        return {"rows": [], "timeframes": [], "data_source": None, "generated_at": None}
    # Cheap join: most-recent AI decision per symbol (list_decisions is newest-first).
    latest_by_sym = {}
    for d in db.list_decisions(200):
        sym = d.get("symbol")
        if sym and sym not in latest_by_sym:
            latest_by_sym[sym] = d
    for r in s.get("rows", []):
        d = latest_by_sym.get(r["symbol"])
        r["ai"] = ({"action": d.get("action"), "confidence": d.get("confidence"),
                    "status": d.get("status"), "ts": d.get("ts")} if d else None)
    return s


@app.get("/api/scan/{symbol:path}")
def get_scan_symbol(symbol: str):
    """Per-pair detail: the latest scan row for one symbol."""
    s = scanner.latest() or {}
    row = next((r for r in s.get("rows", []) if r["symbol"] == symbol), None)
    if not row:
        raise HTTPException(status_code=404, detail="Symbol not in latest scan.")
    return {"generated_at": s.get("generated_at"), "timeframes": s.get("timeframes"), "row": row}


@app.post("/api/scan/run")
def run_scan_now():
    """Trigger a scan immediately (mechanical, no tokens)."""
    return scheduler.run_once()


@app.get("/api/automation")
def get_automation():
    return scheduler.status()


@app.post("/api/automation")
def set_automation(cfg: AutomationConfig):
    """Update the automation knobs. Merges into the trading config."""
    current = db.get_trading_config()
    current.update(cfg.model_dump())
    db.save_trading_config(current)
    db.add_alert("info", "system",
                 f"Automation updated: auto_trade={cfg.auto_trade}, "
                 f"threshold={cfg.auto_trade_confidence}%, interval={cfg.scan_interval_min}m.")
    return scheduler.status()


@app.get("/api/alerts")
def get_alerts(limit: int = 100):
    return db.list_alerts(limit=limit)


def _humanize_stream(text: str) -> str:
    """Turn Claude's stream-json events into a readable live activity feed."""
    import json as _json
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.startswith("{"):
            out.append(line)            # our own header line
            continue
        try:
            ev = _json.loads(line)
        except Exception:
            continue
        t = ev.get("type")
        if t == "system":
            out.append("• session started")
        elif t == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    out.append(c["text"].strip())
                elif c.get("type") == "tool_use":
                    name = c.get("name")
                    inp = c.get("input", {}) or {}
                    if name == "Task":
                        who = inp.get("subagent_type") or inp.get("description") or "subagent"
                        out.append(f"  → running agent: {who}")
                    elif name in ("Bash", "Read", "WebSearch"):
                        out.append(f"  → {name}")
        elif t == "result":
            cost = ev.get("total_cost_usd")
            out.append(f"✓ debate complete{f' (cost ${cost})' if cost else ''}")
    # Collapse consecutive duplicate lines (subagents each emit 'session started',
    # the scan fires several Bash calls, etc.) so the feed stays readable.
    deduped = []
    for line in out:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)


@app.get("/api/analyze/log")
def analyze_log(lines: int = 800, raw: bool = False):
    """Live, human-readable progress of the headless AI debate."""
    from .scheduler import AI_LOG_PATH
    text = AI_LOG_PATH.read_text() if AI_LOG_PATH.exists() else ""
    text = "\n".join(text.splitlines()[-lines:])
    return {"running": scheduler._ai_running, "log": text if raw else _humanize_stream(text)}


@app.post("/api/analyze/run")
def analyze_run():
    """Trigger the AI debate headlessly NOW (from the dashboard). Runs in a
    background thread so the request returns immediately; watch the Alerts feed
    for progress. Uses your Claude Code subscription login, not an API key."""
    import threading
    from .scheduler import _claude_bin
    if scheduler._ai_running:
        return {"started": False, "message": "An AI analysis is already running."}
    if _claude_bin() is None:
        raise HTTPException(status_code=400,
                            detail="Claude Code CLI not found. Install it and run /login first.")

    def _job():
        scheduler.run_ai_analyze()
        try:
            scheduler.run_once()  # process the fresh decision (auto-trade if eligible)
        except Exception:
            pass

    threading.Thread(target=_job, daemon=True, name="manual-analyze").start()
    return {"started": True, "message": "AI debate started — watch the Alerts feed."}


@app.post("/api/trade/manual/{symbol:path}")
def trade_manual(symbol: str):
    """'Trade now' from the scanner: build a mechanical decision for this symbol
    from the latest scan and execute it in the active mode (safety preflight
    still applies). Manual, on-demand — not the auto-loop."""
    s = scanner.latest() or {}
    row = next((r for r in s.get("rows", []) if r["symbol"] == symbol), None)
    if not row:
        raise HTTPException(status_code=404, detail="Symbol not in latest scan; run a scan first.")
    comp = row["composite"]
    if comp["direction"] == "flat":
        raise HTTPException(status_code=400, detail="Signal is flat — no directional trade.")
    decision = scheduler._row_to_decision(row, comp, db.get_trading_config())
    result = engine.execute_decision(decision)
    db.add_alert("info" if result["ok"] else "warning", "auto_trade",
                 f"Manual trade {symbol}: {result['message']}", symbol=symbol)
    return {"ok": result["ok"], "message": result["message"], "decision": decision,
            "mode": mode_manager.mode}


# ---------------------------------------------------------------------------
#  Claude Code connection status (the subscription-covered AI step)
# ---------------------------------------------------------------------------

@app.get("/api/claude/status")
def claude_status():
    """Report whether Claude Code is set up for this project. The actual login
    happens INSIDE Claude Code (its own account login) — a web app cannot drive
    your Max subscription, so this only reports status + the steps to connect."""
    agents_dir = PROJECT_ROOT / ".claude" / "agents"
    commands_dir = PROJECT_ROOT / ".claude" / "commands"
    agents_installed = agents_dir.exists() and any(agents_dir.glob("*.md"))
    analyze_installed = (commands_dir / "analyze.md").exists()
    decisions = db.list_decisions(1)
    return {
        "cli_installed": shutil.which("claude") is not None,
        "agents_installed": agents_installed,
        "analyze_command_installed": analyze_installed,
        "last_decision": decisions[0] if decisions else None,
        "project_root": str(PROJECT_ROOT),
        "steps": [
            "Install Claude Code: npm i -g @anthropic-ai/claude-code",
            "In a terminal at this project, run: claude",
            "Inside Claude Code, run /login and sign in with your Claude Max account (one-time).",
            "Run: bash agents/claude_code/install_agents.sh   (installs the agents)",
            "Type /analyze to run the multi-agent debate. It writes a decision the dashboard auto-loads.",
        ],
    }


# ---------------------------------------------------------------------------
#  Serve the built frontend (same origin) — so ONE port sits behind nginx.
#  Only mounts if frontend/dist exists (i.e. you've run `npm run build`).
#  This must be LAST so it doesn't shadow the /api routes above.
# ---------------------------------------------------------------------------
_DIST = PROJECT_ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
