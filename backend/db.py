"""
db.py
=====
SQLite persistence. Plain stdlib sqlite3 — no ORM, so the schema is easy to
read and modify. Four tables:

  orders          every order we submit + its fill info
  equity_curve    periodic snapshots of total equity (for the curve + drawdown)
  settings        the editable trading config (one row, key/value JSON)
  decisions_log   index of decision JSON files written by Layer 1

The raw debate transcripts + full decision JSON live as files in /decisions/;
this table just indexes them so the UI can list them quickly.
"""

from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create tables if missing and seed default settings. Idempotent."""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            TEXT NOT NULL,
                mode          TEXT NOT NULL,          -- paper | live
                symbol        TEXT NOT NULL,
                side          TEXT NOT NULL,          -- buy | sell
                order_type    TEXT NOT NULL,          -- market | limit
                qty           REAL NOT NULL,
                price         REAL,
                status        TEXT NOT NULL,          -- submitted | filled | rejected | canceled
                filled_qty    REAL DEFAULT 0,
                avg_fill_price REAL,
                pnl           REAL,                   -- realized pnl when known
                exchange_id   TEXT,                   -- ccxt order id
                decision_file TEXT,                   -- which decision triggered it
                raw           TEXT                    -- full ccxt response JSON
            );

            CREATE TABLE IF NOT EXISTS equity_curve (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                mode      TEXT NOT NULL,
                equity    REAL NOT NULL,
                cash      REAL,
                unrealized REAL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decisions_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                filename  TEXT NOT NULL UNIQUE,
                action    TEXT,
                symbol    TEXT,
                confidence REAL,
                status    TEXT DEFAULT 'pending'      -- pending | approved | rejected | executed
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      TEXT NOT NULL,
                level   TEXT NOT NULL,                 -- info | success | warning | danger
                kind    TEXT,                          -- scan | auto_trade | kill | drawdown | system
                symbol  TEXT,
                message TEXT NOT NULL
            );
            """
        )
        # Seed trading config if absent.
        cur = conn.execute("SELECT value FROM settings WHERE key='trading_config'")
        if cur.fetchone() is None:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("trading_config", json.dumps(config.DEFAULT_TRADING_CONFIG)),
            )


# --- settings ---------------------------------------------------------------

def get_trading_config() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='trading_config'").fetchone()
        return json.loads(row["value"]) if row else dict(config.DEFAULT_TRADING_CONFIG)


def save_trading_config(cfg: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('trading_config', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(cfg),),
        )


# --- latest scan (stored as JSON in settings) -------------------------------

def save_latest_scan(scan: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('latest_scan', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(scan),),
        )


def get_latest_scan() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='latest_scan'").fetchone()
        return json.loads(row["value"]) if row else None


# --- alerts -----------------------------------------------------------------

def add_alert(level: str, kind: str, message: str, symbol: str | None = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts (ts, level, kind, symbol, message) VALUES (?,?,?,?,?)",
            (_now(), level, kind, symbol, message),
        )


def list_alerts(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# --- orders -----------------------------------------------------------------

def record_order(**fields) -> int:
    fields.setdefault("ts", _now())
    cols = ", ".join(fields.keys())
    qs = ", ".join("?" for _ in fields)
    with get_conn() as conn:
        cur = conn.execute(f"INSERT INTO orders ({cols}) VALUES ({qs})", tuple(fields.values()))
        return cur.lastrowid


def last_order_ts(symbol: str) -> str | None:
    """ISO timestamp of the most recent order on a symbol (for trade cooldown)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT ts FROM orders WHERE symbol=? ORDER BY id DESC LIMIT 1", (symbol,)
        ).fetchone()
        return row["ts"] if row else None


def list_orders(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# --- equity curve -----------------------------------------------------------

def record_equity(equity: float, cash: float | None, unrealized: float | None, mode: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO equity_curve (ts, mode, equity, cash, unrealized) VALUES (?,?,?,?,?)",
            (_now(), mode, equity, cash, unrealized),
        )


def list_equity(limit: int = 1000, mode: str | None = None) -> list[dict]:
    """Equity snapshots. Pass mode='paper'|'live' to keep the two environments'
    histories separate (so switching mode never shows a fake drawdown)."""
    with get_conn() as conn:
        if mode:
            rows = conn.execute(
                "SELECT ts, equity, cash, unrealized, mode FROM equity_curve "
                "WHERE mode=? ORDER BY id ASC LIMIT ?", (mode, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ts, equity, cash, unrealized, mode FROM equity_curve "
                "ORDER BY id ASC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


# --- decisions index --------------------------------------------------------

def index_decision(filename: str, action: str | None, symbol: str | None,
                   confidence: float | None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO decisions_log (ts, filename, action, symbol, confidence) "
            "VALUES (?,?,?,?,?)",
            (_now(), filename, action, symbol, confidence),
        )
        return cur.lastrowid


def list_decisions(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def set_decision_status(filename: str, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE decisions_log SET status=? WHERE filename=?", (status, filename)
        )
