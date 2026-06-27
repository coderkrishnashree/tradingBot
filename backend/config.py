"""
config.py
=========
Central configuration + the PAPER/LIVE mode manager.

Two ideas live here:

1. Static settings read from the environment (.env) at import time:
   - The two SEPARATE key pairs (testnet vs mainnet).
   - Paths.

2. ModeManager — the single source of truth for "are we paper or live RIGHT NOW".
   * The app ALWAYS boots in PAPER mode. This is deliberate: even if you were
     live yesterday, a restart puts you back on the safe testnet.
   * Going live is a guarded, multi-condition action (see go_live()).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (one level up from this file).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- Mode constants ---------------------------------------------------------
PAPER = "paper"   # Bybit TESTNET — fake funds, real order system
LIVE = "live"     # Bybit MAINNET — REAL funds

# --- Paths ------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "trading.db"))
DECISIONS_DIR = PROJECT_ROOT / "decisions"   # Layer 1 writes here, Layer 2 reads
DECISIONS_DIR.mkdir(exist_ok=True)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def testnet_keys() -> tuple[str, str]:
    return os.getenv("BYBIT_TESTNET_KEY", ""), os.getenv("BYBIT_TESTNET_SECRET", "")


def mainnet_keys() -> tuple[str, str]:
    return os.getenv("BYBIT_MAINNET_KEY", ""), os.getenv("BYBIT_MAINNET_SECRET", "")


def has_testnet_keys() -> bool:
    k, s = testnet_keys()
    return bool(k and s)


def has_mainnet_keys() -> bool:
    k, s = mainnet_keys()
    return bool(k and s)


def demo_keys() -> tuple[str, str]:
    return os.getenv("BYBIT_DEMO_KEY", ""), os.getenv("BYBIT_DEMO_SECRET", "")


def has_demo_keys() -> bool:
    k, s = demo_keys()
    return bool(k and s)


def paper_backend() -> str:
    """Which environment 'paper' mode uses: 'testnet' (default) or 'demo'.
    Bybit Demo Trading gives instant virtual funds and is more reliable than the
    testnet faucet. Set BYBIT_PAPER_BACKEND=demo in .env to use it."""
    return os.getenv("BYBIT_PAPER_BACKEND", "testnet").strip().lower()


# Default trading parameters. These are seeded into the DB on first run and can
# then be edited from the UI config panel (Stage 3). The agents (Stage 2) scan
# the whole `symbol_universe` and debate which pair(s) to trade.
DEFAULT_TRADING_CONFIG = {
    "symbol_universe": [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "XRP/USDT:USDT",
        "BNB/USDT:USDT",
    ],
    "timeframe": "1h",
    "leverage": 3,
    "position_size_pct": 5.0,    # % of equity per position
    "stop_loss_pct": 2.0,
    "take_profit_pct": 4.0,
    "max_drawdown_pct": 20.0,    # auto-halt threshold for Layer 2
    # --- Automation (always-on mechanical screener; no Claude tokens) -------
    "scan_timeframes": ["15m", "1h", "4h", "1d"],  # "all timeframes" the screener checks
    "scan_interval_min": 30,     # how often the background scan runs
    "scan_enabled": True,        # run scans on a schedule (harmless; no tokens)
    "auto_trade": False,         # OFF by default: only auto-execute when you enable it
    "auto_trade_confidence": 65, # trade a pair only if composite confidence >= this %
    "daily_loss_limit_pct": 0,   # 0 = off. e.g. 5 => halt trading if down 5% on the day
    "min_minutes_between_trades": 0,  # 0 = off. per-symbol cooldown to curb fee churn
    # When ON, the backend ITSELF runs the AI debate (`claude -p /analyze`) on the
    # scan schedule — i.e. the "cron from the dashboard". Headless, uses your Claude
    # Code subscription login (no API key). OFF by default. See scheduler.run_ai_analyze.
    "auto_analyze": False,
    # AI-GATED: when ON, the mechanical screener only PRE-FILTERS candidates; the
    # AI debate runs on them and the agents' decision (with the AI's own
    # confidence) is what actually trades. No mechanical-only auto-trades.
    # Requires Claude Code running (non-root). OFF by default.
    "ai_gated": False,
}


class ModeManager:
    """Single source of truth for the active environment.

    The constraint from the spec: a single click must NEVER move us from paper
    to live. go_live() therefore requires THREE independent conditions, and any
    failure leaves us safely in paper mode.
    """

    def __init__(self):
        self._mode = PAPER          # always boot in paper
        self._kill_switch = False   # True => Layer 2 halts all trading
        # When the kill switch is reset, the drawdown auto-stop should measure
        # only from here forward (a re-arm), so stale history can't re-trip it.
        self._dd_reference_ts = None

    @property
    def dd_reference_ts(self):
        return self._dd_reference_ts

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_live(self) -> bool:
        return self._mode == LIVE

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch

    def status(self) -> dict:
        """What the UI mode-banner endpoint returns."""
        return {
            "mode": self._mode,
            "is_live": self.is_live,
            "kill_switch_active": self._kill_switch,
            "paper_backend": paper_backend(),          # 'testnet' or 'demo'
            "testnet_keys_present": has_testnet_keys(),
            "demo_keys_present": has_demo_keys(),
            "mainnet_keys_present": has_mainnet_keys(),
        }

    def go_live(self, confirmation_text: str) -> dict:
        """Switch to LIVE. Returns {ok, error}. Stays in paper on any failure.

        Three guards (all must pass):
          (a) typed confirmation must be exactly "GO LIVE"
          (b) mainnet keys must be present in .env
          (c) kill switch must not be engaged
        """
        if confirmation_text != "GO LIVE":
            return {"ok": False, "error": 'Confirmation must be exactly "GO LIVE".'}
        if not has_mainnet_keys():
            return {"ok": False, "error": "BYBIT_MAINNET_KEY/SECRET are not set in .env."}
        if self._kill_switch:
            return {"ok": False, "error": "Kill switch is engaged. Reset it first."}
        self._mode = LIVE
        return {"ok": True, "error": None}

    def go_paper(self) -> dict:
        """Return to the safe testnet environment. Always allowed."""
        self._mode = PAPER
        return {"ok": True, "error": None}

    def engage_kill_switch(self):
        self._kill_switch = True

    def reset_kill_switch(self):
        self._kill_switch = False
        # Re-arm the drawdown auto-stop from NOW, so historical drawdown (e.g.
        # from setup/basis changes) can't immediately re-engage the kill switch.
        from datetime import datetime, timezone
        self._dd_reference_ts = datetime.now(timezone.utc).isoformat()


# A single shared instance imported across the backend.
mode_manager = ModeManager()
