#!/usr/bin/env bash
# Pull latest code, rebuild, restart. Run on the server:  bash deploy/update.sh
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

echo "==> git pull"
git pull --ff-only

echo "==> backend deps"
.venv/bin/pip install -q -r requirements.txt

echo "==> rebuild frontend"
( cd frontend && npm install --no-audit --no-fund && npm run build )

echo "==> restart service"
sudo systemctl restart finalbot
echo "Done. https URL is live again."
