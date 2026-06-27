#!/usr/bin/env bash
# =============================================================================
#  Migrate FinalBot from running as ROOT to a dedicated non-root user.
#
#  WHY: Claude Code refuses `claude -p --dangerously-skip-permissions` when run
#  as root (security). The backend spawns claude for AI-gated / auto-run AI, so
#  it must run as a normal user. This script does the migration; then you do a
#  one-time Claude login as that user.
#
#  Run on the server:   sudo bash deploy/make-nonroot.sh
# =============================================================================
set -euo pipefail
[ "$(id -u)" = "0" ] || { echo "Run with sudo: sudo bash deploy/make-nonroot.sh"; exit 1; }

INSTALL_DIR="${INSTALL_DIR:-/opt/finalbot}"
USERNAME="${USERNAME:-finalbot}"
NPM_BIN="/home/$USERNAME/.npm-global/bin"

echo "==> Creating user '$USERNAME' (if missing)…"
id "$USERNAME" >/dev/null 2>&1 || useradd -m -d "/home/$USERNAME" -s /bin/bash "$USERNAME"

echo "==> Giving '$USERNAME' ownership of $INSTALL_DIR…"
chown -R "$USERNAME":"$USERNAME" "$INSTALL_DIR"

echo "==> Rewriting systemd service to run as '$USERNAME'…"
cat >/etc/systemd/system/finalbot.service <<EOF
[Unit]
Description=FinalBot trading backend
After=network.target

[Service]
User=$USERNAME
Group=$USERNAME
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=HOME=/home/$USERNAME
Environment=PATH=$NPM_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl restart finalbot
echo "   Backend now runs as '$USERNAME'."

echo "==> Installing Claude Code for '$USERNAME' (user-local, no root needed at runtime)…"
sudo -u "$USERNAME" -H bash -lc '
  set -e
  mkdir -p ~/.npm-global
  npm config set prefix ~/.npm-global
  grep -q ".npm-global/bin" ~/.bashrc 2>/dev/null || echo "export PATH=\$HOME/.npm-global/bin:\$PATH" >> ~/.bashrc
  npm i -g @anthropic-ai/claude-code >/dev/null 2>&1 || npm i -g @anthropic-ai/claude-code
' || echo "   [!] npm install failed — install Node/npm, then re-run."

cat <<EOF

============================================================
 Almost done. Two one-time manual steps as '$USERNAME':

 1) Log in to your Claude Max account (opens a URL to paste in any browser):
      sudo -u $USERNAME -H bash -lc 'cd $INSTALL_DIR && claude'
      # then type:  /login   and follow the prompt, then exit Claude Code

 2) Install the trading agents for this project:
      sudo -u $USERNAME -H bash -lc 'cd $INSTALL_DIR && bash agents/claude_code/install_agents.sh'

 Verify:  the dashboard's "Connect Claude" tab should show "CLI detected".
 Then turn ON "AI-gated" in the Automation tab — the agents now decide trades.
============================================================
EOF
