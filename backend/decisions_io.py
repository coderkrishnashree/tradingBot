"""
decisions_io.py
===============
The bridge between Layer 1 (the AI brain, writes files) and Layer 2 / the API
(reads files). Layer 1 NEVER imports this with a running loop — it just drops
JSON files into /decisions/. Everything here is plain file IO.

File convention (written by the Stage 2 agents):
    decisions/YYYYMMDD-HHMMSS_decision.json

Each decision JSON looks like:
    {
      "timestamp": "...ISO...",
      "action": "buy" | "sell" | "short" | "close" | "hold",
      "symbol": "BTC/USDT:USDT",
      "size": 5.0,                # percent of equity
      "entry": 65000,
      "stop_loss": 63700,
      "take_profit": 67600,
      "confidence": 0.72,         # 0..1
      "rationale": "one paragraph",
      "transcript": {             # full debate, per agent
        "research": "...", "bull": "...", "bear": "...",
        "risk": "...", "portfolio": "..."
      }
    }
"""

from __future__ import annotations
import json
from pathlib import Path

from . import config, db


def _decision_files() -> list[Path]:
    # Sorted ascending by filename; timestamp prefix makes this chronological.
    return sorted(config.DECISIONS_DIR.glob("*_decision.json"))


def read_decision(filename: str) -> dict | None:
    path = config.DECISIONS_DIR / filename
    if not path.exists():
        return None
    return json.loads(path.read_text())


def latest_decision() -> dict | None:
    files = _decision_files()
    if not files:
        return None
    data = json.loads(files[-1].read_text())
    data["_filename"] = files[-1].name
    return data


def latest_transcript() -> dict | None:
    d = latest_decision()
    if not d:
        return None
    return {
        "filename": d.get("_filename"),
        "timestamp": d.get("timestamp"),
        "symbol": d.get("symbol"),
        "transcript": d.get("transcript", {}),
        "final_decision": {k: d.get(k) for k in
                           ("action", "symbol", "size", "entry", "stop_loss",
                            "take_profit", "confidence", "rationale")},
    }


_sync_state = {"ts": 0.0}
_SYNC_MIN_INTERVAL_SEC = 30


def sync_index(force: bool = False) -> int:
    """Make sure every decision file on disk is indexed in SQLite.

    2026-08 perf fix: the old version read AND json-parsed EVERY file on disk
    on EVERY call — with 5,000+ decision files, polled every 8s by the UI,
    that alone made the Debates tab crawl. Now we (a) throttle to once per
    30s, and (b) only parse files whose names aren't already in the index.
    Returns how many new files were indexed.
    """
    import time
    now = time.time()
    if not force and now - _sync_state["ts"] < _SYNC_MIN_INTERVAL_SEC:
        return 0
    _sync_state["ts"] = now

    known = db.known_decision_filenames()
    new = 0
    for f in _decision_files():
        if f.name in known:
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        rid = db.index_decision(
            filename=f.name,
            action=d.get("action"),
            symbol=d.get("symbol"),
            confidence=d.get("confidence"),
        )
        if rid:
            new += 1
    return new
