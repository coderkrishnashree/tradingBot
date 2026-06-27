"""
scheduler.py
============
The always-on background loop (plain Python thread, NO Claude tokens).

Every `scan_interval_min` it:
  1. Runs the multi-timeframe screener (scanner.scan) over all pairs.
  2. If `auto_trade` is ON, executes any pair whose composite confidence >=
     `auto_trade_confidence` (and direction is long/short), in the ACTIVE mode,
     subject to the same safety preflight (kill switch + drawdown) as manual
     trades, and only if there's no open position on that symbol already.
  3. Also auto-executes the latest AI debate decision if it qualifies (the "AI
     overlay") — so a /analyze decision above threshold trades hands-free too.
  4. Logs everything to the alerts feed.

IMPORTANT: this loop is MECHANICAL only. It never invokes the AI agents — that
would require a headless/API path, which is exactly what we avoid. The AI runs
only when you type /analyze in Claude Code; this loop merely *acts on* a decision
file the AI already wrote.
"""

from __future__ import annotations
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

from . import db, scanner, engine, exchange, decisions_io
from .config import mode_manager, PROJECT_ROOT


def _claude_bin() -> str | None:
    """Find the Claude Code CLI. cron-less: we run it from the backend process."""
    found = shutil.which("claude")
    if found:
        return found
    for p in (os.path.expanduser("~/.npm-global/bin/claude"),
              "/usr/local/bin/claude", "/opt/homebrew/bin/claude"):
        if os.path.exists(p):
            return p
    return None


