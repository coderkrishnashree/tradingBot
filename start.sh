#!/usr/bin/env bash
# =============================================================================
#  start.sh — launch the whole stack with one command.
#
#  Starts:
#    1. Layer 2 backend  (FastAPI + the always-on scanner loop)  on :8000
#    2. Dashboard        (Vite dev server)                       on :5173
#
#  It also does first-run setup if needed (Python venv + deps, npm install),
#  and shuts BOTH down cleanly when you press Ctrl+C.
#
#  The AI debate is NOT started here — that runs on your subscription inside
#  Claude Code (`claude` -> /analyze), on demand. See the "Connect Claude" tab.
#
#  Usage:
#     bash start.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

BACKEND_PORT=8000
FRONTEND_PORT=5173

echo "==> Bybit Multi-Agent Trading — starting (default: PAPER/testnet)"

# --- warn if .env is missing -------------------------------------------------
if [ ! -f .env ]; then
  echo "    [!] No .env found. Copying .env.example -> .env (add your TESTNET keys)."
  cp .env.example .env
fi

# --- Python venv + deps (first run only) ------------------------------------
if [ ! -d .venv ]; then
  echo "==> Creating Python venv and installing backend deps (first run)…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi

# --- frontend deps (first run only) -----------------------------------------
if [ ! -d frontend/node_modules ]; then
  echo "==> Installing frontend deps (first run)…"
  (cd frontend && npm install --no-audit --no-fund)
fi

# --- launch both, track PIDs, clean up on exit ------------------------------
PIDS=()
cleanup() {
  echo ""
  echo "==> Shutting down…"
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "==> Stopped."
}
trap cleanup INT TERM EXIT

echo "==> Backend  -> http://localhost:${BACKEND_PORT}  (API docs at /docs)"
./.venv/bin/uvicorn backend.main:app --port "${BACKEND_PORT}" &
PIDS+=($!)

echo "==> Frontend -> http://localhost:${FRONTEND_PORT}"
(cd frontend && npm run dev -- --port "${FRONTEND_PORT}") &
PIDS+=($!)

echo ""
echo "==> Up. Open  http://localhost:${FRONTEND_PORT}   (Ctrl+C stops both)"
wait
