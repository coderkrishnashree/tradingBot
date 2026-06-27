"""
agents/write_decision.py
========================
LAYER 1 OUTPUT WRITER (plain Python, NO Claude tokens).

The orchestrator (the /analyze flow inside Claude Code) collects the debate and
the Portfolio Manager's final decision, then pipes the complete decision JSON
into this script. It:

  1. Validates the schema (required fields, ranges).
  2. Writes the timestamped decision file:  decisions/<YYYYMMDD-HHMMSS>_decision.json
  3. Writes a human-readable transcript:     decisions/<YYYYMMDD-HHMMSS>_transcript.md
  4. Indexes it in SQLite so the dashboard lists it (best-effort).

Usage (from a Claude Code session):
    cat decision.json | python agents/write_decision.py
    #   or
    python agents/write_decision.py decision.json
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "decisions"
DECISIONS.mkdir(exist_ok=True)

REQUIRED = ["action", "symbol", "size", "entry", "stop_loss",
            "take_profit", "confidence", "rationale"]
VALID_ACTIONS = {"buy", "sell", "short", "close", "hold"}


def validate(d: dict) -> list[str]:
    errs = []
    for f in REQUIRED:
        if f not in d:
            errs.append(f"missing required field: {f}")
    if d.get("action") not in VALID_ACTIONS:
        errs.append(f"action must be one of {sorted(VALID_ACTIONS)}")
    conf = d.get("confidence")
    if conf is not None and not (0 <= conf <= 1):
        errs.append("confidence must be between 0 and 1")
    # For a 'hold', numeric levels may be null — that's fine.
    if d.get("action") not in ("hold",):
        for f in ("size", "entry", "stop_loss", "take_profit"):
            if d.get(f) in (None, "") and f != "size":
                errs.append(f"{f} required for action={d.get('action')}")
    return errs


def transcript_md(d: dict) -> str:
    t = d.get("transcript", {})
    lines = [f"# Debate transcript — {d.get('timestamp')}",
             f"**Final:** {d.get('action','').upper()} {d.get('symbol','')} "
             f"(size {d.get('size')}%, confidence {d.get('confidence')})\n"]
    for role in ("research", "macro", "sentiment", "bull", "bear", "quant", "risk", "portfolio"):
        if role in t:
            lines.append(f"## {role.capitalize()} Agent\n\n{t[role]}\n")
    lines.append(f"## Final decision JSON\n\n```json\n"
                 f"{json.dumps({k: d.get(k) for k in REQUIRED}, indent=2)}\n```")
    return "\n".join(lines)


def main():
    raw = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else sys.stdin.read()
    d = json.loads(raw)

    errs = validate(d)
    if errs:
        print("DECISION REJECTED — validation errors:")
        for e in errs:
            print("  -", e)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    d.setdefault("timestamp", now.isoformat())
    stamp = now.strftime("%Y%m%d-%H%M%S")

    decision_path = DECISIONS / f"{stamp}_decision.json"
    transcript_path = DECISIONS / f"{stamp}_transcript.md"
    decision_path.write_text(json.dumps(d, indent=2))
    transcript_path.write_text(transcript_md(d))

    # Index in SQLite (best-effort; fine if DB/backend unavailable).
    try:
        sys.path.insert(0, str(ROOT))
        from backend import db
        db.init_db()
        db.index_decision(decision_path.name, d.get("action"),
                          d.get("symbol"), d.get("confidence"))
    except Exception as e:
        print(f"[note] DB index skipped: {str(e)[:60]}")

    print("DECISION WRITTEN:")
    print("  ", decision_path.relative_to(ROOT))
    print("  ", transcript_path.relative_to(ROOT))
    print(f"  action={d['action']} symbol={d['symbol']} "
          f"confidence={d['confidence']} size={d.get('size')}%")


if __name__ == "__main__":
    main()
