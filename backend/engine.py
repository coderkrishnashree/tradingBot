"""
engine.py
=========
LAYER 2 EXECUTION ENGINE (plain Python, NO Claude tokens).

This is the muscle. It takes a decision (produced by the Layer 1 debate and
approved by you in the UI) and turns it into a real order on Bybit, in whatever
environment is active (paper/testnet or live/mainnet). It also enforces the two
hard safety stops every time:

   1. KILL SWITCH  — if engaged, nothing executes.
   2. MAX DRAWDOWN — if the equity curve is down more than the configured limit,
                     we auto-engage the kill switch and refuse to trade.

Order sizing is derived from your config: a position is `position_size_pct` of
equity, scaled by `leverage`, converted to a base-currency amount at the current
price. Stop-loss and take-profit are attached to the entry order.

Every attempt is written to SQLite (`orders` table) — success or failure — so the
dashboard's history is the full record.
"""

from __future__ import annotations

from . import db, exchange, stats
from .config import mode_manager


class ExecutionResult(dict):
    """Just a dict with ok/message/order fields, for clarity at call sites."""


def _num(x):
    """Float or None (treats 0/blank as None)."""
    try:
        v = float(x)
        return v if v != 0 else None
    except (TypeError, ValueError):
        return None


def _fail(msg: str, **extra) -> ExecutionResult:
    return ExecutionResult(ok=False, message=msg, **extra)


def _ok(msg: str, **extra) -> ExecutionResult:
    return ExecutionResult(ok=True, message=msg, **extra)


def is_protective_order(o: dict) -> bool:
    """True for stop-loss / take-profit / any reduce-only or conditional order.
    These protect an open position and must NEVER be cancelled by our
    entry-replacement logic — cancelling them would strip the position's SL/TP."""
    info = o.get("info", {}) or {}
    if o.get("reduceOnly") or info.get("reduceOnly") in (True, "true", "True", "1", 1):
        return True
    # Bybit conditional / SL / TP orders carry these fields when set.
    for k in ("stopLoss", "takeProfit", "stopPrice", "triggerPrice", "stopOrderType",
              "tpslMode", "orderType"):
        v = info.get(k) or o.get(k)
        if k == "stopOrderType" and v and str(v).lower() != "unknownstoporder":
            return True
        if k in ("stopPrice", "triggerPrice") and _num(v):
            return True
    return False


def drawdown_guard() -> tuple[bool, float, float]:
    """Return (breached, current_dd_pct, limit_pct).
    Compares the worst peak-to-trough on the equity curve to the configured
    max_drawdown_pct. If breached, the caller should halt.
    """
    cfg = db.get_trading_config()
    limit = float(cfg.get("max_drawdown_pct", 20))
    # Only the CURRENT environment's equity — paper and live are different
    # accounts; mixing them shows a fake drawdown when you switch modes.
    rows = db.list_equity(mode=mode_manager.mode)
    # After a manual kill-switch reset we only measure drawdown from that moment
    # forward, so stale history can't immediately re-trip the auto-stop.
    ref = mode_manager.dd_reference_ts
    if ref:
        rows = [r for r in rows if r["ts"] >= ref]
    equity = [r["equity"] for r in rows]
    dd = stats.max_drawdown(equity) * 100 if equity else 0.0
    return dd >= limit, round(dd, 2), limit


def daily_loss_guard() -> tuple[bool, float, float]:
    """Return (breached, today_pnl_pct, limit_pct). 0 limit => disabled."""
    cfg = db.get_trading_config()
    limit = float(cfg.get("daily_loss_limit_pct", 0) or 0)
    if limit <= 0:
        return False, 0.0, 0.0
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    rows = [r for r in db.list_equity(mode=mode_manager.mode) if r["ts"].startswith(today)]
    if len(rows) < 2:
        return False, 0.0, limit
    first, cur = rows[0]["equity"], rows[-1]["equity"]
    pct = ((cur - first) / first * 100) if first else 0.0
    return (pct <= -limit), round(pct, 2), limit


def cooldown_remaining(symbol: str) -> float:
    """Minutes left on a symbol's trade cooldown (0 if none / disabled)."""
    cfg = db.get_trading_config()
    mins = float(cfg.get("min_minutes_between_trades", 0) or 0)
    if mins <= 0:
        return 0.0
    ts = db.last_order_ts(symbol)
    if not ts:
        return 0.0
    from datetime import datetime, timezone
    try:
        age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 60
        return max(0.0, round(mins - age_min, 1))
    except Exception:
        return 0.0


