#!/usr/bin/env bash
# =============================================================================
#  auto_analyze.sh — run the AI debate headlessly, then let Layer 2 act on it.
#
#  !!! HEADLESS AI LOOP — the thing this project originally avoided. You asked
#      for it explicitly. Notes:
#      - It runs on your Claude Code SUBSCRIPTION login (claude -p), NOT an API
#        key, so it will NOT switch you to paid per-token billing.
#      - It makes trading fully unattended. KEEP IT IN PAPER until you trust it.
#      - Auto-execution still respects the kill switch, drawdown auto-stop, your
#        confidence threshold, and the auto_trade toggle (Automation tab).
#
#  Intended to be run by cron every 30 min (see crontab line at the bottom).
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

# cron runs with a minimal PATH — make sure `claude`, node, curl are findable.
export PATH="$HOME/.npm-global/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"

LOG="data/auto_analyze.log"
mkdir -p data
echo "[$(date)] === auto /analyze start ===" >> "$LOG"

# 1) Run the multi-agent debate headlessly on your subscription.
#    --dangerously-skip-permissions lets it run the scan + write the decision
#    file unattended (it needs to run bash + write to decisions/).
if ! claude -p "/analyze" --dangerously-skip-permissions >> "$LOG" 2>&1; then
  echo "[$(date)] claude run FAILED (is claude installed and /login done?)" >> "$LOG"
  exit 1
fi

# 2) Nudge Layer 2 to process the brand-new decision immediately. /api/scan/run
#    runs one scheduler cycle, which auto-executes the latest decision IF
#    auto_trade is ON and its confidence >= your threshold (and preflight passes).
curl -s -X POST http://localhost:8000/api/scan/run > /dev/null || \
  echo "[$(date)] backend not reachable on :8000 (start it with start.sh)" >> "$LOG"

echo "[$(date)] === auto /analyze done ===" >> "$LOG"

# -----------------------------------------------------------------------------
#  To schedule every 30 minutes, run `crontab -e` and add (use your real path):
#
#     */30 * * * * /bin/bash "/Users/abc/Documents/Projects/FinalBot/auto_analyze.sh"
#
#  Then check it's working:   tail -f data/auto_analyze.log
#  To stop automation:        crontab -e  and delete that line.
# -----------------------------------------------------------------------------
