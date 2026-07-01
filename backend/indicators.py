"""
indicators.py
=============
Pure-Python technical indicators + a transparent signal score. Shared by:
  - backend/scanner.py     (the always-on multi-timeframe screener)
  - agents/market_scan.py  (the Layer 1 data tool)

No numpy/pandas — every number is auditable so you can tune the strategy.

The scoring is intentionally simple and explainable. For one (pair, timeframe):
  signal in [-1, +1]  = weighted blend of trend, momentum (RSI), MACD sign, and
  price-vs-SMA20. Positive = bullish, negative = bearish, magnitude = strength.
"""

from __future__ import annotations


def sma(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


def ema(values, n):
    if len(values) < n:
        return None
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    for v in values[n:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(-n, 0):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain, avg_loss = sum(gains) / n, sum(losses) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def macd(closes):
    e12, e26 = ema(closes, 12), ema(closes, 26)
    if e12 is None or e26 is None:
        return None
    return round(e12 - e26, 6)


def atr(highs, lows, closes, n=14):
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(-n, 0):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return round(sum(trs) / n, 6)


def stdev(values, n):
    if len(values) < n:
        return None
    window = values[-n:]
    mean = sum(window) / n
    var = sum((v - mean) ** 2 for v in window) / n
    return var ** 0.5


def bollinger(closes, n=20, k=2):
    """Returns (lower, mid, upper, %B). %B: 0 = lower band, 1 = upper band."""
    mid = sma(closes, n)
    sd = stdev(closes, n)
    if mid is None or sd is None:
        return None
    upper, lower = mid + k * sd, mid - k * sd
    width = upper - lower
    pctb = ((closes[-1] - lower) / width) if width else 0.5
    return {"lower": lower, "mid": mid, "upper": upper, "pctb": round(pctb, 3),
            "width_pct": round(width / mid * 100, 2) if mid else None}


def stochastic(highs, lows, closes, n=14):
    """Stochastic %K (0-100). >80 overbought, <20 oversold."""
    if len(closes) < n:
        return None
    hh = max(highs[-n:])
    ll = min(lows[-n:])
    rng = hh - ll
    return round((closes[-1] - ll) / rng * 100, 1) if rng else 50.0


def adx(highs, lows, closes, n=14):
    """ADX (trend STRENGTH, not direction). >25 = trending, <20 = chop."""
    if len(closes) < 2 * n:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(-2 * n + 1, 0):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr_sum = sum(trs[-n:]) or 1e-9
    pdi = 100 * (sum(plus_dm[-n:]) / atr_sum)
    mdi = 100 * (sum(minus_dm[-n:]) / atr_sum)
    dx = 100 * abs(pdi - mdi) / ((pdi + mdi) or 1e-9)
    return round(dx, 1)


def vwap(ohlcv, n=20):
    """Rolling VWAP over last n candles (typical price * volume)."""
    rows = ohlcv[-n:]
    pv = sum(((c[2] + c[3] + c[4]) / 3) * c[5] for c in rows)
    vol = sum(c[5] for c in rows) or 1e-9
    return round(pv / vol, 6)


def swing_levels(highs, lows, lookback=50):
    """Nearest support (recent swing low) and resistance (recent swing high)."""
    h = highs[-lookback:]
    l = lows[-lookback:]
    return {"resistance": round(max(h), 6), "support": round(min(l), 6)}


def _swing_points(values, left=2, right=2):
    """Indices of local swing lows and highs (a point lower/higher than `left`
    bars before and `right` bars after it). Returns (low_idxs, high_idxs)."""
    lows, highs = [], []
    for i in range(left, len(values) - right):
        window_l = values[i - left:i]
        window_r = values[i + 1:i + 1 + right]
        if values[i] <= min(window_l) and values[i] <= min(window_r):
            lows.append(i)
        if values[i] >= max(window_l) and values[i] >= max(window_r):
            highs.append(i)
    return lows, highs


def _rsi_series(closes, n=14):
    """RSI value at every index (None until warm). Wilder-free simple average,
    consistent with rsi() above."""
    out = [None] * len(closes)
    for i in range(n, len(closes)):
        out[i] = rsi(closes[:i + 1], n)
    return out


def rsi_divergence(closes, n=14, lookback=40):
    """Swing-point RSI divergence over the last `lookback` bars.
    Bullish: price makes a LOWER swing low but RSI makes a HIGHER low.
    Bearish: price makes a HIGHER swing high but RSI makes a LOWER high.
    Returns 'bullish', 'bearish', or None."""
    if len(closes) < lookback + n:
        return None
    tail = closes[-(lookback + n + 1):]   # rsi(n) only needs n+1 bars of context
    seg = tail[-lookback:]
    lows, highs = _swing_points(seg)
    rsis = _rsi_series(tail, n)[-lookback:]
    # Compare the two most recent swing points of each kind.
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if rsis[a] is not None and rsis[b] is not None:
            if seg[b] < seg[a] and rsis[b] > rsis[a]:
                return "bullish"
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if rsis[a] is not None and rsis[b] is not None:
            if seg[b] > seg[a] and rsis[b] < rsis[a]:
                return "bearish"
    return None


def regime(ind: dict, min_adx: float = 22.0, min_bb_width: float = 0.0) -> dict:
    """Classify the tape: 'trend' (tradeable with trend signals), 'chop'
    (mean-reversion only / skip), or 'squeeze' (coiled, breakout watch).
    Used as the entry gate — trend-following entries in chop are the #1
    win-rate killer."""
    adx_v = ind.get("adx") or 0.0
    bbw = ind.get("bb_width_pct")
    if bbw is not None and bbw < max(min_bb_width, 1.0):
        kind = "squeeze"
    elif adx_v >= min_adx:
        kind = "trend"
    else:
        kind = "chop"
    return {"kind": kind, "adx": adx_v, "bb_width_pct": bbw,
            "trend_ok": kind == "trend"}


def analyze(ohlcv) -> dict:
    """Compute the full indicator set for one OHLCV series [[ts,o,h,l,c,v], ...]."""
    closes = [c[4] for c in ohlcv]
    highs = [c[2] for c in ohlcv]
    lows = [c[3] for c in ohlcv]
    last = closes[-1]
    s20, s50 = sma(closes, 20), sma(closes, 50)
    a = atr(highs, lows, closes)
    trend = "neutral"
    if s20 and s50:
        if last > s20 > s50:
            trend = "up"
        elif last < s20 < s50:
            trend = "down"
    pct = round((last / closes[-25] - 1) * 100, 2) if len(closes) >= 25 else None
    bb = bollinger(closes)
    vw = vwap(ohlcv)
    return {
        "last": last, "sma20": s20, "sma50": s50,
        "rsi": rsi(closes), "macd": macd(closes), "atr": a,
        "atr_pct": round(a / last * 100, 2) if a and last else None,
        "trend": trend, "pct_change": pct,
        # --- deeper technicals ---
        "bb_pctb": bb["pctb"] if bb else None,
        "bb_width_pct": bb["width_pct"] if bb else None,
        "stoch": stochastic(highs, lows, closes),
        "adx": adx(highs, lows, closes),
        "vwap": vw,
        "vwap_dist_pct": round((last / vw - 1) * 100, 2) if vw else None,
        "divergence": rsi_divergence(closes),
        **swing_levels(highs, lows),
    }


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def signal(ind: dict) -> dict:
    """Entry-quality score in [-0.9, +0.9]. Separates DIRECTIONAL BIAS from
    ENTRY QUALITY so it stops rewarding chasing already-extended moves.

    bias        = trend direction x ADX strength x (lightly) confirmations
    exhaustion  = penalty for entering INTO an oversold/overbought extreme
                  (the 'don't short the already-bleeding one' fix)
    freshness   = penalty for entering far from VWAP/mean (chasing)
    room        = penalty when price is jammed against the level you'd target
                  (poor reward:risk from here)
    final = bias x freshness x room, shrunk by exhaustion; capped at 0.9.
    """
    last, s20 = ind.get("last"), ind.get("sma20")
    m, r, adx_v = ind.get("macd"), ind.get("rsi"), ind.get("adx")
    bb, vwd, atrp = ind.get("bb_pctb"), ind.get("vwap_dist_pct"), ind.get("atr_pct")
    sup, res, div = ind.get("support"), ind.get("resistance"), ind.get("divergence")

    # --- 1) DIRECTIONAL BIAS (one trend factor, scaled by REAL trend strength) ---
    trend_dir = {"up": 1.0, "down": -1.0}.get(ind.get("trend"), 0.0)
    if trend_dir == 0 and last and s20:
        trend_dir = 1.0 if last > s20 else -1.0
    adx_strength = _clamp(((adx_v or 0) - 15) / 25, 0.0, 1.0)   # real trend only > ADX 15
    # Same-family confirmations add only a LITTLE (avoids fake 4x-counted confluence).
    confirms = 0
    if m is not None and trend_dir:
        confirms += 1 if (m > 0) == (trend_dir > 0) else -1
    if vwd is not None and trend_dir:
        confirms += 1 if (vwd > 0) == (trend_dir > 0) else -1
    confirm_factor = 0.6 + 0.4 * max(0, confirms) / 2          # 0.6 .. 1.0
    bias = trend_dir * adx_strength * confirm_factor            # [-1, 1]

    # --- 2) EXHAUSTION: penalize entering INTO an extreme (bounce/squeeze risk) ---
    against = 0.0
    if r is not None:
        if bias < 0 and r <= 35:        # shorting into oversold
            against = (35 - r) / 35
        elif bias > 0 and r >= 65:      # buying into overbought
            against = (r - 65) / 35
    if bb is not None:
        if bias < 0 and bb < 0.1:
            against = max(against, (0.1 - bb) / 0.1)
        elif bias > 0 and bb > 0.9:
            against = max(against, (bb - 0.9) / 0.1)
    against = _clamp(against, 0.0, 1.0)

    # --- 3) FRESHNESS: penalize chasing far from the mean (VWAP) ---
    extension = min(1.0, abs(vwd or 0) / 3.0)                   # 3% from VWAP = stretched
    freshness = 1.0 - 0.5 * extension                          # 0.5 .. 1.0

    # --- 4) ROOM: reward:risk to the next level in the trade direction ---
    room = 1.0
    if last and atrp:
        atr_abs = last * atrp / 100 or 1e-9
        if bias < 0 and sup:
            room = _clamp((last - sup) / (1.5 * atr_abs), 0.2, 1.0)   # room down to support
        elif bias > 0 and res:
            room = _clamp((res - last) / (1.5 * atr_abs), 0.2, 1.0)   # room up to resistance

    score = bias * freshness * room * (1.0 - 0.7 * against)
    if div == "bearish" and score > 0:
        score *= 0.5
    elif div == "bullish" and score < 0:
        score *= 0.5
    score = _clamp(score, -0.9, 0.9)                            # never a fake 100%
    direction = "long" if score > 0.1 else "short" if score < -0.1 else "flat"
    return {
        "score": round(score, 3),
        "direction": direction,
        "parts": {
            "bias": round(bias, 2), "adx_strength": round(adx_strength, 2),
            "exhaustion_penalty": round(against, 2), "freshness": round(freshness, 2),
            "room": round(room, 2), "divergence": div,
        },
    }
