"""
agents/market_scan.py
=====================
LAYER 1 DATA TOOL (plain Python, NO Claude tokens).

Thin CLI wrapper over backend/scanner.py. It runs the multi-timeframe screener
over every pair in your universe across every configured timeframe and writes
the result to decisions/_scan_latest.json — the file the Research agent reads.

Usage:
    python agents/market_scan.py            # live Bybit mainnet data
    python agents/market_scan.py --demo     # synthetic offline data
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import scanner, db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="use synthetic offline data")
    args = ap.parse_args()

    db.init_db()
    result = scanner.scan(demo=args.demo)
    rows = result["rows"]
    tfs = result["timeframes"]

    print(f"\nMULTI-TIMEFRAME SCAN ({result['data_source']})  ->  decisions/_scan_latest.json")
    header = f"{'symbol':16}{'conf%':>7}{'dir':>7}{'aligned':>9}  " + "".join(f"{tf:>7}" for tf in tfs)
    print("-" * len(header))
    print(header)
    print("-" * len(header))
    for r in rows:
        c = r["composite"]
        cells = "".join(f"{r['per_tf'][tf]['score']:>7.2f}" for tf in tfs)
        print(f"{r['symbol']:16}{c['confidence_pct']:>7}{c['direction']:>7}"
              f"{str(c['aligned']):>9}  {cells}")
    print("-" * len(header))
    print("Per-timeframe cells are signal scores in [-1,+1] (+ = bullish). "
          "conf% is the blended composite.\nNext: run /analyze in Claude Code to debate the top candidates.")


if __name__ == "__main__":
    main()