def preflight() -> ExecutionResult:
    """Run the safety checks that must pass before ANY order."""
    if mode_manager.kill_switch_active:
        return _fail("Kill switch is engaged — trading halted.")
    breached, dd, limit = drawdown_guard()
    if breached:
        mode_manager.engage_kill_switch()  # auto-stop
        return _fail(f"Max drawdown breached ({dd}% >= {limit}%). Kill switch auto-engaged.",
                     drawdown_pct=dd, limit_pct=limit)
    dl_breached, day_pct, dl_limit = daily_loss_guard()
    if dl_breached:
        mode_manager.engage_kill_switch()  # daily auto-stop
        return _fail(f"Daily loss limit hit ({day_pct}% <= -{dl_limit}%). Trading halted for today.",
                     daily_pnl_pct=day_pct, daily_limit_pct=dl_limit)
    return _ok("preflight passed", drawdown_pct=dd, limit_pct=limit)


def _equity_usdt() -> float:
    """Account equity in USDT, robust to Bybit unified/demo balance shapes."""
    bal = exchange.fetch_balance()
    try:
        acct = bal["info"]["result"]["list"][0]
        eq = float(acct.get("totalEquity") or 0) or float(acct.get("totalWalletBalance") or 0)
        if eq > 0:
            return eq
    except Exception:
        pass
    return float((bal.get("total", {}) or {}).get("USDT", 0) or 0)


def _amount_from_size(symbol: str, size_pct: float, leverage: int, price: float) -> float:
    """Convert a %-of-equity position into a base-currency amount."""
    equity = _equity_usdt()
    notional = equity * (size_pct / 100.0) * leverage
    if price <= 0:
        return 0.0
    return notional / price


