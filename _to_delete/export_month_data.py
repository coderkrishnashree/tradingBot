#!/usr/bin/env python3
"""
export_month_data.py — bundle ~35 days of FinalBot data for offline analysis.

RUN ON THE SERVER, from the project root, with the venv python:

    cd /opt/finalbot && sudo -u finalbot .venv/bin/python export_month_data.py

(Running locally on your Mac against a copy of the repo works too, but the
server has the real trading.db, decisions/ and log files.)

What it collects (last --days days, default 35):
  db/            orders, equity_curve, decisions_log, trade_features, alerts,
                 trading_config + latest_scan  (from data/trading.db, read-only)
  bybit/         closed-PnL and execution/fee records pulled DIRECTLY from
                 Bybit in explicit 7-day windows — the dashboard's own fetch
                 uses Bybit's default window (~7 days), so this is the only
                 way to get the full month of realized trades
  decisions/     every decision/transcript file from the window
                 + _learner_stats.json + _debate_targets.json
  logs/          tail of data/ai_debate.log
  meta.json      export info, mode/key availability (booleans only)

Contains NO API keys or secrets. Output: data/finalbot_export_<ts>.tar.gz
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

ERRORS: list[str] = []


def note_err(section: str, e: Exception | str):
    msg = f"{section}: {e}"
    ERRORS.append(msg)
    print(f"  [warn] {msg}")


# --------------------------------------------------------------------------
# Config / env
# --------------------------------------------------------------------------

def load_env() -> dict:
    """Prefer backend.config (same logic the bot uses); fall back to .env."""
    try:
        from backend import config as bot_config  # noqa
        return {
            "demo": bot_config.demo_keys(),
            "mainnet": bot_config.mainnet_keys(),
            "testnet": bot_config.testnet_keys(),
            "paper_backend": bot_config.paper_backend(),
            "db_path": bot_config.DB_PATH,
            "decisions_dir": str(bot_config.DECISIONS_DIR),
        }
    except Exception as e:
        note_err("backend.config import (falling back to .env parse)", e)
        env: dict[str, str] = dict(os.environ)
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        return {
            "demo": (env.get("BYBIT_DEMO_KEY", ""), env.get("BYBIT_DEMO_SECRET", "")),
            "mainnet": (env.get("BYBIT_MAINNET_KEY", ""), env.get("BYBIT_MAINNET_SECRET", "")),
            "testnet": (env.get("BYBIT_TESTNET_KEY", ""), env.get("BYBIT_TESTNET_SECRET", "")),
            "paper_backend": env.get("BYBIT_PAPER_BACKEND", "testnet").lower(),
            "db_path": env.get("DB_PATH", str(ROOT / "data" / "trading.db")),
            "decisions_dir": str(ROOT / "decisions"),
        }


# --------------------------------------------------------------------------
# SQLite dump (read-only so the live service is never touched)
# --------------------------------------------------------------------------

def dump_db(db_path: str, out: Path, cutoff_iso: str):
    d = out / "db"
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            "orders": "SELECT * FROM orders WHERE ts >= ? ORDER BY id",
            "equity_curve": "SELECT * FROM equity_curve WHERE ts >= ? ORDER BY id",
            "decisions_log": "SELECT * FROM decisions_log WHERE ts >= ? ORDER BY id",
            "trade_features": "SELECT * FROM trade_features WHERE ts >= ? ORDER BY id",
            "alerts": "SELECT * FROM alerts WHERE ts >= ? ORDER BY id",
        }
        for name, q in tables.items():
            try:
                rows = [dict(r) for r in conn.execute(q, (cutoff_iso,)).fetchall()]
                (d / f"{name}.json").write_text(json.dumps(rows, indent=1, default=str))
                print(f"  db/{name}.json: {len(rows)} rows")
            except Exception as e:
                note_err(f"db table {name}", e)
        for key in ("trading_config", "latest_scan"):
            try:
                row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                if row:
                    (d / f"{key}.json").write_text(row["value"])
                    print(f"  db/{key}.json: ok")
            except Exception as e:
                note_err(f"settings {key}", e)
        # ALL settings keys (names only + small values, so gate_exception:* etc. show up)
        try:
            small = {}
            for r in conn.execute("SELECT key, value FROM settings"):
                if r["key"] in ("trading_config", "latest_scan"):
                    continue
                v = r["value"]
                small[r["key"]] = v if len(v) <= 2000 else f"<{len(v)} bytes>"
            (d / "settings_other.json").write_text(json.dumps(small, indent=1))
        except Exception as e:
            note_err("settings misc", e)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Bybit: full-window closed PnL + executions (7-day chunks, cursor paginated)
# --------------------------------------------------------------------------

def build_client(env_name: str, keys: tuple[str, str]):
    import ccxt
    client = ccxt.bybit({
        "apiKey": keys[0], "secret": keys[1],
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    if env_name == "demo":
        client.enable_demo_trading(True)
    elif env_name == "testnet":
        client.set_sandbox_mode(True)
    return client


def paged_window_fetch(client, path: str, days: int, extra: dict) -> list[dict]:
    """Fetch a v5 list endpoint over the last `days` days in <=6-day windows
    (Bybit caps most windows at 7 days), following nextPageCursor."""
    fetch = getattr(client, path)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days * 86400_000
    out, seen = [], set()
    win = 6 * 86400_000
    t0 = start_ms
    while t0 < now_ms:
        t1 = min(t0 + win, now_ms)
        cursor = None
        for _ in range(20):
            params = {"category": "linear", "limit": 100,
                      "startTime": t0, "endTime": t1, **extra}
            if cursor:
                params["cursor"] = cursor
            resp = fetch(params)
            res = resp.get("result", {}) or {}
            items = res.get("list", []) or []
            for it in items:
                key = json.dumps(it, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    out.append(it)
            cursor = res.get("nextPageCursor")
            if not cursor:
                break
        t0 = t1
    return out


def dump_bybit(envs: dict, out: Path, days: int):
    d = out / "bybit"
    d.mkdir(parents=True, exist_ok=True)
    for env_name in ("demo", "mainnet", "testnet"):
        keys = envs.get(env_name) or ("", "")
        if not (keys[0] and keys[1]):
            continue
        print(f"  bybit[{env_name}]: fetching…")
        try:
            client = build_client(env_name, keys)
            closed = paged_window_fetch(
                client, "private_get_v5_position_closed_pnl", days, {})
            (d / f"{env_name}_closed_pnl.json").write_text(json.dumps(closed, indent=1))
            print(f"    closed_pnl: {len(closed)} records")
            try:
                execs = paged_window_fetch(
                    client, "private_get_v5_execution_list", days, {})
                (d / f"{env_name}_executions.json").write_text(json.dumps(execs, indent=1))
                print(f"    executions: {len(execs)} fills (fees/slippage)")
            except Exception as e:
                note_err(f"bybit {env_name} executions", e)
            try:
                bal = client.fetch_balance()
                slim = {"total": bal.get("total"), "free": bal.get("free"),
                        "used": bal.get("used")}
                (d / f"{env_name}_balance.json").write_text(json.dumps(slim, indent=1, default=str))
            except Exception as e:
                note_err(f"bybit {env_name} balance", e)
            try:
                pos = [p for p in client.fetch_positions() if p.get("contracts")]
                (d / f"{env_name}_open_positions.json").write_text(
                    json.dumps(pos, indent=1, default=str))
                print(f"    open positions: {len(pos)}")
            except Exception as e:
                note_err(f"bybit {env_name} positions", e)
        except Exception as e:
            note_err(f"bybit {env_name}", e)


# --------------------------------------------------------------------------
# Decisions + logs
# --------------------------------------------------------------------------

def dump_decisions(decisions_dir: str, out: Path, cutoff_ts: float):
    src = Path(decisions_dir)
    if not src.exists():
        note_err("decisions dir", f"{src} missing")
        return
    d = out / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(src.iterdir()):
        if not f.is_file():
            continue
        always = f.name in ("_learner_stats.json", "_debate_targets.json")
        try:
            if not always and f.stat().st_mtime < cutoff_ts:
                continue
            if f.stat().st_size > 1_000_000:  # skip anything absurdly large
                continue
            shutil.copy2(f, d / f.name)
            n += 1
        except Exception as e:
            note_err(f"decision file {f.name}", e)
    print(f"  decisions/: {n} files")


def dump_logs(out: Path, lines: int = 5000):
    d = out / "logs"
    d.mkdir(parents=True, exist_ok=True)
    log = ROOT / "data" / "ai_debate.log"
    if log.exists():
        try:
            content = log.read_text(errors="replace").splitlines()[-lines:]
            (d / "ai_debate_tail.log").write_text("\n".join(content))
            print(f"  logs/ai_debate_tail.log: last {min(lines, len(content))} lines")
        except Exception as e:
            note_err("ai_debate.log", e)


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=35)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    out = ROOT / "data" / f"export_{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    envs = load_env()
    print(f"Exporting last {args.days} days -> {out}")

    print("[1/4] database")
    try:
        dump_db(envs["db_path"], out, cutoff.isoformat())
    except Exception as e:
        note_err("db", e)

    print("[2/4] bybit history (full window, 7-day chunks)")
    dump_bybit(envs, out, args.days)

    print("[3/4] decisions")
    dump_decisions(envs["decisions_dir"], out, cutoff.timestamp())

    print("[4/4] logs")
    dump_logs(out)

    meta = {
        "exported_at": now.isoformat(),
        "days": args.days,
        "paper_backend": envs.get("paper_backend"),
        "keys_present": {k: bool(envs.get(k, ("", ""))[0]) for k in ("demo", "mainnet", "testnet")},
        "errors": ERRORS,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1))

    tar_path = ROOT / "data" / f"finalbot_export_{stamp}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(out, arcname=out.name)
    shutil.rmtree(out, ignore_errors=True)

    size_mb = tar_path.stat().st_size / 1e6
    print(f"\nDone: {tar_path}  ({size_mb:.1f} MB)")
    if ERRORS:
        print(f"{len(ERRORS)} warnings (recorded in meta.json) — export still usable.")
    print("\nCopy it to your Mac (run from your Mac):")
    print(f"  scp <user>@<droplet-ip>:{tar_path} ~/Documents/Projects/FinalBot/")


if __name__ == "__main__":
    main()
