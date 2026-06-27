#!/usr/bin/env bash
# =============================================================================
#  FinalBot one-command server installer (Ubuntu 22.04/24.04 droplet).
#
#  Sets up, behind nginx, the WHOLE stack on a single HTTPS URL with auth:
#    - Python venv + deps, builds the React frontend
#    - systemd service running the backend (+ scanner loop) on 127.0.0.1:8000
#    - nginx reverse proxy with HTTP Basic Auth
#    - Let's Encrypt HTTPS (certbot)
#    - UFW firewall: SSH open, port 80 open (ACME + redirect), port 443 LOCKED
#      to your home IP so only YOU can reach the dashboard.
#
#  Usage (after `git clone ... && cd FinalBot`):
#    sudo DOMAIN=bot.example.com EMAIL=you@example.com ALLOW_IP=1.2.3.4 \
#         AUTH_USER=admin AUTH_PASS='a-strong-password' bash deploy/install.sh
#
#  Any missing value is prompted for. Re-running is safe (idempotent-ish).
#
#  PREREQUISITES you must do first:
#    1. Point an A record for DOMAIN at this droplet's public IP.
#    2. Know your home/office public IP (https://ifconfig.me) for ALLOW_IP.
#  NOTE: the AI brain (Claude Code) is set up separately — see deploy/README.md.
# =============================================================================
set -euo pipefail

[ "$(id -u)" = "0" ] || { echo "Please run with sudo: sudo bash deploy/install.sh"; exit 1; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-root}"

ask() { local var="$1" prompt="$2" def="${3:-}"; local cur="${!var:-}"
  if [ -z "$cur" ]; then read -rp "$prompt${def:+ [$def]}: " cur; cur="${cur:-$def}"; fi
  printf -v "$var" '%s' "$cur"; }

ask DOMAIN     "Domain (leave BLANK to use this server's IP with a self-signed cert)"
ask EMAIL      "Email for Let's Encrypt (only used if a domain is set)"
ask ALLOW_IP   "Your home/office public IP allowed to reach the dashboard (blank = allow all)"
ask AUTH_USER  "Dashboard username" "admin"
ask AUTH_PASS  "Dashboard password"
[ -n "$AUTH_PASS" ] || { echo "AUTH_PASS is required."; exit 1; }

SERVER_IP="$(curl -fsSL ifconfig.me 2>/dev/null || echo "")"
if [ -n "$DOMAIN" ] && ! [[ "$DOMAIN" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  TLS_MODE="letsencrypt"; URL_HOST="$DOMAIN"
else
  TLS_MODE="selfsigned"; DOMAIN=""; URL_HOST="${SERVER_IP:-YOUR_SERVER_IP}"
fi
echo "==> TLS mode: $TLS_MODE   (dashboard host: $URL_HOST)"

echo "==> Installing system packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3-venv python3-pip nginx certbot python3-certbot-nginx \
                   apache2-utils ufw curl git
if ! command -v npm >/dev/null 2>&1; then
  echo "==> Installing Node.js 20…"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "==> Python venv + backend deps…"
sudo -u "$RUN_USER" python3 -m venv "$REPO_DIR/.venv"
sudo -u "$RUN_USER" "$REPO_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$RUN_USER" "$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"

echo "==> Building frontend…"
sudo -u "$RUN_USER" bash -c "cd '$REPO_DIR/frontend' && npm install --no-audit --no-fund && npm run build"

echo "==> Ensuring .env exists (fill in your Bybit keys after install)…"
[ -f "$REPO_DIR/.env" ] || sudo -u "$RUN_USER" cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"

echo "==> systemd service (backend + scanner loop)…"
cat >/etc/systemd/system/finalbot.service <<EOF
[Unit]
Description=FinalBot trading backend
After=network.target

[Service]
User=$RUN_USER
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now finalbot

echo "==> HTTP Basic Auth user…"
htpasswd -bc /etc/nginx/.finalbot_htpasswd "$AUTH_USER" "$AUTH_PASS"

PROXY_BLOCK='
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
    }'

if [ "$TLS_MODE" = "selfsigned" ]; then
  echo "==> Generating self-signed TLS cert for $URL_HOST…"
  mkdir -p /etc/nginx/ssl
  openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/finalbot.key -out /etc/nginx/ssl/finalbot.crt \
    -subj "/CN=$URL_HOST" >/dev/null 2>&1

  echo "==> nginx (self-signed HTTPS on the IP)…"
  cat >/etc/nginx/sites-available/finalbot <<EOF
server { listen 80 default_server; server_name _; return 301 https://\$host\$request_uri; }
server {
    listen 443 ssl default_server;
    server_name _;
    ssl_certificate     /etc/nginx/ssl/finalbot.crt;
    ssl_certificate_key /etc/nginx/ssl/finalbot.key;
    client_max_body_size 5m;
$PROXY_BLOCK
}
EOF
else
  echo "==> nginx (will get a real cert from Let's Encrypt)…"
  cat >/etc/nginx/sites-available/finalbot <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 5m;
$PROXY_BLOCK
}
EOF
fi

ln -sf /etc/nginx/sites-available/finalbot /etc/nginx/sites-enabled/finalbot
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "==> Firewall…"
ufw allow OpenSSH || true
if [ "$TLS_MODE" = "letsencrypt" ]; then
  ufw allow 80/tcp || true        # ACME challenge + http->https redirect
fi
for PORT in 80 443; do
  # In self-signed mode lock BOTH; in LE mode 80 is already open above.
  if [ "$TLS_MODE" = "selfsigned" ] || [ "$PORT" = "443" ]; then
    if [ -n "$ALLOW_IP" ]; then
      ufw allow from "$ALLOW_IP" to any port "$PORT" proto tcp || true
    else
      ufw allow "$PORT"/tcp || true
    fi
  fi
done
[ -z "$ALLOW_IP" ] && echo "   [!] ALLOW_IP blank — port is open to the internet (Basic Auth only)."
ufw --force enable

if [ "$TLS_MODE" = "letsencrypt" ]; then
  echo "==> HTTPS via Let's Encrypt…"
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect \
    || echo "   [!] certbot failed (check DNS A record). Retry: sudo certbot --nginx -d $DOMAIN --redirect"
fi

echo ""
echo "============================================================"
echo " FinalBot is up:  https://$URL_HOST   (login: $AUTH_USER)"
[ "$TLS_MODE" = "selfsigned" ] && echo " (Self-signed cert: your browser will warn once — click 'proceed'. It IS encrypted.)"
echo " 1) Edit keys:    nano $REPO_DIR/.env   then: sudo systemctl restart finalbot"
echo " 2) Logs:         journalctl -u finalbot -f"
echo " 3) AI brain:     see deploy/README.md to set up Claude Code on this box"
echo " It boots in PAPER mode. Live is still gated in the UI."
echo "============================================================"
