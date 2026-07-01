"""
scanner.py
==========
The always-on MULTI-TIMEFRAME SCREENER (plain Python, NO Claude tokens).

For every pair in the universe and every timeframe in the scan set, it pulls
OHLCV, computes indicators, and turns them into a signal. It then blends the
per-timeframe signals into ONE composite per pair:

   confidence_pct : 0..100   (how strong + how aligned the signals are)
   direction      : long | short | flat

Higher timeframes carry more weight, and full agreement across timeframes adds
an alignment bonus. This composite confidence is what the scheduler compares to
your `auto_trade_confidence` threshold.

Market data is read from PUBLIC MAINNET (no key) so signals reflect the real
market even when you trade on testnet. An offline `demo=True` fallback generates
synthetic data so the system is testable without network.
"""

from __future__ import annotations
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from . import indicators, db, config

# Weight per timeframe — longer = more trustworthy for trend.
TF_WEIGHTS = {"1m": 0.5, "5m": 0.7, "15m": 1.0, "30m": 1.2, "1h": 2.0, "4h": 3.0, "1d": 3.0}


def _public_client():
    import ccxt
    return ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})


def _demo_ohlcv(symbol, seed_shift, limit=120):
    random.seed(hash(symbol) % 10000 + seed_shift)
    bases = {"BTC/USDT:USDT": 64000, "ETH/USDT:USDT": 3400, "SOL/USDT:USDT": 145,
             "XRP/USDT:USDT": 0.52, "BNB/USDT:USDT": 590}
    price = bases.get(symbol, 100.0)
    drift = random.uniform(-0.001, 0.0015)
    candles, ts = [], 1_700_000_000_000
    for _ in range(limit):
        o = price
        price *= (1 + drift + random.gauss(0, 0.012))
        c = price
        h = max(o, c) * (1 + abs(random.gauss(0, 0.004)))
        l = min(o, c) * (1 - abs(random.gauss(0, 0.004)))
        candles.append([ts, o, h, l, c, random.uniform(500, 5000)])
        ts += 60000
    return candles


def composite(per_tf: dict) -> dict:
    """Blend per-timeframe signals into one confidence% + direction.

    Alignment is MULTIPLICATIVE (scales with the signal), not a flat bonus —
    a flat +15 used to push weak signals over the trade threshold; now a weak
    signal stays weak even when timeframes agree, and disagreement actively
    shrinks confidence."""
    num = den = 0.0
    signs = []
    for tf, row in per_tf.items():
        w = TF_WEIGHTS.get(tf, 1.0)
        s = row["signal"]["score"]
        num += w * s
        den += w
        if abs(s) > 0.1:
            signs.append(1 if s > 0 else -1)
    blended = (num / den) if den else 0.0          # -1..1
    base = abs(blended) * 100
    # Alignment factor: fraction of active TFs agreeing with the majority.
    if signs:
        pos = sum(1 for x in signs if x > 0)
        agree = max(pos, len(signs) - pos) / len(signs)     # 0.5 .. 1.0
    else:
        agree = 0.5
    aligned = bool(signs) and agree == 1.0
    align_factor = 0.7 + 0.5 * (agree - 0.5) * 2            # 0.7 .. 1.2 (x1.2 = old +15 only when strong)
    conf = min(100.0, base * align_factor)
    direction = "long" if blended > 0.1 else "short" if blended < -0.1 else "flat"
    return {"confidence_pct": round(conf, 1), "direction": direction,
            "blended_score": round(blended, 3), "aligned": aligned,
            "align_factor": round(align_factor, 2)}


def _returns(closes):
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def _pearson(a, b):
    n = min(len(a), len(b))
    if n < 5:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((x - mb) ** 2 for x in b) ** 0.5
    return round(cov / (va * vb), 3) if va and vb else None


def _corr_matrix(ref_closes: dict) -> dict:
    """Pairwise return-correlation between every scanned symbol (ref timeframe).
    Used by the correlation cap: opening BTC+ETH+SOL longs is ONE trade at 3x
    risk, not three trades."""
    rets = {s: _returns(c) for s, c in ref_closes.items() if len(c) > 5}
    syms = list(rets)
    out = {}
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            c = _pearson(rets[a], rets[b])
            if c is not None:
                out[f"{a}|{b}"] = c
    return out


def pair_correlation(scan: dict, sym_a: str, sym_b: str) -> float | None:
    """Look up pairwise correlation from a scan result (either key order)."""
    m = (scan or {}).get("corr_matrix") or {}
    return m.get(f"{sym_a}|{sym_b}", m.get(f"{sym_b}|{sym_a}"))


def _attach_btc_relations(rows, ref_closes):
    """Add btc_correlation + relative_strength (vs BTC) to each row.
    Relative strength = pair's window return minus BTC's window return."""
    btc_sym = next((s for s in ref_closes if s.startswith("BTC/")), None)
    if not btc_sym:
        return
    btc_ret = _returns(ref_closes[btc_sym])
    btc_window = (ref_closes[btc_sym][-1] / ref_closes[btc_sym][0] - 1) * 100 if len(ref_closes[btc_sym]) > 1 else 0
    for r in rows:
        closes = ref_closes.get(r["symbol"])
        if not closes:
            continue
        corr = _pearson(_returns(closes), btc_ret) if r["symbol"] != btc_sym else 1.0
        win = (closes[-1] / closes[0] - 1) * 100 if len(closes) > 1 else 0
        r["btc_correlation"] = corr
        r["relative_strength_pct"] = round(win - btc_window, 2)


