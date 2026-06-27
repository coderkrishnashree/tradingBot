#!/usr/bin/env bash
# =============================================================================
#  FinalBot — ONE-FILE server setup for a PLAIN DigitalOcean droplet (no domain)
# =============================================================================
#  Fresh Ubuntu 22.04/24.04 droplet -> fully running, HTTPS (self-signed) on the
#  server's IP, password-protected, firewalled to your home IP, auto-starts on
#  reboot. Clones the repo, builds everything, no domain required.
#
#  HOW TO USE:
#    1. Edit the 3 values in the CONFIG block just below.
#    2. Copy this file onto the droplet (or paste it into `nano server-setup.sh`).
#    3. Run:   sudo bash server-setup.sh
#    4. Open:  https://YOUR_DROPLET_IP   (click through the one-time cert warning)
#    5. Paste your Bybit keys:  sudo nano /opt/finalbot/.env  then
#                               sudo systemctl restart finalbot
#
#  NOTE: the AI debate (Claude Code) is optional and set up separately — the
#  dashboard + auto-screener work without it. See deploy/README.md.
# =============================================================================
set -euo pipefail

# ----------------------------- CONFIG (EDIT ME) ------------------------------
GIT_URL="https://github.com/coderkrishnashree/tradingBot"   # <-- your repo URL
ALLOW_IP=""                                          # <-- your home IP (curl ifconfig.me). blank = open to all (NOT recommended)
AUTH_USER="admin"                                  # dashboard login name
AUTH_PASS="Lamojasto@Lamojasto0116"                              # <-- dashboard password
INSTALL_DIR="${INSTALL_DIR:-/opt/finalbot}"
# -----------------------------------------------------------------------------

[ "$(id -u)" = "0" ] || { echo "Run with sudo: sudo bash server-setup.sh"; exit 1; }
[ "$GIT_URL" != "https://github.com/CHANGE_ME/FinalBot.git" ] || { echo "Edit GIT_URL at the top first."; exit 1; }
[ "$AUTH_PASS" != "CHANGE_ME" ] || { echo "Edit AUTH_PASS at the top first."; exit 1; }

SERVER_IP="$(curl -fsSL ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
export DEBIAN_FRONTEND=noninteractive

echo "==> [1/9] System packages…"
apt-get update -y
apt-get install -y git python3-venv python3-pip nginx apache2-utils ufw curl openssl
if ! command -v npm >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "==> [2/9] Cloning repo into $INSTALL_DIR…"
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --ff-only || true
else
  rm -rf "$INSTALL_DIR"
  git clone "$GIT_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

echo "==> [3/9] Python venv + backend deps…"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> [4/9] Building frontend…"
( cd frontend && npm install --no-audit --no-fund && npm run build )

echo "==> [5/9] .env (fill in Bybit keys after this finishes)…"
[ -f .env ] || cp .env.example .env
chmod 600 .env

echo "==> [6/9] systemd service…"
cat >/etc/systemd/system/finalbot.service <<EOF
[Unit]
Description=FinalBot trading backend
After=network.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now finalbot

echo "==> [7/9] Basic Auth + self-signed TLS cert…"
htpasswd -bc /etc/nginx/.finalbot_htpasswd "$AUTH_USER" "$AUTH_PASS"
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/finalbot.key -out /etc/nginx/ssl/finalbot.crt \
  -subj "/CN=$SERVER_IP" >/dev/null 2>&1

echo "==> [8/9] nginx reverse proxy (HTTPS on the IP)…"
cat >/etc/nginx/sites-available/finalbot <<'NGINX'
server { listen 80 default_server; server_name _; return 301 https://$host$request_uri; }
server {
    listen 443 ssl default_server;
    server_name _;
    ssl_certificate     /etc/nginx/ssl/finalbot.crt;
    ssl_certificate_key /etc/nginx/ssl/finalbot.key;
    client_max_body_size 5m;
    location / {
        auth_basic "FinalBot";
        auth_basic_user_file /etc/nginx/.finalbot_htpasswd;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/finalbot /etc/nginx/sites-enabled/finalbot
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "==> [9/9] Firewall…"
ufw allow OpenSSH || true
for PORT in 80 443; do
  if [ -n "$ALLOW_IP" ]; then
    ufw allow from "$ALLOW_IP" to any port "$PORT" proto tcp || true
  else
    ufw allow "$PORT"/tcp || true
  fi
done
[ -z "$ALLOW_IP" ] && echo "   [!] ALLOW_IP blank — open to the whole internet (password only)."
ufw --force enable

echo ""
echo "============================================================"
echo " DONE.  Open:  https://$SERVER_IP"
echo "   login: $AUTH_USER   (click through the one-time cert warning)"
echo ""
echo " Next: add your Bybit keys, then restart:"
echo "   sudo nano $INSTALL_DIR/.env"
echo "   sudo systemctl restart finalbot"
echo ""
echo " Logs:    journalctl -u finalbot -f"
echo " Update:  cd $INSTALL_DIR && sudo bash deploy/update.sh"
echo " Boots in PAPER mode. Live stays gated in the UI."
echo "============================================================"