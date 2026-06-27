---
description: Run the multi-agent trading debate across all configured pairs and write a decision.
---

Run a full multi-agent trading debate and write the result to `decisions/`. This runs on the
Claude subscription via the Task tool — there is NO API key and NO background loop.

Follow these steps in order:

1. **Refresh market data.** Run:
   `python agents/market_scan.py`
   (add `--demo` only if you have no network). This writes `decisions/_scan_latest.json`.

2. **Research.** Launch the `research-agent` subagent (Task tool). Let it read the scan
   (technicals + market-structure + correlation) and return a neutral briefing + a ranked
   shortlist of the best 2–3 opportunities and direction.

3. **Context (macro + sentiment).** Launch the `macro-agent` and the `sentiment-agent` subagents,
   passing each the Research shortlist. Macro judges positioning + regime (SUPPORTIVE / MIXED /
   HOSTILE); Sentiment web-searches news/catalysts. Collect both.

4. **Bull.** Launch the `bull-agent` subagent with the Research briefing (+ macro/sentiment
   context). Collect its strongest case to enter (with proposed entry/stop/target).

5. **Bear.** Launch the `bear-agent` subagent with the Research briefing + the Bull case.
   Collect its rebuttal / short case.

6. **Quant.** Launch the `quant-agent` subagent with the proposed trade. It returns PASS/FAIL on
   the math (reward:risk, stop vs ATR, entry quality, edge vs noise).

7. **Risk.** Launch the `risk-manager` subagent with the proposed trade + all context. Collect
   APPROVE / APPROVE WITH CHANGES / VETO and the max allowed size.

8. **Decide.** Launch the `portfolio-manager` subagent. Pass it ALL outputs (research, macro,
   sentiment, bull, bear, quant, risk). It returns STRICT decision JSON. Honor any veto, and do
   NOT enter if the quant agent FAILED the trade.

9. **Persist.** Assemble the final object: the Portfolio Manager's JSON PLUS a `transcript`
   object containing each agent's full text:
   ```json
   {
     "...portfolio JSON fields...",
     "transcript": {
       "research": "<research output>",
       "macro": "<macro agent output>",
       "sentiment": "<sentiment agent output>",
       "bull": "<bull output>",
       "bear": "<bear output>",
       "quant": "<quant agent output>",
       "risk": "<risk manager output>",
       "portfolio": "<one-line summary of the PM's reasoning>"
     }
   }
   ```
   Write it to a temp file and run:
   `cat /tmp/decision.json | python agents/write_decision.py`

10. **Confirm.** Print the path of the written `*_decision.json` and `*_transcript.md`, and the
    final action/symbol/confidence. The dashboard will pick it up automatically.

Do NOT place any orders here. This command only produces a decision file. Execution is a
separate, human-approved step in the dashboard (Layer 2).
