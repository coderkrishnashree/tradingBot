# Deploying FinalBot to a server (HTTPS + auth, one command)

This puts the **whole app** behind one HTTPS URL protected by a password and a firewall,
on a small droplet (2 GB RAM is plenty).

## What you get
- Backend + always-on scanner as a **systemd service** (auto-restarts, survives reboot)
- React frontend **built and served by the backend** (single port — no CORS)
- **nginx** reverse proxy with **HTTP Basic Auth** + **Let's Encrypt HTTPS**
- **UFW firewall**: SSH open, port 80 open (only for cert + redirect), **port 443 locked to
  your home IP** so nobody else can even reach the dashboard

## Before you start
1. Create the droplet (Ubuntu 22.04/24.04, 2 GB).
2. Find your home/office public IP: `curl ifconfig.me` (used to lock down access).
3. (Optional) If you have a domain, point a DNS **A record** at the droplet for a *real* cert.

## Install on a PLAIN IP server (no domain) — recommended for you
Leave `DOMAIN` blank and the installer uses a **self-signed HTTPS cert on the IP**. Encrypted +
password + firewall; the only quirk is a one-time browser "proceed anyway" warning.
```bash
git clone <YOUR_REPO_URL> FinalBot
cd FinalBot
sudo ALLOW_IP=YOUR_HOME_IP AUTH_USER=admin AUTH_PASS='a-strong-password' bash deploy/install.sh
```
Then open **https://YOUR_DROPLET_IP** and click through the warning once.

## Install WITH a domain (real cert, no warning)
```bash
sudo DOMAIN=bot.yourdomain.com EMAIL=you@example.com ALLOW_IP=YOUR_HOME_IP \
     AUTH_USER=admin AUTH_PASS='a-strong-password' bash deploy/install.sh
```
No domain but want a real cert? Get a free one in 5 min from **DuckDNS**
(`yourname.duckdns.org` → your IP), then run the command above with that as `DOMAIN`.

> Leave any variable out and it prompts you. Leave `ALLOW_IP` blank to allow any IP — then the
> only protection is the password, which is **not** recommended for live trading.

## Most secure option (no public exposure at all): SSH tunnel
If you'd rather expose nothing, skip nginx entirely. Run the backend bound to localhost on the
droplet (the systemd service already binds `127.0.0.1:8000`), then from your laptop:
```bash
ssh -L 8000:localhost:8000 root@YOUR_DROPLET_IP
```
…and open **http://localhost:8000**. Nothing is reachable from the internet. (You can even
`sudo systemctl stop nginx && sudo ufw deny 443` to close the web entirely and use only this.)

After it finishes:
```bash
nano .env                       # paste your Bybit DEMO/TESTNET (and later MAINNET) keys
sudo systemctl restart finalbot
```
Open **https://bot.yourdomain.com** and log in. It boots in **PAPER** mode; live is still gated
in the UI.

## The AI brain (Claude Code) on the server
Layer 1 (the agent debate) runs on **your Claude subscription via Claude Code** — install it on
the droplet too:
```bash
sudo npm i -g @anthropic-ai/claude-code
cd ~/FinalBot && claude            # then run /login and open the printed URL in ANY browser
bash agents/claude_code/install_agents.sh
```
Then either use the **Auto-run AI** toggle (Automation tab) or a cron of `auto_analyze.sh`. Note:
unattended 24/7 use should fit your Max plan's usage limits. The dashboard works fully without
this — you just won't get fresh AI debates until Claude Code is logged in.

## Updating later
```bash
cd ~/FinalBot && bash deploy/update.sh    # git pull + rebuild + restart
```

## Security notes (read these)
- **Port 443 is locked to `ALLOW_IP`.** If your home IP changes, update it:
  `sudo ufw allow from NEW_IP to any port 443 proto tcp` (and remove the old rule with
  `sudo ufw status numbered` + `sudo ufw delete <n>`).
- The dashboard can **place trades and switch to live**. Use a strong password, keep `ALLOW_IP`
  set, and keep `.env` readable only by your user (`chmod 600 .env`).
- Renewals: certbot auto-renews via port 80 (kept open); nothing to do.

## Troubleshooting
- Backend logs: `journalctl -u finalbot -f`
- nginx test: `sudo nginx -t`
- certbot retry: `sudo certbot --nginx -d bot.yourdomain.com --redirect`
- Is the API up? `curl -s localhost:8000/api/health`
