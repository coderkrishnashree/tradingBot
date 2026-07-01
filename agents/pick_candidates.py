#!/usr/bin/env python3
"""
pick_candidates.py
==================
Print (one per line) the ONLY pairs the AI debate should analyze this cycle.

This exists to stop token burn: the debate must never analyze the whole universe
by accident. Resolution order:

  1. decisions/_debate_targets.json with {"full": true}  -> the full universe
     (an EXPLICIT manual "Run analysis now" sweep — the only way to get all pairs).
  2. decisions/_debate_targets.json with non-empty "symbols" -> exactly those
     (the AI-gated path: the backend already picked the qualifiers).
  3. Otherwise compute candidates ourselves from the latest scan:
     symbols whose composite confidence >= auto_trade_confidence AND direction != flat.

If nothing qualifies, print NOTHING (the command must then debate nothing — NOT
fall back to the universe). This is self-contained so it works even if the
scheduler didn't write the targets file.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TARGETS = os.path.join(ROOT, "decisions", "_debate_targets.json")
SCAN = os.path.join(ROOT, "decisions", "_scan_latest.json")


def _cfg():
    try:
        from backend import db
        return db.get_trading_config()
    except Exception:
        return {}


def main():
    cfg = _cfg()
    threshold = float(cfg.get("auto_trade_confidence", 65) or 65)
    universe = cfg.get("symbol_universe") or []

    # 1 & 2: explicit targets file wins.
    if os.path.exists(TARGETS):
        try:
            t = json.load(open(TARGETS))
            if t.get("full"):
                print("\n".join(universe))
                return
            syms = t.get("symbols") or []
            if syms:
                print("\n".join(syms))
                return
        except Exception:
            pass

    # 3: compute from the latest scan + threshold (self-contained fallback).
    try:
        scan = json.load(open(SCAN))
    except Exception:
        return  # no scan -> nothing to debate
    out = []
    for r in scan.get("rows", []):
        c = r.get("composite", {})
        if float(c.get("confidence_pct", 0)) >= threshold and c.get("direction") not in (None, "flat"):
            out.append(r["symbol"])
    print("\n".join(out))


if __name__ == "__main__":
    main()
