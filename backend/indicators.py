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


def rsi_divergence(closes, n=14, lookback=20):
    """Crude divergence flag: price makes a new extreme but RSI doesn't.
    Returns 'bullish', 'bearish', or None."""
    if len(closes) < lookback + n:
        return None
    recent = closes[-lookback:]
    r_now = rsi(closes, n)
    r_then = rsi(closes[:-lookback // 2], n)
    if r_now is None or r_then is None:
        return None
    price_low_now = recent[-1] <= min(recent)
    price_high_now = recent[-1] >= max(recent)
    if price_low_now and r_now > r_then:
        return "bullish"
    if price_high_now and r_now < r_then:
        return "bearish"
    return None


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


def signal(ind: dict) -> dict:
    """Turn indicators into a signal in [-1, +1] with a transparent breakdown.

    Components (weights sum to 1.0):
      trend .22 (gated by ADX strength), momentum/RSI .18, macd .15,
      price-vs-SMA20 .10, price-vs-VWAP .12, bollinger %B .13, stochastic .10.
    Then a divergence penalty dampens a signal fighting a momentum divergence.
    """
    last, s20 = ind.get("last"), ind.get("sma20")
    r, m = ind.get("rsi"), ind.get("macd")
    adx_v = ind.get("adx")
    bb = ind.get("bb_pctb")
    stoch = ind.get("stoch")
    vw_dist = ind.get("vwap_dist_pct")

    trend_s = {"up": 1.0, "down": -1.0}.get(ind.get("trend"), 0.0)
    # ADX gates trend: weak trend (chop) => trend contributes less.
    adx_gate = max(0.3, min(1.0, (adx_v or 20) / 25))
    trend_s *= adx_gate

    mom_s = max(-1.0, min(1.0, (r - 50) / 25)) if r is not None else 0.0
    macd_s = (1.0 if m and m > 0 else -1.0 if m and m < 0 else 0.0)
    px_s = (1.0 if last and s20 and last > s20 else -1.0 if last and s20 else 0.0)
    vwap_s = max(-1.0, min(1.0, (vw_dist or 0) / 1.0))            # +/-1% from VWAP -> +/-1
    bb_s = max(-1.0, min(1.0, ((bb if bb is not None else 0.5) - 0.5) * 2))
    stoch_s = max(-1.0, min(1.0, ((stoch if stoch is not None else 50) - 50) / 30))

    score = (0.22 * trend_s + 0.18 * mom_s + 0.15 * macd_s + 0.10 * px_s
             + 0.12 * vwap_s + 0.13 * bb_s + 0.10 * stoch_s)

    # Divergence dampens a signal moving against it.
    div = ind.get("divergence")
    if div == "bearish" and score > 0:
        score *= 0.6
    elif div == "bullish" and score < 0:
        score *= 0.6

    score = max(-1.0, min(1.0, score))
    direction = "long" if score > 0.1 else "short" if score < -0.1 else "flat"
    return {
        "score": round(score, 3),
        "direction": direction,
        "parts": {
            "trend": round(trend_s, 2), "momentum": round(mom_s, 2), "macd": macd_s,
            "price_vs_sma20": px_s, "vwap": round(vwap_s, 2),
            "bollinger": round(bb_s, 2), "stochastic": round(stoch_s, 2),
            "adx_gate": round(adx_gate, 2), "divergence": div,
        },
    }
