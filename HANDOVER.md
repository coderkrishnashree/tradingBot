# FinalBot — Trading System Handover

_Last updated: 2026-07-01_

A multi-agent, multi-asset trading bot for **Bybit** (via ccxt) with a modern web dashboard,
deployed on a DigitalOcean droplet. This document is the single reference for how the system is
built, how it runs on the server, what has been changed, and how to operate it.

---

## 1. Architecture at a glance

The system is deliberately split into two layers so the expensive "thinking" is separated from the
always-on "doing".

**Layer 1 — the AI brain (Claude Code, on your Max subscription).**
A multi-agent debate (research, macro, sentiment, bull, bear, quant, risk manager, portfolio
manager, plus a fast "desk-analyst" for lite mode). It reads the current market scan, debates, and
writes a **decision JSON + transcript** per pair into `decisions/`. It runs headlessly via
`claude -p` — using your subscription login, **never an API key**. This is the one place tokens are
spent.

**Layer 2 — the mechanical engine (plain Python, zero tokens).**
Always-on. It reads decisions, executes orders on Bybit, tracks the portfolio, computes stats, logs
everything to SQLite, and enforces the hard safety stops (kill switch + max-drawdown auto-stop +
daily-loss limit). This never calls Claude.

**Between them — the mechanical screener.**
`scanner.py` + `indicators.py` run a multi-timeframe scan of every pair and produce a *composite
confidence* + *direction*. In **AI-gated mode**, only pairs whose confidence clears your
`auto_trade_confidence` threshold are handed to the AI debate; the AI then makes the final call and
the engine executes it.

```
   market data ──> scanner (free) ──> candidates >= threshold
                                            │
                                            ▼
                                 AI debate (Layer 1, tokens)
                                            │
                                     decision JSON
                                            ▼
                                 engine (Layer 2, no tokens) ──> Bybit
```

---

## 2. Tech stack

- **Backend:** FastAPI (`backend/`), served same-origin with the built frontend via `StaticFiles`.
- **Frontend:** React + Vite + Tailwind (`frontend/`), modern dark "ink" theme, indigo accent.
- **Exchange:** ccxt Bybit, linear USDT perps.
- **Storage:** SQLite (stdlib `sqlite3`) — tables: `orders`, `equity_curve`, `settings`,
  `decisions_log`, `alerts`.
- **AI:** Claude Code subagents (`agents/claude_code/agents/*.md`) + slash commands
  (`/analyze`, `/analyze-lite`), run headlessly.
- **Deploy:** systemd service `finalbot` (non-root `finalbot` user) + nginx reverse proxy with
  self-signed HTTPS, Basic Auth, UFW firewall.

---

## 3. Trading environments (paper vs live)

Three Bybit environments are supported through one client factory (`backend/exchange.py`):

- **Demo Trading** (`api-demo.bybit.com`, `enable_demo_trading(True)`) — mainnet-style demo with
  instant virtual funds. This is the paper backend in use (`BYBIT_PAPER_BACKEND=demo`).
  **Important:** demo API keys must be created *inside* Demo Trading mode on bybit.com, and virtual
  funds must be transferred from the Funding wallet to the Unified wallet to show a balance.
- **Testnet** (`set_sandbox_mode(True)`) — alternative paper backend.
- **Mainnet** — real funds, live trading.

**Safety model:** two key pairs (paper + mainnet), a big always-visible mode banner
(green = PAPER, red = LIVE), and a gated live switch. Keys are never hardcoded — they live in `.env`.

**Mode persistence:** the active mode is saved and restored across restarts. If it was LIVE, it
reboots LIVE (only if mainnet keys are present); otherwise it boots paper.

---

## 4. Server / deployment setup

**Host:** DigitalOcean droplet.
**Repo on server:** `/opt/finalbot` (GitHub: `coderkrishnashree/tradingBot`).
**Runs as:** non-root user `finalbot` (Claude Code refuses `--dangerously-skip-permissions` as root,
so a non-root user is required for headless AI). `deploy/make-nonroot.sh` created the user and gave
it sudoers rights to restart the service.

**Service:** systemd unit `finalbot` (auto-restart, boots on server start).

**Web:** nginx reverse-proxy in front of the app, self-signed HTTPS (no domain), HTTP Basic Auth,
and UFW locked to an allowlisted IP (`ALLOW_IP`).

**Deploy scripts (`deploy/`):**
- `install.sh` / `server-setup.sh` — first-time provisioning.
- `update.sh` — pull deps + restart (the routine deploy step).
- `make-nonroot.sh` — one-time migration to the `finalbot` user.

