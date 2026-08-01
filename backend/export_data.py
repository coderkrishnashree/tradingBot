"""
export_data.py
==============
Build a downloadable analysis bundle (tar.gz) for a custom date range.
Served by GET /api/export?start=YYYY-MM-DD&end=YYYY-MM-DD (see main.py) so the
whole thing downloads straight through the browser — nothing to scp.

What goes in:
  db/          orders, equity_curve, decisions_log, trade_features, alerts,
               trading_config + latest_scan (from trading.db, read-only)
  bybit/       closed-PnL + execution/fee records pulled DIRECTLY from Bybit
               in explicit <=7-day windows for every env with keys (demo /
               mainnet / testnet). NOTE: without explicit startTime Bybit's
               closed-pnl endpoint only returns ~the last 7 days — which is
               also why the dashboard's realized numbers under-report.
  decisions/   decision/transcript files whose mtime falls in the range
               + _learner_stats.json + _debate_targets.json
  logs/        tail of data/ai_debate.log
  meta.json    range, key availability (booleans only), warnings

Contains NO API keys or secrets.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

_DAY_MS = 86_400_000


def _parse_range(start: str, end: str) -> tuple[datetime, datetime]:
    """YYYY-MM-DD strings (UTC) -> [start 00:00, end 23:59:59]. Defaults:
    end = today, start = end - 35 days."""
    now = datetime.now(timezone.utc)
    try:
        end_dt = (datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
                  if end else now)
    except Exception:
        raise ValueError(f"Bad end date: {end!r} (use YYYY-MM-DD)")
    try:
        start_dt = (datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
                    if start else end_dt - timedelta(days=35))
    except Exception:
        raise ValueError(f"Bad start date: {start!r} (use YYYY-MM-DD)")
    start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = min(end_dt.replace(hour=23, minute=59, second=59, microsecond=0), now)
    if start_dt >= end_dt:
        raise ValueError("start must be before end")
    if (end_dt - start_dt).days > 370:
        raise ValueError("Range too large (max ~1 year)")
    return start_dt, end_dt


# --------------------------------------------------------------------------
# SQLite (read-only — never touches the live service's writes)
# --------------------------------------------------------------------------

def _dump_db(out: Path, start_iso: str, end_iso: str, errors: list[str]):
    d = out / "db"
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for name in ("orders", "equity_curve", "decisions_log", "trade_features", "alerts"):
            try:
                rows = [dict(r) for r in conn.execute(
                    f"SELECT * FROM {name} WHERE ts >= ? AND ts <= ? ORDER BY id",
                    (start_iso, end_iso)).fetchall()]
                (d / f"{name}.json").write_text(json.dumps(rows, indent=1, default=str))
            except Exception as e:
                errors.append(f"db {name}: {e}")
        for key in ("trading_config", "latest_scan"):
            try:
                row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                if row:
                    (d / f"{key}.json").write_text(row["value"])
            except Exception as e:
                errors.append(f"settings {key}: {e}")
        try:
            small = {r["key"]: (r["value"] if len(r["value"]) <= 2000 else f"<{len(r['value'])} bytes>")
                     for r in conn.execute("SELECT key, value FROM settings")
                     if r["key"] not in ("trading_config", "latest_scan")}
            (d / "settings_other.json").write_text(json.dumps(small, indent=1))
        except Exception as e:
            errors.append(f"settings misc: {e}")
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Bybit history in explicit <=7-day windows (cursor paginated)
# --------------------------------------------------------------------------

def _build_client(env_name: str, keys: tuple[str, str]):
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


def _paged_window_fetch(client, path: str, start_ms: int, end_ms: int) -> list[dict]:
    fetch = getattr(client, path)
    out, seen = [], set()
    win = 6 * _DAY_MS                      # Bybit caps most windows at 7 days
    t0 = start_ms
    while t0 < end_ms:
        t1 = min(t0 + win, end_ms)
        cursor = None
        for _ in range(20):
            params = {"category": "linear", "limit": 100,
                      "startTime": t0, "endTime": t1}
            if cursor:
                params["cursor"] = cursor
            resp = fetch(params)
            res = resp.get("result", {}) or {}
            for it in res.get("list", []) or []:
                key = json.dumps(it, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    out.append(it)
            cursor = res.get("nextPageCursor")
            if not cursor:
                break
        t0 = t1
    return out


def _dump_bybit(out: Path, start_ms: int, end_ms: int, errors: list[str]) -> dict:
    d = out / "bybit"
    d.mkdir(parents=True, exist_ok=True)
    envs = {
        "demo": config.demo_keys(),
        "mainnet": config.mainnet_keys(),
        "testnet": config.testnet_keys(),
    }
    keys_present = {}
    for env_name, keys in envs.items():
        keys_present[env_name] = bool(keys[0] and keys[1])
        if not keys_present[env_name]:
            continue
        try:
            client = _build_client(env_name, keys)
            closed = _paged_window_fetch(
                client, "private_get_v5_position_closed_pnl", start_ms, end_ms)
            (d / f"{env_name}_closed_pnl.json").write_text(json.dumps(closed, indent=1))
            try:
                execs = _paged_window_fetch(
                    client, "private_get_v5_execution_list", start_ms, end_ms)
                (d / f"{env_name}_executions.json").write_text(json.dumps(execs, indent=1))
            except Exception as e:
                errors.append(f"bybit {env_name} executions: {e}")
            try:
                bal = client.fetch_balance()
                (d / f"{env_name}_balance.json").write_text(json.dumps(
                    {"total": bal.get("total"), "free": bal.get("free"),
                     "used": bal.get("used")}, indent=1, default=str))
            except Exception as e:
                errors.append(f"bybit {env_name} balance: {e}")
            try:
                pos = [p for p in client.fetch_positions() if p.get("contracts")]
                (d / f"{env_name}_open_positions.json").write_text(
                    json.dumps(pos, indent=1, default=str))
            except Exception as e:
                errors.append(f"bybit {env_name} positions: {e}")
        except Exception as e:
            errors.append(f"bybit {env_name}: {e}")
    return keys_present


# --------------------------------------------------------------------------

def _dump_decisions(out: Path, start_ts: float, end_ts: float, errors: list[str]):
    src = config.DECISIONS_DIR
    d = out / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    if not Path(src).exists():
        errors.append(f"decisions dir missing: {src}")
        return
    for f in sorted(Path(src).iterdir()):
        if not f.is_file():
            continue
        always = f.name in ("_learner_stats.json", "_debate_targets.json")
        try:
            mt = f.stat().st_mtime
            if not always and not (start_ts <= mt <= end_ts + 86400):
                continue
            if f.stat().st_size > 1_000_000:
                continue
            shutil.copy2(f, d / f.name)
        except Exception as e:
            errors.append(f"decision {f.name}: {e}")


def _dump_logs(out: Path, errors: list[str], lines: int = 5000):
    d = out / "logs"
    d.mkdir(parents=True, exist_ok=True)
    log = Path(config.DB_PATH).parent / "ai_debate.log"
    if log.exists():
        try:
            content = log.read_text(errors="replace").splitlines()[-lines:]
            (d / "ai_debate_tail.log").write_text("\n".join(content))
        except Exception as e:
            errors.append(f"ai_debate.log: {e}")


# --------------------------------------------------------------------------

def build_export(start: str = "", end: str = "") -> Path:
    """Build the bundle and return the tar.gz path. Raises ValueError on a bad
    range. The caller (the /api/export route) deletes the file after sending."""
    start_dt, end_dt = _parse_range(start, end)
    errors: list[str] = []

    stamp = f"{start_dt:%Y%m%d}_{end_dt:%Y%m%d}"
    exports_dir = Path(config.DB_PATH).parent / "exports"
    staging = exports_dir / f"export_{stamp}_{int(time.time())}"
    staging.mkdir(parents=True, exist_ok=True)

    try:
        _dump_db(staging, start_dt.isoformat(), end_dt.isoformat(), errors)
        keys_present = _dump_bybit(
            staging, int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000), errors)
        _dump_decisions(staging, start_dt.timestamp(), end_dt.timestamp(), errors)
        _dump_logs(staging, errors)

        (staging / "meta.json").write_text(json.dumps({
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "range": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
            "paper_backend": config.paper_backend(),
            "keys_present": keys_present,
            "errors": errors,
        }, indent=1))

        tar_path = exports_dir / f"finalbot_export_{stamp}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(staging, arcname=f"finalbot_export_{stamp}")
        return tar_path
    finally:
        shutil.rmtree(staging, ignore_errors=True)
