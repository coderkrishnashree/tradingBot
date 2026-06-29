"""
exchange.py
===========
The ONE place that talks to Bybit, via ccxt.

Key design point: a SINGLE codebase serves both environments. We never import
two different exchange classes — we build the same `ccxt.bybit` client and just
flip `set_sandbox_mode(True/False)` and swap which key pair we hand it. The
active environment is decided by the shared ModeManager, so the rest of the app
never has to think about paper-vs-live plumbing.
"""

from __future__ import annotations
import ccxt

from . import config
from .config import mode_manager, PAPER, LIVE


# We cache one client per mode so we don't re-handshake on every request.
_clients: dict[str, ccxt.bybit] = {}


def _build_client(mode: str) -> ccxt.bybit:
    # Decide which credentials + environment to use.
    #   LIVE                       -> mainnet keys, real funds
    #   PAPER + backend 'demo'     -> Bybit Demo Trading (instant virtual funds)
    #   PAPER + backend 'testnet'  -> Bybit Testnet (faucet funds)
    use_demo = mode == PAPER and config.paper_backend() == "demo"
    if mode == LIVE:
        key, secret = config.mainnet_keys()
    elif use_demo:
        key, secret = config.demo_keys()
    else:
        key, secret = config.testnet_keys()

    client = ccxt.bybit({
        "apiKey": key,
        "secret": secret,
        "enableRateLimit": True,
        "options": {
            # Trade USDT perpetuals ("linear") by default. This matches the
            # BTC/USDT:USDT style unified symbols the agents reason about.
            "defaultType": "swap",
        },
    })

    if use_demo:
        # Demo Trading runs on api-demo.bybit.com (mainnet-style, virtual funds).
        if not hasattr(client, "enable_demo_trading"):
            raise RuntimeError("Your ccxt is too old for Demo Trading. Run: pip install -U ccxt")
        client.enable_demo_trading(True)
    else:
        # THE paper/live switch. True => testnet endpoints; False => mainnet.
        client.set_sandbox_mode(mode == PAPER)
    return client


def get_client() -> ccxt.bybit:
    """Return the ccxt client for whatever mode is active RIGHT NOW."""
    mode = mode_manager.mode
    if mode not in _clients:
        _clients[mode] = _build_client(mode)
    return _clients[mode]


def reset_clients():
    """Drop cached clients — call after keys change so they're rebuilt."""
    _clients.clear()


# --- Read helpers (safe in both modes) -------------------------------------

def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 200) -> list[list]:
    """OHLCV candles: [[ts, open, high, low, close, volume], ...]."""
    return get_client().fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)


def fetch_balance() -> dict:
    """Unified balance dict. Empty/zero if keys are missing — never raises to caller."""
    try:
        return get_client().fetch_balance()
    except Exception as e:  # keys not set yet, network, etc.
        return {"error": str(e), "total": {}, "free": {}, "used": {}}


def fetch_positions() -> list[dict]:
    """Open positions (linear swaps). Returns [] if unavailable."""
    try:
        positions = get_client().fetch_positions()
        # ccxt returns many zero-size rows; keep only actually-open ones.
        return [p for p in positions if p.get("contracts")]
    except Exception:
        return []


def fetch_ticker(symbol: str) -> dict:
    try:
        return get_client().fetch_ticker(symbol)
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def fetch_closed_trades(symbols, per_sym: int = 100) -> list[dict]:
    """Bybit closed-PnL (realized) records across the given symbols, newest first."""
    out = []
    try:
        client = get_client()
        for sym in (symbols or [])[:8]:
            try:
                resp = client.private_get_v5_position_closed_pnl(
                    {"category": "linear", "symbol": client.market_id(sym), "limit": per_sym})
                for it in resp.get("result", {}).get("list", []):
                    out.append({
                        "symbol": sym,
                        "side": it.get("side"),
                        "qty": float(it.get("qty") or 0),
                        "entry": float(it.get("avgEntryPrice") or 0),
                        "exit": float(it.get("avgExitPrice") or 0),
                        "realized": float(it.get("closedPnl") or 0),
                        "closed_at": int(it.get("updatedTime") or it.get("createdTime") or 0),
                    })
            except Exception:
                pass
    except Exception:
        pass
    out.sort(key=lambda x: x.get("closed_at") or 0, reverse=True)
    return out


def connectivity_check() -> dict:
    """Cheap public call to confirm we can reach the active environment."""
    try:
        t = get_client().fetch_ticker("BTC/USDT:USDT")
        return {"reachable": True, "mode": mode_manager.mode, "btc_last": t.get("last")}
    except Exception as e:
        return {"reachable": False, "mode": mode_manager.mode, "error": str(e)}
