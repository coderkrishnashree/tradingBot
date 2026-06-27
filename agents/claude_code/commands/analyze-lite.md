---
description: LITE debate — shared web research once, then a fast decision for EVERY pair.
---

Run a FAST debate that produces a decision for **every pair** in the universe. It still uses web
research (macro + sentiment), but only ONCE per cycle (shared), so it stays quick even across many
pairs. Runs on the Claude subscription via the Task tool — no API key, no loop.

Steps:

1. **Refresh data.** Run `python agents/market_scan.py`. Read the pair list from the config:
   `python -c "import sys;sys.path.insert(0,'.');from backend import db;print(db.get_trading_config()['symbol_universe'])"`

2. **Shared web research (ONCE).** Launch the `macro-agent` and `sentiment-agent` subagents for
   the overall market + this universe (these use web search). Collect their notes. Do this a
   single time — it is the shared context for all pairs this cycle.

3. **Per-pair decision.** For EACH symbol in the universe, launch the `desk-analyst` subagent,
   passing it the symbol PLUS the shared macro + sentiment notes from step 2. It returns STRICT
   decision JSON for that pair (it does not browse the web — it uses the shared context).

4. **Persist each.** For every pair, assemble the decision object: the desk-analyst's JSON PLUS a
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