**The routine deploy command (run as `finalbot`, never root):**
```bash
sudo -u finalbot -H bash -lc 'cd /opt/finalbot && git pull && bash deploy/update.sh && bash agents/claude_code/install_agents.sh'
```
(`install_agents.sh` copies the subagents + slash commands into place; run it whenever an agent or
command file changes.)

---

## 5. Key files

| File | Role |
|---|---|
| `backend/config.py` | `ModeManager` (paper/live, kill switch, drawdown re-arm, mode persistence); `DEFAULT_TRADING_CONFIG`; key helpers. |
| `backend/exchange.py` | Single ccxt client factory (live/demo/testnet); closed-trades cache; OHLCV/balance/positions. |
| `backend/indicators.py` | Pure-Python indicators; **anti-chase `signal()`** (see §7). |
| `backend/scanner.py` | Multi-timeframe scan + `composite()`; writes `decisions/_scan_latest.json`. |
| `backend/market_structure.py` | Funding / OI / long-short / orderbook imbalance → `structure_bias`. |
| `backend/engine.py` | **Execution engine** — preflight safety, sizing from config, entry/SL/TP, order replacement. |
| `backend/scheduler.py` | Background loop — reconcile, log closures, expire stale orders, AI-gated cycle, headless AI runner. |
| `backend/main.py` | FastAPI app + all API endpoints; deposit-proof P&L; mode restore. |
| `backend/backtest.py` | Replays the mechanical `signal()` over history; returns stats + equity curve. |
| `agents/pick_candidates.py` | **NEW** — prints the exact pairs the debate may analyze (threshold-filtered). |
| `agents/claude_code/commands/analyze-lite.md` | Lite debate command; now reads `pick_candidates.py`. |
| `agents/claude_code/agents/*.md` | The subagents (asset-aware: crypto vs tokenized stock/ETF vs gold). |

---

## 6. The instrument universe

Crypto plus **tokenized stocks/ETFs and gold**, all as Bybit perps. Gold is `XAUT/USDT` (and `PAXG`).
The agents are **asset-aware**: they analyze tokenized equities as equities (earnings, index,
market hours, holiday gaps) and ignore crypto-only metrics for them; crypto is analyzed with
funding/OI/dominance, etc.

---

## 7. Major design decisions & fixes (chronological themes)

**AI on subscription, headless.** Originally the debate was to be interactive only. Per your
request it now runs automatically and headlessly via `claude -p … --output-format stream-json`,
still on your subscription (no API key). Requires the non-root user.

**Risk split: config vs AI.** Position **size and leverage come from your config** (your risk
budget). The AI only sets **direction, entry, and (cautiously) SL/TP**. This fixed an early bug
where the AI's tiny `size` produced ~$12 positions.

**Deposit-proof P&L.** P&L is computed as **realized (Bybit closed-PnL) + unrealized (open
positions)**, never `equity − baseline`. This stopped deposits/withdrawals and mixed paper/live
history from showing up as fake profit/loss. Equity is also **mode-filtered** (paper and live are
separate accounts).

**Kill switch re-arm.** After a manual reset, drawdown is measured only from the reset moment
forward (`dd_reference_ts`), so stale peaks can't instantly re-trip the auto-stop. This fixed the
"kill switch re-engages right after reset" bug and the "switched to mainnet and it halted" bug.

**Anti-chase scoring.** The old confidence score gave ~100% to already-bled/oversold names. `signal()`
was rebuilt to separate *directional bias* from *entry quality* (bias × freshness × room, minus an
exhaustion penalty, capped ±0.9), so it stops rewarding chase entries.

**Order/status correctness.** Distinguished a filled market order (`executed`, position open) from a
resting limit (`resting`, no position yet) — this fixed "BTC shows executed but no trade". Added
reconcile (resting→executed once a position appears), closure alerts, and stale-limit expiry (TTL
`ai_order_ttl_min`).

**Backtest harness.** `backtest.py` + a dashboard tab replays the mechanical strategy over a
selectable window and reports return, Sharpe, win rate, profit factor, max drawdown, and an equity
curve — so the strategy can be evaluated before risking money.

**Modern dashboard.** Full UI overhaul: ink palette + indigo accent, glassy pill nav, two-pane
Debates view (list + detail with per-agent cards + live AI panel), scanner with an AI column, and
per-tab polish.

---

## 8. Most recent fixes (this session)

