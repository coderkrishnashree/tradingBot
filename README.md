# Bybit Multi-Agent Trading System

A two-layer crypto trading bot for **Bybit** (via ccxt) with a modern dark web dashboard.

- **Layer 1 — AI brain:** a multi-agent *debate* (Research / Bull / Bear / Risk / Portfolio)
  that runs **interactively inside Claude Code, on your Max subscription**. It scans every pair
  in your universe and writes a decision JSON + transcript to `decisions/`. It is **never**
  wired to a background loop and **never** calls the Anthropic API directly.
- **Layer 2 — mechanical engine:** plain always-on Python (no Claude tokens). FastAPI backend +
  execution engine. Reads approved decisions, places orders on Bybit, tracks the portfolio,
  logs to SQLite, computes stats, and owns the kill switch + max-drawdown auto-stop.
- **Dashboard:** React + Tailwind + Vite. Dark, card-based, responsive, auto-refreshing.

> **Safety first.** The app **always boots in PAPER / TESTNET mode.** Going LIVE is a gated,
> multi-step opt-in (type `GO LIVE` + mainnet keys present + kill switch clear). A single click
> can never move you to real funds, and live is never remembered across restarts.

---

## 1. One-time setup

```bash
cd FinalBot

# Python (Layer 2 backend + tools)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Keys: copy and fill in. Start with TESTNET keys only.
cp .env.example .env
#   BYBIT_TESTNET_KEY / SECRET   <- from https://testnet.bybit.com  (API Management)
#   leave the MAINNET keys blank until you truly intend to go live.

# Install the Layer 1 agents into Claude Code (.claude/)
bash agents/claude_code/install_agents.sh

# Frontend deps
cd frontend && npm install && cd ..
```

## 2. Start everything (3 pieces)

```bash
# Terminal 1 — Layer 2 backend (always-on, no Claude tokens)
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000

# Terminal 2 — dashboard
cd frontend && npm run dev          # -> http://localhost:5173

# Terminal 3 — Layer 1 brain, ON DEMAND only (your subscription)
claude                              # open Claude Code in the project root
#   then type:  /analyze
```

Open **http://localhost:5173**. You'll see the green PAPER banner, your (test) portfolio, and —
once you've run `/analyze` at least once — the agent debate with Approve / Reject.

### The full loop
1. In Claude Code, run `/analyze`. The agents debate across all pairs and write a decision to
   `decisions/`.
2. The dashboard auto-loads it into the **Agent Debate** panel (polls every ~6s; or click
   "Check for new decision").
3. Review the transcript. Click **Approve & execute** → Layer 2 places the order on Bybit in
   the active mode (testnet by default). Or **Reject**.
4. Portfolio, positions, equity curve, stats, and order history update live.

---

## 3. Code map (so you can modify it)

```
FinalBot/
├── backend/                      # LAYER 2 — always-on Python, no Claude tokens
│   ├── config.py                 # env keys + ModeManager (paper/live single source of truth)
│   ├── exchange.py               # the ONE ccxt-bybit wrapper; flips testnet/mainnet by mode
│   ├── indicators.py             # pure-Python TA + signal score (shared by scanner + agents)
│   ├── scanner.py                # multi-timeframe screener: all pairs x all TFs -> confidence%
│   ├── scheduler.py              # always-on 30-min loop: scan + auto-trade (NO tokens)
│   ├── engine.py                 # execution: decision -> Bybit order; kill switch + DD auto-stop
│   ├── db.py                     # SQLite schema + helpers (orders, equity, settings, decisions, alerts)
│   ├── stats.py                  # total return / win rate / Sharpe / max drawdown
│   ├── models.py                 # pydantic schemas + input validation
│   ├── decisions_io.py           # reads Layer 1's decision/transcript files
│   └── main.py                   # FastAPI app — every dashboard endpoint
│
├── agents/                       # LAYER 1 — the AI brain (runs in Claude Code)
│   ├── market_scan.py            # pulls Bybit OHLCV + indicators -> decisions/_scan_latest.json
│   ├── write_decision.py         # validates + writes the decision JSON + transcript
│   ├── README.md                 # how the debate works
│   └── claude_code/
│       ├── agents/*.md           # the 5 subagents (research, bull, bear, risk, portfolio)
│       ├── commands/analyze.md   # the /analyze orchestrator
│       └── install_agents.sh     # copies the above into .claude/
│
├── frontend/                     # DASHBOARD — React + Tailwind + Vite
│   ├── src/App.jsx               # layout + independent pollers
│   ├── src/api.js                # REST wrapper + usePoll hook + formatters
│   └── src/components/           # ModeBanner, KillSwitch, PortfolioOverview, PositionsTable,
│                                 # Charts, StatsPanel, OrderHistory, AgentPanel, ConfigPanel,
│                                 # LiveTradingSection, RunAnalysis,
│                                 # ScannerTable, PairDetail, AutomationPanel, AlertsFeed, ConnectClaude
│       (tabs: Overview · Scanner · Automation · Alerts · Connect Claude)
│
├── decisions/                    # Layer 1 output (decision JSON + transcript) — the L1<->L2 bridge
├── data/trading.db               # SQLite (created on first run; local disk)
├── .env / .env.example           # API keys (never committed)
└── requirements.txt
```

