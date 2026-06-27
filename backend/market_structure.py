"""
market_structure.py
===================
Derivatives "positioning" data (plain Python, NO Claude tokens) — the closest
thing to fundamentals for a perpetual future. All from the public Bybit API via
ccxt (no API key needed). Each piece degrades gracefully to None on error so a
flaky call never breaks a scan.

For one symbol we gather:
  funding_rate        : current funding (longs pay shorts if positive). Extreme
                        positive = crowded longs (contrarian caution for longs).
  open_interest       : total open contracts (rising OI + rising price = real trend).
  long_short_ratio    : retail account long/short ratio (high = crowded longs).
  orderbook_imbalance : (bid_vol - ask_vol)/(bid_vol + ask_vol) on the top of book.

`structure_bias` blends these into [-1, +1]: positive = supportive of longs,
negative = supportive of shorts, with crowding treated as contrarian.
"""

from __future__ import annotations

_pub = None


def _client():
    global _pub
    if _pub is None:
        import ccxt
        _pub = ccxt.bybit({"enableRateLimit": True,
                           "options": {"defaultType": "swap"},
                           "timeout": 8000})
    return _pub


def _funding(client, symbol):
    try:
        fr = client.fetch_funding_rate(symbol)
        return {"rate": fr.get("fundingRate"), "next": fr.get("fundingTimestamp")}
    except Exception:
        return {"rate": None, "next": None}


def _open_interest(client, symbol):
    try:
        oi = client.fetch_open_interest(symbol)
        return oi.get("openInterestValue") or oi.get("openInterestAmount")
    except Exception:
        return None


def _long_short(client, symbol):
    """Bybit account long/short ratio via the implicit V5 endpoint."""
    try:
        fn = getattr(client, "public_get_v5_market_account_ratio", None)
        if not fn:
            return None
        resp = fn({"category": "linear", "symbol": client.market_id(symbol),
                   "period": "1h", "limit": 1})
        row = resp.get("result", {}).get("list", [{}])[0]
        buy = float(row.get("buyRatio") or 0)
        sell = float(row.get("sellRatio") or 0)
        return round(buy / sell, 3) if sell else None
    except Exception:
        return None


def _orderbook_imbalance(client, symbol, depth=25):
    try:
        ob = client.fetch_order_book(symbol, limit=depth)
        bid_vol = sum(b[1] for b in ob.get("bids", [])[:depth])
        ask_vol = sum(a[1] for a in ob.get("asks", [])[:depth])
        tot = bid_vol + ask_vol
        return round((bid_vol - ask_vol) / tot, 3) if tot else None
    except Exception:
        return None


def structure(symbol: str) -> dict:
    client = _client()
    f = _funding(client, symbol)
    oi = _open_interest(client, symbol)
    lsr = _long_short(client, symbol)
    imb = _orderbook_imbalance(client, symbol)

    # Blend into a contrarian-aware bias in [-1, +1].
    bias = 0.0
    parts = {}
    if f["rate"] is not None:
        # High positive funding = crowded longs => slight short lean (contrarian).
        fr = f["rate"]
        parts["funding"] = round(max(-1.0, min(1.0, -fr * 1000)), 2)  # 0.1% funding -> -1
        bias += 0.4 * parts["funding"]
    if lsr is not None:
        # >1 crowded long => contrarian short lean; <1 crowded short => long lean.
        parts["long_short"] = round(max(-1.0, min(1.0, (1.0 - lsr))), 2)
        bias += 0.3 * parts["long_short"]
    if imb is not None:
        parts["orderbook"] = imb  # bids heavier => long lean
        bias += 0.3 * imb

    return {
        "funding_rate": f["rate"],
        "funding_next": f["next"],
        "open_interest": oi,
        "long_short_ratio": lsr,
        "orderbook_imbalance": imb,
        "structure_bias": round(max(-1.0, min(1.0, bias)), 3),
        "bias_parts": parts,
    }