def scan(symbols=None, timeframes=None, demo=False) -> dict:
    cfg = db.get_trading_config()
    symbols = symbols or cfg.get("symbol_universe", [])
    timeframes = timeframes or cfg.get("scan_timeframes", ["15m", "1h", "4h", "1d"])

    client = None
    source = "bybit-mainnet-live"
    if not demo:
        try:
            client = _public_client()
        except Exception:
            demo = True
    if demo or client is None:
        source = "demo-synthetic"

    rows = []
    ref_tf = timeframes[-1]
    ref_closes: dict[str, list] = {}   # for BTC correlation / relative strength
    for i, sym in enumerate(symbols):
        per_tf = {}
        for tf in timeframes:
            try:
                if client:
                    ohlcv = client.fetch_ohlcv(sym, timeframe=tf, limit=120)
                else:
                    raise RuntimeError("demo")
            except Exception:
                ohlcv = _demo_ohlcv(sym, seed_shift=hash(tf) % 100)
                source = "demo-synthetic"
            ind = indicators.analyze(ohlcv)
            sig = indicators.signal(ind)
            per_tf[tf] = {"indicators": ind, "signal": sig}
            if tf == ref_tf:
                ref_closes[sym] = [c[4] for c in ohlcv]
        comp = composite(per_tf)

        # --- REGIME GATE (#1 win-rate killer: trend entries in chop) --------
        # Classify the reference timeframe's tape. In chop/squeeze, the trend
        # composite is not tradeable: zero the direction so nothing downstream
        # (auto-trade, AI gate, pick_candidates) enters, but keep the raw call
        # visible for the dashboard.
        reg = indicators.regime(per_tf[ref_tf]["indicators"],
                                min_adx=float(cfg.get("regime_min_adx", 22) or 0),
                                min_bb_width=float(cfg.get("regime_min_bb_width", 0) or 0))
        comp["regime"] = reg["kind"]
        if float(cfg.get("regime_min_adx", 22) or 0) > 0 and not reg["trend_ok"]:
            comp["raw_direction"] = comp["direction"]
            comp["direction"] = "flat"
            comp["confidence_pct"] = round(comp["confidence_pct"] * 0.6, 1)
            comp["regime_blocked"] = True

        # --- Market structure (funding/OI/long-short/order book) ---
        # Skip in demo to keep the offline path fast; live calls degrade to None.
        struct = {}
        if not demo and client is not None:
            try:
                from . import market_structure
                struct = market_structure.structure(sym)
            except Exception:
                struct = {}
        # Nudge confidence by structure bias aligned with the technical direction.
        sbias = struct.get("structure_bias", 0.0) or 0.0
        if comp["direction"] == "long":
            comp["confidence_pct"] = round(min(100.0, max(0.0, comp["confidence_pct"] + sbias * 8)), 1)
        elif comp["direction"] == "short":
            comp["confidence_pct"] = round(min(100.0, max(0.0, comp["confidence_pct"] - sbias * 8)), 1)

        rows.append({
            "symbol": sym,
            "last": round(per_tf[ref_tf]["indicators"]["last"], 6) if timeframes else None,
            "composite": comp,
            "structure": struct,
            "indicators_ref": {k: per_tf[ref_tf]["indicators"].get(k) for k in
                               ("rsi", "adx", "bb_pctb", "bb_width_pct", "stoch", "vwap_dist_pct",
                                "divergence", "support", "resistance", "atr_pct")},
            "per_tf": {tf: {
                "score": v["signal"]["score"],
                "direction": v["signal"]["direction"],
                "rsi": v["indicators"]["rsi"],
                "trend": v["indicators"]["trend"],
                "macd": v["indicators"]["macd"],
                "atr_pct": v["indicators"]["atr_pct"],
            } for tf, v in per_tf.items()},
        })

    # --- BTC correlation + relative strength (free, from the data we have) ---
    _attach_btc_relations(rows, ref_closes)

    # --- Learner calibration: blend in the win-probability learned from THIS
    # account's actual closed trades (only once there's enough history). ------
    if cfg.get("adaptive_weights", True):
        try:
            from . import learner
            learner.calibrate_rows(rows)
        except Exception:
            pass

    rows.sort(key=lambda r: r["composite"]["confidence_pct"], reverse=True)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": source,
        "timeframes": timeframes,
        "corr_matrix": _corr_matrix(ref_closes),
        "rows": rows,
    }
    # Persist latest scan for the dashboard + the Layer 1 agents.
    out = Path(config.DECISIONS_DIR) / "_scan_latest.json"
    out.write_text(json.dumps(result, indent=2))
    try:
        db.save_latest_scan(result)
    except Exception:
        pass
    return result


def latest() -> dict | None:
    try:
        s = db.get_latest_scan()
        if s:
            return s
    except Exception:
        pass
    out = Path(config.DECISIONS_DIR) / "_scan_latest.json"
    if out.exists():
        return json.loads(out.read_text())
    return None