**Where to change things:**
- Add/adjust an agent's reasoning → edit `agents/claude_code/agents/*.md`, re-run the install script.
- Change indicators the agents see → `agents/market_scan.py`.
- Change how orders are sized/placed → `backend/engine.py` (`_amount_from_size`, `execute_decision`).
- Add an API endpoint → `backend/main.py`.
- Change the UI → `frontend/src/components/*`.
- Trading defaults (universe, leverage, SL/TP, drawdown limit) → the **Config panel** in the UI,
  or `DEFAULT_TRADING_CONFIG` in `backend/config.py` for the seed.

---

## 3b. Automation, the multi-timeframe scanner & the two "brains"

There are **two** decision sources, by design:

**A) Mechanical screener (always-on, NO Claude tokens).** `scheduler.py` runs every
`scan_interval_min` (default 30) and calls `scanner.py`, which pulls OHLCV for **every pair ×
every timeframe** in `scan_timeframes`, scores each timeframe to a signal in [−1,+1], and blends
them (longer timeframes weighted more, +bonus when all agree) into a **0–100% confidence** with a
long/short/flat direction. If **auto-trade** is ON and a pair scores ≥ `auto_trade_confidence`
(your 60–70%), it places the trade automatically in the active mode — same kill-switch + drawdown
preflight as a manual trade, and it skips pairs you already hold. This is what makes "scan every
30 min and trade above the threshold" possible without breaking the no-headless-AI rule.

**B) AI multi-agent debate (on-demand, your subscription).** You run `/analyze` in Claude Code.
If auto-trade is ON, a debate decision above the threshold is also auto-executed ("AI overlay");
otherwise you Approve/Reject it in the Overview tab.

Everything the loop does is written to the **Alerts** feed. The **Scanner** tab shows the live
table (click a pair for its per-timeframe breakdown, or hit **Trade** to act now). The
**Automation** tab toggles scanning / auto-trade, sets the threshold, interval, and timeframes.

> Defaults are safe: `scan_enabled=True` (scanning is harmless), **`auto_trade=False`** (you turn
> it on), and the app still boots in PAPER. Auto-trade executes in whichever mode is active, so
> switching to LIVE makes auto-trade live too — that's intentional per your setup.

## 3c. Connecting Claude Code (the "login" question)

The AI debate runs on your **Claude Max subscription inside Claude Code** — there is deliberately
**no "log in with Claude" box in the dashboard**, because a web app can't use your subscription
directly. Doing so would require an Anthropic **API key = paid per-token billing**, the exact thing
this whole design avoids. Instead you log in **once, inside Claude Code**, against your Anthropic
account:

```bash
npm i -g @anthropic-ai/claude-code     # install
claude                                  # open it in the project folder
/login                                  # one-time browser sign-in with your Max account
bash agents/claude_code/install_agents.sh
/analyze                                # run the debate; the dashboard auto-loads the result
```

The dashboard's **Connect Claude** tab shows live status (CLI installed? agents installed? last
decision?) and these steps with copy buttons. `GET /api/claude/status` powers it.