**Token burn — debate was analyzing ALL pairs.** In AI-gated mode the scanner correctly filtered to
pairs above the threshold, but the debate still analyzed the whole 21-pair universe (you saw only
COIN/BTC/TSLA ≥50%, yet decisions were written for all 21). **Root cause:** candidates were passed
as slash-command arguments (`/analyze-lite BTC…`), but headless `claude -p` doesn't reliably
populate `$ARGUMENTS`, so the command hit its "no args → whole universe" fallback.

**Fix:**
- New `agents/pick_candidates.py` prints the exact pairs to debate. Resolution order:
  1. `decisions/_debate_targets.json` `{"full": true}` → full universe (explicit manual sweep only).
  2. that file with non-empty `symbols` → exactly those (AI-gated candidates).
  3. otherwise compute from the latest scan + `auto_trade_confidence` (self-contained).
  It **never falls back to the whole universe** on its own.
- `analyze-lite.md` now calls `pick_candidates.py` instead of reading the config universe.
- `scheduler.run_ai_analyze()` writes the targets file (`{"symbols": [...]}` for gated,
  `{"full": true}` for a manual "Run analysis now").
- **Verified** across all cases: compute-from-scan → COIN/BTC/TSLA; gated → exactly the passed pairs;
  full sweep → universe. The whole-universe path is gone unless you explicitly trigger it.

**SL/TP were being wiped when replacing a stale limit.** The entry-replacement logic cancelled *all*
open orders on a symbol, which included the position's stop-loss / take-profit. **Fix:** added
`engine.is_protective_order()`; both the entry-replacement loop (`engine.py`) and the stale-order
expiry (`scheduler.py`) now **skip any SL / TP / reduce-only / conditional order**. Only a plain
resting *entry* limit can be replaced. If a position is already open, the symbol is left untouched.

**requirements.txt corruption.** A stray past command had appended the symbol universe into
`requirements.txt`, which broke `pip install` during deploy (`Invalid requirement: ', TSM/USDT…'`).
Cleaned back to the six real dependencies. Nothing in the code writes to that file, so it was a
one-off. **This fix is committed locally (`e481435`) but still needs `git push` from your Mac.**

---

## 9. Configuration (`DEFAULT_TRADING_CONFIG`)

Key settings (editable from the Automation tab):

- `symbol_universe`, `timeframe`, `scan_timeframes`, `scan_interval_min`, `scan_enabled`
- `leverage`, `position_size_pct`, `stop_loss_pct`, `take_profit_pct`
- `max_drawdown_pct`, `daily_loss_limit_pct`, `min_minutes_between_trades`
- `auto_trade`, `auto_trade_confidence` (the gate threshold), `ai_gated`
- `auto_analyze`, `ai_lite`, `ai_timeout_sec` (default 1200), `ai_order_ttl_min` (default 120)

**`.env`:** Bybit key pairs (paper + mainnet), `BYBIT_PAPER_BACKEND=demo`, `ALLOW_IP`, Basic Auth
creds. Never commit `.env`.

---

## 10. Operations runbook

**Deploy after pushing code:**
```bash
sudo -u finalbot -H bash -lc 'cd /opt/finalbot && git pull && bash deploy/update.sh && bash agents/claude_code/install_agents.sh'
```

**Watch logs:**
```bash
journalctl -u finalbot -f            # service logs
tail -f /opt/finalbot/data/ai_debate.log   # live AI debate output
```

**Restart / status:**
```bash
sudo systemctl restart finalbot
sudo systemctl status finalbot
```

**Common gotchas:**
- Run git/deploy **as `finalbot`**, not root (avoids "dubious ownership" and the
  `--dangerously-skip-permissions cannot be used as root` error).
- Runtime files are gitignored and skip-worktree'd so `git pull` won't conflict:
  `decisions/_scan_latest.json`, `decisions/_debate_targets.json`, `data/ai_debate.log`,
  `data/auto_analyze.log`.
- If the balance shows $0 in demo: confirm keys were made *inside* Demo Trading and funds moved to
  the Unified wallet.
- If the AI debate over-analyzes: check `decisions/_debate_targets.json` and run
  `python3 agents/pick_candidates.py` — it should print only threshold-passing pairs.

---

## 11. Open items / next steps

- **Push the requirements.txt fix** (`git push`) and re-run the deploy — the token-burn and SL/TP
  fixes go live in the same deploy.
- After deploy, confirm the next AI-gated cycle writes **3 decisions** (one per qualifying pair),
  not 20.
- Optional: decide whether a stale `{"symbols": []}` targets file should mean "debate nothing"
  (stricter) vs the current safe "recompute from threshold". Current behavior can never over-debate.
- Longer-term: the strategy is still lightly validated — keep using the backtest tab before scaling
  size or going live with meaningful capital.
