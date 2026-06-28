"""
backtest.py
===========
Replays the MECHANICAL screener (indicators.signal) over historical candles so
you can measure whether the strategy actually has an edge — BEFORE risking money.

It backtests the single-timeframe signal (the same `signal()` the live scanner
uses per timeframe). It does NOT backtest the AI debate — running thousands of
historical debates would be wildly expensive; this validates the mechanical
layer, which is the part that needs proving.

Honest about costs: applies taker fees on entry+exit. Funding is NOT modelled
(note it when reading results). Fills assume stop/target hit intrabar at the
level (optimistic on slippage). Treat results as directional, not gospel.
"""

from __future__ import annotations
import time

from . import indicators

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
         "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _fetch_history(symbol: str, timeframe: str, bars: int) -> list[list]:
    """Public mainnet OHLCV, paginated back `bars` candles."""
    import ccxt
    ex = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}, "timeout": 15000})
    tf_ms = TF_MS.get(timeframe, 3_600_000)
    since = ex.milliseconds() - bars * tf_ms
    out, guard = [], 0
    while len(out) < bars and guard < 30:
        guard += 1
        chunk = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not chunk:
            break
        out += chunk
        since = chunk[-1][0] + tf_ms
        if len(chunk) < 1000:
            break
        time.sleep(ex.rateLimit / 1000)
    seen = {c[0]: c for c in out}
    return [seen[k] for k in sorted(seen)]


def _max_drawdown(eq: list[float]) -> float:
    peak, mdd = -1e18, 0.0
    for e in eq:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd * 100


def _sharpe(rets: list[float], periods_per_year: float) -> float:
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = var ** 0.5
    return round((mean / sd) * (periods_per_year ** 0.5), 2) if sd else 0.0


def run(symbol: str, timeframe: str = "1h", days: int = 90, threshold: float = 50,
        sl_pct: float = 2.0, tp_pct: float = 4.0, size_pct: float = 5.0,
        leverage: float = 3.0, fee_pct: float = 0.055, ohlcv=None) -> dict:
    tf_ms = TF_MS.get(timeframe, 3_600_000)
    per_day = max(1, round(86_400_000 / tf_ms))
    bars = min(5000, max(200, int(days * per_day)))

    if ohlcv is None:
        try:
            ohlcv = _fetch_history(symbol, timeframe, bars)
        except Exception as e:
            return {"error": f"history fetch failed: {e}"}
    if not ohlcv or len(ohlcv) < 80:
        return {"error": "not enough history for this symbol/timeframe/period."}

    closes = [c[4] for c in ohlcv]
    highs = [c[2] for c in ohlcv]
    lows = [c[3] for c in ohlcv]
    tss = [c[0] for c in ohlcv]

    fee = fee_pct / 100.0
    lev = max(0.0, leverage)
    size = size_pct / 100.0
    equity = 10000.0
    warm = 60
    pos = None
    trades, eq_curve, bar_rets = [], [], []
    prev_eq = equity

    for i in range(warm, len(ohlcv)):
        # 1) manage an open position against THIS bar's range
        if pos:
            hit = exitp = None
            if pos["dir"] == "long":
                if lows[i] <= pos["sl"]: hit, exitp = "sl", pos["sl"]
                elif highs[i] >= pos["tp"]: hit, exitp = "tp", pos["tp"]
            else:
                if highs[i] >= pos["sl"]: hit, exitp = "sl", pos["sl"]
                elif lows[i] <= pos["tp"]: hit, exitp = "tp", pos["tp"]
            if hit:
                raw = (exitp / pos["entry"] - 1) if pos["dir"] == "long" else (pos["entry"] / exitp - 1)
                ret = (raw - 2 * fee) * size * lev          # P&L as fraction of equity
                equity *= (1 + ret)
                trades.append({
                    "dir": pos["dir"], "entry": round(pos["entry"], 6), "exit": round(exitp, 6),
                    "result": hit, "ret_pct": round(ret * 100, 3),
                    "t_in": pos["t"], "t_out": tss[i],
                })
                pos = None

        # 2) consider a NEW entry at this close using the signal up to here
        if not pos:
            sig = indicators.signal(indicators.analyze(ohlcv[:i + 1]))
            conf = abs(sig["score"]) * 100
            if conf >= threshold and sig["direction"] in ("long", "short"):
                entry = closes[i]
                d = sig["direction"]
                pos = {
                    "dir": d, "entry": entry, "t": tss[i],
                    "sl": entry * (1 - sl_pct / 100) if d == "long" else entry * (1 + sl_pct / 100),
                    "tp": entry * (1 + tp_pct / 100) if d == "long" else entry * (1 - tp_pct / 100),
                }

        eq_curve.append({"t": tss[i], "equity": round(equity, 2)})
        bar_rets.append(equity / prev_eq - 1)
        prev_eq = equity

    # --- stats ---
    rets = [t["ret_pct"] / 100 for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    eq_vals = [p["equity"] for p in eq_curve]
    periods_per_year = (365 * 86_400_000) / tf_ms

    return {
        "symbol": symbol, "timeframe": timeframe, "days": days,
        "bars": len(ohlcv), "from": tss[0], "to": tss[-1],
        "params": {"threshold": threshold, "sl_pct": sl_pct, "tp_pct": tp_pct,
                   "size_pct": size_pct, "leverage": leverage, "fee_pct": fee_pct},
        "stats": {
            "total_return_pct": round((equity / 10000 - 1) * 100, 2),
            "num_trades": len(trades),
            "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (999.0 if gross_win else 0.0),
            "max_drawdown_pct": round(_max_drawdown(eq_vals), 2),
            "sharpe": _sharpe(bar_rets, periods_per_year),
            "avg_win_pct": round(sum(wins) / len(wins) * 100, 3) if wins else 0.0,
            "avg_loss_pct": round(sum(losses) / len(losses) * 100, 3) if losses else 0.0,
            "ending_equity": round(equity, 2),
        },
        "equity": eq_curve[:: max(1, len(eq_curve) // 400)],   # downsample for the chart
        "trades": trades[-100:],
    }
