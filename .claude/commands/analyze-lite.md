---
model: opus
description: LITE debate — shared web research once, then a fast decision for the qualifying pairs.
---

Run a FAST debate that produces a decision for the **qualifying pairs only**. It still uses web
research (macro + sentiment), but only ONCE per cycle (shared), so it stays quick. Runs on the
Claude subscription via the Task tool — no API key, no loop.

**Which pairs (CRITICAL — this controls token cost, do EXACTLY this):** do NOT read the config
universe, and do NOT decide the list yourself. The list of pairs to debate is produced by a script:

```
python3 agents/pick_candidates.py
```

- Each line it prints is one TARGET pair. Debate ONLY those. Ignore every other pair.
- If it prints NOTHING, there is nothing to debate this cycle → **STOP immediately, write no
  decisions.** Do NOT fall back to the full universe. (The script already filters to pairs above the
  confidence threshold; an empty result means nothing qualified.)
- If `python3` is missing, try `.venv/bin/python agents/pick_candidates.py` or `python`.

Never debate more pairs than this script prints. Analyzing the whole universe is the exact bug this
prevents — it wastes a large amount of tokens.

Steps:

1. **Refresh data.** Run `python3 agents/market_scan.py` (this scans all pairs for data — that's
   free, no tokens). Then get your TARGET pairs with `python3 agents/pick_candidates.py`.

   If it returns NO pairs, STOP — nothing to debate this cycle.

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