class Scheduler:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_run: str | None = None
        self.next_run_epoch: float | None = None
        self.last_summary: dict | None = None
        self._ai_running = False     # guard against overlapping claude runs
        self._cycle_running = False  # True while a scan cycle is executing
        self.ai_available = _claude_bin() is not None

    # --- lifecycle ----------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scanner-loop")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def status(self) -> dict:
        cfg = db.get_trading_config()
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "scan_enabled": cfg.get("scan_enabled", True),
            "auto_trade": cfg.get("auto_trade", False),
            "auto_trade_confidence": cfg.get("auto_trade_confidence", 65),
            "daily_loss_limit_pct": cfg.get("daily_loss_limit_pct", 0),
            "min_minutes_between_trades": cfg.get("min_minutes_between_trades", 0),
            "auto_analyze": cfg.get("auto_analyze", False),
            "ai_available": _claude_bin() is not None,  # re-check live (no restart needed)
            "ai_running": self._ai_running,
            "cycle_running": self._cycle_running,
            "scan_interval_min": cfg.get("scan_interval_min", 30),
            "scan_timeframes": cfg.get("scan_timeframes", []),
            "last_run": self.last_run,
            "seconds_to_next": max(0, int(self.next_run_epoch - time.time())) if self.next_run_epoch else None,
            "last_summary": self.last_summary,
            "mode": mode_manager.mode,
        }

    # --- main loop ----------------------------------------------------------
    def _loop(self):
        # First run shortly after boot so the dashboard has data quickly.
        self._schedule_next(5)
        while not self._stop.is_set():
            if self.next_run_epoch and time.time() >= self.next_run_epoch:
                # Schedule the NEXT run BEFORE running this one, so the countdown
                # reflects the real cadence even if this cycle takes a while.
                cfg = db.get_trading_config()
                self._schedule_next(int(cfg.get("scan_interval_min", 30)) * 60)
                try:
                    self.run_once()
                except Exception as e:
                    db.add_alert("danger", "system", f"Scan loop error: {e}")
            self._stop.wait(2)  # check stop flag / time every 2s

    def _schedule_next(self, seconds: float):
        self.next_run_epoch = time.time() + seconds

    # --- one cycle ----------------------------------------------------------
    def run_once(self) -> dict:
        cfg = db.get_trading_config()
        self.last_run = datetime.now(timezone.utc).isoformat()
        self._cycle_running = True
        try:
            if not cfg.get("scan_enabled", True):
                self.last_summary = {"skipped": "scanning disabled"}
                return self.last_summary

            result = scanner.scan()
            rows = result.get("rows", [])
            db.add_alert("info", "scan",
                         f"Scan complete: {len(rows)} pairs ({result.get('data_source')}).")

            summary = {"scanned": len(rows), "traded": [], "skipped": []}

            # "Cron from the dashboard": run the AI debate headlessly — but in a
            # BACKGROUND thread so a slow/hanging claude run never freezes the scan
            # loop. The resulting decision is picked up by a later cycle's overlay.
            if cfg.get("auto_analyze", False) and not self._ai_running:
                threading.Thread(target=self.run_ai_analyze, daemon=True,
                                 name="auto-analyze").start()

            if cfg.get("auto_trade", False):
                threshold = float(cfg.get("auto_trade_confidence", 65))
                summary.update(self._auto_trade(rows, threshold, cfg))
                summary.update(self._auto_trade_ai(threshold, cfg))
            self.last_summary = summary
            return summary
        finally:
            self._cycle_running = False

    def run_ai_analyze(self, timeout: int = 420) -> dict:
        """Run the multi-agent debate HEADLESSLY via Claude Code (claude -p).

        Uses your subscription login (NOT an API key). This is the dashboard's
        version of a cron — it's the headless AI loop the project originally
        avoided, enabled here only because you asked for it. Blocks until the
        debate finishes (or times out); the resulting decision is then handled
        by the auto-trade step / AI overlay.
        """
        if self._ai_running:
            return {"ok": False, "message": "An AI analysis is already running."}
        binp = _claude_bin()
        if not binp:
            db.add_alert("danger", "system",
                         "Auto-analyze: `claude` not found. Install Claude Code + /login first.")
            return {"ok": False, "message": "claude CLI not found"}

        self._ai_running = True
        db.add_alert("info", "system", "Auto-analyze: running /analyze headlessly (subscription)…")
        try:
            proc = subprocess.run(
                [binp, "-p", "/analyze", "--dangerously-skip-permissions"],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=timeout,
            )
            if proc.returncode == 0:
                db.add_alert("success", "system", "Auto-analyze: debate complete; decision written.")
                return {"ok": True, "message": "analyze complete"}
            err = (proc.stderr or proc.stdout or "")[-200:]
            db.add_alert("warning", "system", f"Auto-analyze failed (rc={proc.returncode}): {err}")
            return {"ok": False, "message": f"claude rc={proc.returncode}"}
        except subprocess.TimeoutExpired:
            db.add_alert("warning", "system", f"Auto-analyze timed out after {timeout}s.")
            return {"ok": False, "message": "timeout"}
        except Exception as e:
            db.add_alert("danger", "system", f"Auto-analyze error: {e}")
            return {"ok": False, "message": str(e)}
        finally:
            self._ai_running = False

    def _open_symbols(self) -> set[str]:
        try:
            return {p.get("symbol") for p in exchange.fetch_positions()}
        except Exception:
            return set()

    def _auto_trade(self, rows, threshold, cfg) -> dict:
        traded, skipped = [], []
        open_syms = self._open_symbols()
        for r in rows:
            comp = r["composite"]
            sym = r["symbol"]
            if comp["confidence_pct"] < threshold or comp["direction"] == "flat":
                continue
            if sym in open_syms:
                skipped.append(f"{sym}: already open")
                continue
            cd = engine.cooldown_remaining(sym)
            if cd > 0:
                skipped.append(f"{sym}: cooldown {cd}m")
                continue
            decision = self._row_to_decision(r, comp, cfg)
            res = engine.execute_decision(decision)
            if res["ok"]:
                traded.append(sym)
                db.add_alert("success", "auto_trade",
                             f"AUTO {comp['direction'].upper()} {sym} @ conf {comp['confidence_pct']}% — {res['message']}",
                             symbol=sym)
            else:
                skipped.append(f"{sym}: {res['message']}")
                db.add_alert("warning", "auto_trade",
                             f"Skipped {sym} (conf {comp['confidence_pct']}%): {res['message']}",
                             symbol=sym)
        return {"traded": traded, "skipped": skipped}

    def _auto_trade_ai(self, threshold, cfg) -> dict:
        """AI overlay: auto-execute the latest AI decision if it qualifies."""
        d = decisions_io.latest_decision()
        if not d:
            return {}
        fn = d.get("_filename")
        # Only act on a still-pending decision.
        logged = {x["filename"]: x for x in db.list_decisions(200)}
        if fn in logged and logged[fn]["status"] in ("executed", "rejected"):
            return {}
        conf_pct = float(d.get("confidence") or 0) * 100
        if conf_pct < threshold or (d.get("action") or "").lower() == "hold":
            return {}
        if d.get("symbol") in self._open_symbols():
            return {}
        res = engine.execute_decision(d, decision_file=fn)
        if res["ok"]:
            db.add_alert("success", "auto_trade",
                         f"AUTO (AI) {d.get('action','').upper()} {d.get('symbol')} "
                         f"@ conf {round(conf_pct)}% — {res['message']}", symbol=d.get("symbol"))
            return {"ai_traded": d.get("symbol")}
        return {"ai_skipped": res["message"]}

    def _row_to_decision(self, row, comp, cfg) -> dict:
        """Build an executable decision from a mechanical scan row."""
        last = row["last"]
        sl = float(cfg.get("stop_loss_pct", 2))
        tp = float(cfg.get("take_profit_pct", 4))
        long = comp["direction"] == "long"
        return {
            "action": "buy" if long else "short",
            "symbol": row["symbol"],
            "size": float(cfg.get("position_size_pct", 5)),
            "entry": last,
            "stop_loss": round(last * (1 - sl / 100) if long else last * (1 + sl / 100), 6),
            "take_profit": round(last * (1 + tp / 100) if long else last * (1 - tp / 100), 6),
            "confidence": comp["confidence_pct"] / 100,
            "rationale": f"Mechanical screener: {comp['confidence_pct']}% {comp['direction']} "
                         f"(aligned={comp['aligned']}) across {len(row['per_tf'])} timeframes.",
            "source": "screener",
        }


# Shared instance.
scheduler = Scheduler()
