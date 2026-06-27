# Layer 1 — The AI Brain (multi-agent debate)

This layer runs **interactively inside Claude Code, on your Max subscription**, using Claude
Code's built-in **subagent (Task) tool**. There is:

- **NO Anthropic API key** — reasoning is covered by your subscription.
- **NO background / headless loop** — it only runs when *you* type `/analyze`.

> ⚠️ If any future step asks you to put this on a timer, run it headless, or add an
> `ANTHROPIC_API_KEY`, that would switch you to paid API billing. Don't — that breaks the whole
> point of this design.

## Pieces

| File | What it is | Tokens? |
|---|---|---|
| `market_scan.py` | Plain-Python tool: pulls Bybit OHLCV, computes indicators, writes `decisions/_scan_latest.json` | No |
| `write_decision.py` | Plain-Python tool: validates + writes the final decision JSON + transcript, indexes it in SQLite | No |
| `claude_code/agents/*.md` | The five subagent definitions (Research, Bull, Bear, Risk, Portfolio) | Yes (subscription) |
| `claude_code/commands/analyze.md` | The `/analyze` orchestrator that runs the debate | Yes (subscription) |
| `claude_code/install_agents.sh` | Copies the agents + command into `.claude/` so Claude Code sees them | No |

## One-time setup
```bash
bash agents/claude_code/install_agents.sh   # copies into .claude/agents and .claude/commands
```
(We stage them under `agents/claude_code/` because this tool can't write into `.claude/`
directly; the script does the copy on your machine.)

## Running a debate
1. Open **Claude Code** in the project root: `cd FinalBot && claude`
2. Type: **`/analyze`**
3. Claude Code will, in one interactive run:
   - run `market_scan.py` (live Bybit data),
   - launch the Research → Bull → Bear → Risk → Portfolio subagents in turn,
   - assemble the final decision + full transcript,
   - pipe it through `write_decision.py`.
4. You'll get `decisions/<timestamp>_decision.json` + `_transcript.md`. The dashboard
   auto-detects it.

## The agents
- **Research** — neutral; scans every pair, ranks opportunities from the full data set
  (technicals + market structure + BTC correlation).
- **Macro / Positioning** — funding, open interest, long/short ratio, order-book imbalance +
  market regime (web search). SUPPORTIVE / MIXED / HOSTILE environment call.
- **Sentiment / News** — web-searches recent news, catalysts, unlocks, sentiment per candidate.
- **Bull** — strongest honest case to enter (with entry/stop/target).
- **Bear** — stress-tests it; argues stay-out or short.
- **Quant (devil's advocate)** — the math check: reward:risk, stop vs ATR/structure, entry
  quality, edge vs noise. PASS/FAIL; the desk can't enter on a FAIL.
- **Risk Manager** — checks size/drawdown/exposure vs your config; **can VETO**, sets max size.
- **Portfolio Manager** — final call as strict JSON; honors the veto and the quant FAIL.

Plus a standalone **Post-Trade Review** agent (run it any time) that studies closed trades and
proposes concrete config/strategy tweaks — it does not place trades.

### Data the agents now see
The scan (`scanner.py`) computes, per pair × timeframe: trend (MA, ADX), momentum (RSI, MACD,
stochastic), volatility (ATR, Bollinger), location (VWAP, support/resistance, divergence), the
multi-timeframe blend, **market structure** (funding/OI/long-short/order-book — free via Bybit),
and **BTC correlation + relative strength**.

## Decision JSON shape
```json
{
  "action": "buy|sell|short|close|hold",
  "symbol": "SOL/USDT:USDT",
  "size": 3.0,
  "entry": 147.0, "stop_loss": 144.2, "take_profit": 152.9,
  "confidence": 0.55,
  "rationale": "…",
  "transcript": { "research": "…", "bull": "…", "bear": "…", "risk": "…", "portfolio": "…" }
}
```

## Example run (included)
`decisions/20260627-124112_decision.json` + `_transcript.md` are a real run of this pipeline
over a 5-pair scan (offline demo data). The desk debated a risk-off tape and landed on a small
**SOL long** (3% size, 0.55 confidence) after the Risk Manager trimmed size from the 5% cap —
demonstrating the veto/sizing flow end to end.