def execute_decision(decision: dict, decision_file: str | None = None) -> ExecutionResult:
    """Execute one decision dict. Returns an ExecutionResult and logs to SQLite."""
    pre = preflight()
    if not pre["ok"]:
        return pre

    action = (decision.get("action") or "").lower()
    symbol = decision.get("symbol")
    if action == "hold":
        return _ok("Decision is HOLD — no order placed.")
    if action not in ("buy", "short", "sell", "close"):
        return _fail(f"Unknown action '{action}'.")

    cfg = db.get_trading_config()
    leverage = int(cfg.get("leverage", 3))
    client = exchange.get_client()
    mode = mode_manager.mode

    # Current price for sizing (fall back to the decision's entry).
    price = decision.get("entry")
    try:
        t = client.fetch_ticker(symbol)
        price = float(t.get("last") or price)
    except Exception:
        pass
    if not price:
        return _fail("Could not determine a price for sizing.")

    # --- CLOSE / SELL: reduce existing position -----------------------------
    if action in ("close", "sell"):
        positions = exchange.fetch_positions()
        pos = next((p for p in positions if p.get("symbol") == symbol and p.get("contracts")), None)
        if not pos:
            return _ok(f"No open position on {symbol} to close.")
        close_side = "sell" if pos.get("side") == "long" else "buy"
        amount = float(pos.get("contracts"))
        try:
            order = client.create_order(symbol, "market", close_side, amount, None,
                                        params={"reduceOnly": True})
        except Exception as e:
            db.record_order(mode=mode, symbol=symbol, side=close_side, order_type="market",
                            qty=amount, price=price, status="rejected",
                            decision_file=decision_file, raw=str(e))
            return _fail(f"Close order rejected: {e}")
        db.record_order(mode=mode, symbol=symbol, side=close_side, order_type="market",
                        qty=amount, price=price, status="submitted",
                        exchange_id=order.get("id"), decision_file=decision_file,
                        raw=str(order))
        if decision_file:
            db.set_decision_status(decision_file, "executed")
        return _ok(f"Close submitted for {symbol}.", order_id=order.get("id"))

    # --- BUY / SHORT: open a new position --------------------------------
    side = "buy" if action == "buy" else "sell"
    is_long = action == "buy"

    # If a position is already OPEN, don't stack another entry onto it.
    try:
        if any(p.get("contracts") for p in exchange.fetch_positions() if p.get("symbol") == symbol):
            if decision_file:
                db.set_decision_status(decision_file, "reviewed")
            return _ok(f"{symbol}: position already open — not adding to it.")
    except Exception:
        pass
    # Otherwise REPLACE any stale resting ENTRY limit with this fresh decision —
    # the AI's entry should reflect the newest debate, not an hour-old plan. We
    # ONLY cancel plain entry limits; stop-loss / take-profit / reduce-only orders
    # are left untouched so we never strip a position's protection.
    try:
        for o in client.fetch_open_orders(symbol):
            if is_protective_order(o):
                continue
            try:
                client.cancel_order(o["id"], symbol)
            except Exception:
                pass
    except Exception:
        pass

    # SIZE & LEVERAGE come straight from YOUR config — your risk budget / how much
    # you want to invest. The AI only sets direction, entry, and (cautious) SL/TP.
    size_pct = float(cfg.get("position_size_pct", 5))

    # ENTRY: honor the AI's planned entry as a LIMIT order when it's a better,
    # passive price on the correct side (short ABOVE market / long BELOW market).
    # Otherwise fall back to a market order — never chase past the plan.
    ai_entry = _num(decision.get("entry"))
    order_type, limit_price = "market", None
    if ai_entry:
        if is_long and ai_entry < price * 0.999:
            order_type, limit_price = "limit", ai_entry
        elif (not is_long) and ai_entry > price * 1.001:
            order_type, limit_price = "limit", ai_entry
    ref_price = limit_price or price

    amount = _amount_from_size(symbol, size_pct, leverage, ref_price)
    if amount <= 0:
        return _fail("Computed order size is zero (no equity / price). Fund the account or check keys.")
    try:
        amount = float(client.amount_to_precision(symbol, amount))
    except Exception:
        pass

    try:
        client.set_leverage(leverage, symbol)
    except Exception:
        pass

    # SL/TP: prefer the AI's structural levels; else derive from your config %.
    sl = _num(decision.get("stop_loss"))
    tp = _num(decision.get("take_profit"))
    if not sl:
        slp = float(cfg.get("stop_loss_pct", 2))
        sl = ref_price * (1 - slp / 100) if is_long else ref_price * (1 + slp / 100)
    if not tp:
        tpp = float(cfg.get("take_profit_pct", 4))
        tp = ref_price * (1 + tpp / 100) if is_long else ref_price * (1 - tpp / 100)

    def _p(v):
        try:
            return client.price_to_precision(symbol, v)
        except Exception:
            return str(v)
    params = {"stopLoss": _p(sl), "takeProfit": _p(tp)}

    try:
        if order_type == "limit":
            order = client.create_order(symbol, "limit", side, amount, float(_p(limit_price)), params=params)
        else:
            order = client.create_order(symbol, "market", side, amount, None, params=params)
    except Exception as e:
        db.record_order(mode=mode, symbol=symbol, side=side, order_type=order_type,
                        qty=amount, price=ref_price, status="rejected",
                        decision_file=decision_file, raw=str(e))
        return _fail(f"Entry order rejected: {e}")

    # A market order fills now (=> position opened => "executed"). A limit order
    # usually rests unfilled (=> NO position yet => "resting", not "executed").
    filled = order_type == "market" or order.get("status") in ("closed", "filled")
    status = "executed" if filled else "resting"
    db.record_order(mode=mode, symbol=symbol, side=side, order_type=order_type,
                    qty=amount, price=order.get("average") or ref_price,
                    status="filled" if filled else "resting", filled_qty=order.get("filled"),
                    avg_fill_price=order.get("average"),
                    exchange_id=order.get("id"), decision_file=decision_file, raw=str(order))
    if decision_file:
        db.set_decision_status(decision_file, status)
    if filled:
        placed = f"MARKET filled @ ~{_p(price)} — position OPEN"
    else:
        placed = f"LIMIT resting @ {_p(limit_price)} — waiting for a bounce, NOT a position yet"
    return _ok(f"{action.upper()} {symbol} {placed}: {amount} (lev {leverage}x, size {round(size_pct, 2)}%, "
               f"SL {_p(sl)}, TP {_p(tp)}).",
               order_id=order.get("id"), amount=amount, price=ref_price, status=status, mode=mode)