## 3d. Deploy to a server (HTTPS + auth, one command)

To run it 24/7 on a small droplet (2 GB RAM is plenty) behind a password-protected HTTPS URL.

**Plain IP server, no domain** (self-signed HTTPS on the IP — one browser warning to click through):
```bash
git clone <YOUR_REPO_URL> FinalBot && cd FinalBot
sudo ALLOW_IP=YOUR_HOME_IP AUTH_USER=admin AUTH_PASS='strong-password' bash deploy/install.sh
# then open  https://YOUR_DROPLET_IP
```

**With a domain** (real Let's Encrypt cert, no warning): add `DOMAIN=bot.yourdomain.com EMAIL=you@example.com`.

The installer builds the frontend, runs the backend as a **systemd** service, serves the UI
same-origin, and puts **nginx + HTTPS + Basic Auth** in front with **UFW** locking access to your
home IP. No-domain, domain, and zero-exposure **SSH-tunnel** options + the Claude Code step are all
in **`deploy/README.md`**. Update later with `bash deploy/update.sh`.

> ⚠️ The dashboard can place trades and switch to live — never expose it without auth + the IP
> lock. Keep `ALLOW_IP` set and use a strong password.

## 4. Safety model (read this)

- **Default PAPER.** `ModeManager` constructs in paper mode every boot. Restart = back to testnet.
- **Two key pairs**, never hardcoded: testnet vs mainnet in `.env`.
- **Go-live needs all three:** type `GO LIVE` in the gated Live section, mainnet keys present,
  kill switch clear. The UI button stays disabled until the first two hold; the backend re-checks.
- **Kill switch** cancels resting orders and halts Layer 2. Engaging is one click; resetting is a
  separate deliberate action.
- **Max-drawdown auto-stop:** if the equity curve falls past `max_drawdown_pct`, the engine
  auto-engages the kill switch (checked on every portfolio poll and before every order).
- **Live execution** additionally pops a browser confirm before sending a real order.

> 🚫 **Never** add an `ANTHROPIC_API_KEY`, a cron job, or a headless loop around Layer 1. That
> switches the AI reasoning to paid API billing and breaks the subscription-only design. If a
> future step seems to require it, stop and reconsider.

---

## 5. Roadmap (ranked, for later)

1. **Live-trading hardening** (do first before real funds): verify fills with `fetch_order`,
   reconcile partial fills, retry/timeout handling, idempotency keys per decision, per-symbol
   max position caps, and a daily-loss limit separate from drawdown.
2. **Notifications:** the in-app **Alerts** feed already logs scans, auto-trades, kill switch and
   drawdown. Next: push those same events out to Telegram/Discord/email.
3. **Realized-PnL accounting:** match closes to opens to populate `pnl` per trade (sharpens win
   rate + the stats panel). Currently P&L is account-derived; per-trade attribution is approximate.
4. **More agents / better debate:** a Macro agent (funding, OI, BTC dominance), a Sentiment agent
   (news/social), and a Devil's-Advocate pass that re-attacks the Portfolio Manager's pick.
5. **Backtest harness:** replay `market_scan` history through the same sizing/SL/TP logic to
   sanity-check the strategy before live.
6. **Scheduled reminders (not auto-trading):** a daily nudge to run `/analyze` — the decision and
   execution stay human-in-the-loop.
7. **WebSocket feeds:** replace polling with Bybit WS for sub-second positions/marks.

---

## Build status
- Stage 1 backend: 14 endpoints verified (boots paper, go-live guards reject, config validation,
  graceful no-keys, kill switch). ✓
- Stage 2 agents: full example debate written + served (`decisions/20260627-124112_*`). ✓
- Stage 3 dashboard: `vite build` clean, 47 modules. ✓
- Stage 4 wiring: approve→execute, reject, and drawdown auto-stop verified. ✓
- Expansion: MTF scanner (5 pairs × 4 TFs, composite confidence + alignment), 30-min scheduler
  thread, auto-trade gating + alerts, manual "Trade now", tabbed UI (Scanner / Automation /
  Alerts / Connect Claude), Claude-status endpoint. Backend + `vite build` (52 modules) verified. ✓
