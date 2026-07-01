---
description: LITE debate — shared web research once, then a fast decision for EVERY pair.
---

Run a FAST debate that produces a decision for **every pair** in the universe. It still uses web
research (macro + sentiment), but only ONCE per cycle (shared), so it stays quick even across many
pairs. Runs on the Claude subscription via the Task tool — no API key, no loop.

**Which pairs (IMPORTANT — do exactly this):** the backend writes the pairs to debate into
`decisions/_debate_targets.json`. Debate ONLY those pairs. This is the normal case — the screener
already filtered to the ones above the confidence threshold. Do NOT debate any other pair; doing so
wastes tokens.

Get the target list with:
```
python -c "import json;d=json.load(open('decisions/_debate_targets.json'));print(' '.join(d.get('symbols') or []))"
```
- If it prints one or more symbols → those are your ONLY targets.
- If it prints nothing (empty) → this is a manual full sweep; use the whole universe from config:
  `python -c "import sys;sys.path.insert(0,'.');from backend import db;print(db.get_trading_config()['symbol_universe'])"`

Steps:

1. **Refresh data.** Run `python agents/market_scan.py` (this scans all pairs for data — that's
   free, no tokens). Then determine your TARGET pairs using the command above.

   If there are NO target pairs (empty list and no manual sweep), STOP — nothing to debate.

2. **Shared web research (ONCE).** Launch the `macro-agent` and `sentiment-agent` subagents for
   the overall market + ONLY the TARGET pairs (these use web search). Collect their notes. Do this
   a single time — it is the shared context for the targets this cycle.

3. **Per-pair decision.** For EACH TARGET pair (NOT the whole universe), launch the `desk-analyst`
   subagent, passing it the symbol PLUS the shared macro + sentiment notes from step 2. It returns
   STRICT decision JSON for that pair (it does not browse the web — it uses the shared context).

4. **Persist each.** For every TARGET pair, assemble the decision object: the desk-analyst's JSON PLUS a
   `transcript` with the shared context and the analyst's reasoning:
   ```json
   {
     "...desk-analyst JSON fields...",
     "transcript": {
       "macro": "<shared macro notes>",
       "sentiment": "<shared sentiment notes>",
       "analyst": "<this pair's desk-analyst reasoning>",
       "portfolio": "<one-line: the call for this pair>"
     }
   }
   ```
   Write it with: `cat /tmp/decision_<SYM>.json | python agents/write_decision.py`
   (one write per pair — each becomes its own timestamped decision file).

5. **Confirm.** Print a one-line summary per pair (action · confidence) and the files written. The
   dashboard's Scanner tab will show each pair's AI confidence; the Debates tab shows the details.

Do NOT place orders here — Layer 2 executes approved/qualifying decisions separately.
