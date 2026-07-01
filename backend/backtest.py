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


# =============================================================================
# COMPOSITE BACKTEST — replays what the LIVE system actually trades:
# the multi-timeframe composite + regime gate + ATR stops + break-even/trail +
# time-stop + risk-based sizing. The single-TF run() above validates one
# signal; this validates the whole mechanical pipeline.
# =============================================================================

def _fetch_multi(symbol: str, timeframes: list[str], days: int) -> dict:
    out = {}
    for tf in timeframes:
        per_day = max(1, round(86_400_000 / TF_MS.get(tf, 3_600_000)))
        bars = min(5000, max(200, int(days * per_day) + 130))
        out[tf] = _fetch_history(symbol, tf, bars)
    return out


def run_composite(symbol: str, timeframes=None, days: int = 90, threshold: float = 65,
                  atr_stop_mult: float = 1.5, atr_tp_mult: float = 3.0,
                  size_pct: float = 5.0, leverage: float = 3.0,
                  risk_per_trade_pct: float = 1.0, regime_min_adx: float = 22.0,
                  breakeven_atr: float = 1.0, trail_atr_mult: float = 1.5,
                  max_holding_hours: float = 48.0, fee_pct: float = 0.055,
                  history: dict | None = None, quiet: bool = False) -> dict:
    """Walk the SHORTEST timeframe bar by bar; at each bar rebuild every
    timeframe's 120-candle window (exactly what the live scanner sees), gate by
    regime, enter on composite >= threshold, then manage the position with the
    same ATR stop / break-even / trail / time-stop logic the scheduler runs."""
    from . import indicators, scanner as _scanner

    timeframes = timeframes or ["15m", "1h", "4h", "1d"]
    if history is None:
        try:
            history = _fetch_multi(symbol, timeframes, days)
        except Exception as e:
            return {"error": f"history fetch failed: {e}"}
    step_tf = min(timeframes, key=lambda t: TF_MS.get(t, 1e18))
    ref_tf = timeframes[-1]
    step = history.get(step_tf) or []
    if len(step) < 200:
        return {"error": "not enough history for this symbol/timeframes/period."}

    # Pointer per TF into its candle list (advance as time moves forward).
    ptr = {tf: 0 for tf in timeframes}
    fee = fee_pct / 100.0
    equity, warm = 10000.0, 130
    pos = None
    trades, eq_curve, bar_rets = [], [], []
    prev_eq = equity
    step_ms = TF_MS.get(step_tf, 900_000)

    for i in range(warm, len(step)):
        ts, o, h, l, c, v = step[i][:6]

        # --- manage an open position against THIS bar ------------------------
        if pos:
            hit = exitp = None
            if pos["dir"] == "long":
                if l <= pos["sl"]:
                    hit, exitp = ("be" if abs(pos["sl"] - pos["entry"]) < 1e-9 else
                                  ("trail" if pos.get("trailed") else "sl")), pos["sl"]
                elif h >= pos["tp"]:
                    hit, exitp = "tp", pos["tp"]
            else:
                if h >= pos["sl"]:
                    hit, exitp = ("be" if abs(pos["sl"] - pos["entry"]) < 1e-9 else
                                  ("trail" if pos.get("trailed") else "sl")), pos["sl"]
                elif l <= pos["tp"]:
                    hit, exitp = "tp", pos["tp"]
            if not hit and max_holding_hours > 0 and (ts - pos["t"]) > max_holding_hours * 3_600_000:
                hit, exitp = "time", c
            if hit:
                raw = (exitp / pos["entry"] - 1) if pos["dir"] == "long" else (pos["entry"] / exitp - 1)
                ret = (raw - 2 * fee) * pos["notional_frac"]
                equity *= (1 + ret)
                trades.append({"dir": pos["dir"], "entry": round(pos["entry"], 6),
                               "exit": round(exitp, 6), "result": hit,
                               "ret_pct": round(ret * 100, 3), "t_in": pos["t"], "t_out": ts})
                pos = None
            else:
                # Break-even + ATR trail (tighten only), same as the scheduler.
                atr_abs = pos["atr_abs"]
                profit = (c - pos["entry"]) if pos["dir"] == "long" else (pos["entry"] - c)
                if atr_abs > 0 and profit > 0:
                    new_sl = None
                    if breakeven_atr > 0 and profit >= breakeven_atr * atr_abs:
                        new_sl = pos["entry"]
                    if trail_atr_mult > 0 and profit >= trail_atr_mult * atr_abs:
                        t_sl = c - trail_atr_mult * atr_abs if pos["dir"] == "long" else c + trail_atr_mult * atr_abs
                        new_sl = max(new_sl or 0, t_sl) if pos["dir"] == "long" else min(new_sl or 1e18, t_sl)
                        if new_sl == t_sl:
                            pos["trailed"] = True
                    if new_sl is not None:
                        if pos["dir"] == "long" and new_sl > pos["sl"]:
                            pos["sl"] = new_sl
                        elif pos["dir"] == "short" and new_sl < pos["sl"]:
                            pos["sl"] = new_sl

        # --- consider a new entry (rebuild what the scanner would see) --------
        if not pos:
            per_tf, ref_ind = {}, None
            for tf in timeframes:
                series = history.get(tf) or []
                j = ptr[tf]
                while j < len(series) and series[j][0] + TF_MS.get(tf, 0) <= ts + step_ms:
                    j += 1          # candles CLOSED by the end of this step bar
                ptr[tf] = j
                window = series[max(0, j - 120):j]
                if len(window) < 60:
                    per_tf = {}
                    break
                ind = indicators.analyze(window)
                per_tf[tf] = {"indicators": ind, "signal": indicators.signal(ind)}
                if tf == ref_tf:
                    ref_ind = ind
            if per_tf and ref_ind:
                comp = _scanner.composite(per_tf)
                reg = indicators.regime(ref_ind, min_adx=regime_min_adx)
                gate_ok = (regime_min_adx <= 0) or reg["trend_ok"]
                if (gate_ok and comp["direction"] in ("long", "short")
                        and comp["confidence_pct"] >= threshold):
                    d = comp["direction"]
                    entry = c
                    atr_pct = ref_ind.get("atr_pct") or 2.0
                    atr_abs = entry * atr_pct / 100
                    sl_dist = atr_abs * (atr_stop_mult or 1.5)
                    tp_dist = atr_abs * (atr_tp_mult or 3.0)
                    sl = entry - sl_dist if d == "long" else entry + sl_dist
                    tp = entry + tp_dist if d == "long" else entry - tp_dist
                    # Sizing: config ceiling, optionally risk-normalized (same as engine).
                    notional_frac = (size_pct / 100.0) * leverage
                    if risk_per_trade_pct > 0 and sl_dist > 0:
                        notional_frac = min(notional_frac,
                                            (risk_per_trade_pct / 100.0) * entry / sl_dist)
                    pos = {"dir": d, "entry": entry, "t": ts, "sl": sl, "tp": tp,
                           "atr_abs": atr_abs, "notional_frac": notional_frac}

        eq_curve.append({"t": ts, "equity": round(equity, 2)})
        bar_rets.append(equity / prev_eq - 1)
        prev_eq = equity

    rets = [t["ret_pct"] / 100 for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    eq_vals = [p["equity"] for p in eq_curve]
    periods_per_year = (365 * 86_400_000) / step_ms
    result = {
        "symbol": symbol, "timeframes": timeframes, "days": days, "mode": "composite",
        "bars": len(step), "from": step[0][0], "to": step[-1][0],
        "params": {"threshold": threshold, "atr_stop_mult": atr_stop_mult,
                   "atr_tp_mult": atr_tp_mult, "risk_per_trade_pct": risk_per_trade_pct,
                   "regime_min_adx": regime_min_adx, "breakeven_atr": breakeven_atr,
                   "trail_atr_mult": trail_atr_mult, "max_holding_hours": max_holding_hours,
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
            "exit_breakdown": {k: sum(1 for t in trades if t["result"] == k)
                               for k in ("tp", "sl", "be", "trail", "time")},
        },
    }
    if not quiet:
        result["equity"] = eq_curve[:: max(1, len(eq_curve) // 400)]
        result["trades"] = trades[-100:]
    return result


def sweep(symbol: str, timeframes=None, days: int = 90,
          thresholds=(50, 55, 60, 65, 70, 75, 80), **kw) -> dict:
    """Run the composite backtest across confidence thresholds on ONE cached
    dataset — find where win rate / expectancy actually peaks instead of
    guessing 65."""
    timeframes = timeframes or ["15m", "1h", "4h", "1d"]
    try:
        history = _fetch_multi(symbol, timeframes, days)
    except Exception as e:
        return {"error": f"history fetch failed: {e}"}
    rows = []
    for th in thresholds:
        r = run_composite(symbol, timeframes, days, threshold=float(th),
                          history=history, quiet=True, **kw)
        if "error" in r:
            continue
        s = r["stats"]
        rows.append({"threshold": th, **{k: s[k] for k in
                     ("num_trades", "win_rate_pct", "profit_factor",
                      "total_return_pct", "max_drawdown_pct", "sharpe")}})
    best = max(rows, key=lambda x: (x["profit_factor"] if x["num_trades"] >= 5 else -1),
               default=None)
    return {"symbol": symbol, "timeframes": timeframes, "days": days,
            "sweep": rows, "best": best,
            "note": "best = highest profit factor with >=5 trades. Set auto_trade_confidence near it."}


def walk_forward(symbol: str, timeframes=None, days: int = 180, folds: int = 3,
                 thresholds=(55, 60, 65, 70, 75), **kw) -> dict:
    """Walk-forward validation: split history into `folds` sequential segments;
    in each fold, pick the best threshold on the TRAIN part and evaluate it on
    the unseen TEST part. If test results collapse vs train, the parameters are
    overfit — don't trust them live."""
    timeframes = timeframes or ["15m", "1h", "4h", "1d"]
    try:
        history = _fetch_multi(symbol, timeframes, days)
    except Exception as e:
        return {"error": f"history fetch failed: {e}"}
    step_tf = min(timeframes, key=lambda t: TF_MS.get(t, 1e18))
    step = history.get(step_tf) or []
    if len(step) < 600:
        return {"error": "not enough history for walk-forward (need more days)."}

    def _slice(h, t0, t1):
        return {tf: [c for c in series if t0 <= c[0] <= t1] for tf, series in h.items()}

    t_start, t_end = step[0][0], step[-1][0]
    span = (t_end - t_start) / (folds + 1)       # train = 2 spans sliding, test = 1
    results = []
    for f in range(folds):
        train_a = t_start + f * span
        train_b = train_a + span
        test_b = train_b + span
        train_h = _slice(history, train_a, train_b)
        test_h = _slice(history, train_b, test_b)
        best_th, best_pf = None, -1
        for th in thresholds:
            r = run_composite(symbol, timeframes, days, threshold=float(th),
                              history=train_h, quiet=True, **kw)
            if "error" in r or r["stats"]["num_trades"] < 3:
                continue
            pf = r["stats"]["profit_factor"]
            if pf > best_pf:
                best_pf, best_th = pf, th
        if best_th is None:
            results.append({"fold": f + 1, "skipped": "no tradeable threshold in train"})
            continue
        test_r = run_composite(symbol, timeframes, days, threshold=float(best_th),
                               history=test_h, quiet=True, **kw)
        results.append({
            "fold": f + 1, "picked_threshold": best_th, "train_profit_factor": best_pf,
            "test": {k: test_r["stats"][k] for k in
                     ("num_trades", "win_rate_pct", "profit_factor", "total_return_pct",
                      "max_drawdown_pct")} if "error" not in test_r else test_r,
        })
    oos = [r["test"] for r in results if isinstance(r.get("test"), dict)]
    avg = {}
    if oos:
        for k in ("win_rate_pct", "profit_factor", "total_return_pct"):
            avg[k] = round(sum(x[k] for x in oos) / len(oos), 2)
    return {"symbol": symbol, "timeframes": timeframes, "days": days, "folds": results,
            "out_of_sample_avg": avg,
            "note": "Trust the out-of-sample numbers, not the train numbers. "
                    "If test profit_factor < 1, the edge is not real yet."}
