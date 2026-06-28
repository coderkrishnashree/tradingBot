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


AI_LOG_PATH = PROJECT_ROOT / "data" / "ai_debate.log"


def _tail(path, n=6) -> str:
    try:
        return "\n".join(path.read_text().splitlines()[-n:])[-400:]
    except Exception:
        return ""


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
            "ai_gated": cfg.get("ai_gated", False),
            "ai_lite": cfg.get("ai_lite", True),
            "ai_timeout_sec": cfg.get("ai_timeout_sec", 1200),
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
            ai_gated = cfg.get("ai_gated", False)
            threshold = float(cfg.get("auto_trade_confidence", 65))

            # "Cron from the dashboard": when NOT gated, optionally run the AI in a
            # background thread so a slow run never freezes the loop. When gated,
            # the AI is run synchronously below (it IS the decision step).
            if cfg.get("auto_analyze", False) and not ai_gated and not self._ai_running:
                threading.Thread(target=self.run_ai_analyze, daemon=True,
                                 name="auto-analyze").start()

            if cfg.get("auto_trade", False):
                if ai_gated:
                    summary.update(self._ai_gated_cycle(rows, threshold, cfg))
                else:
                    summary.update(self._auto_trade(rows, threshold, cfg))
                    summary.update(self._auto_trade_ai(threshold, cfg))
            self.last_summary = summary
            return summary
        finally:
            self._cycle_running = False

    def run_ai_analyze(self, timeout: int | None = None, symbols: list | None = None) -> dict:
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

        if timeout is None:
            timeout = int(db.get_trading_config().get("ai_timeout_sec", 1200))
        from datetime import datetime, timezone
        AI_LOG_PATH.parent.mkdir(exist_ok=True)
        self._ai_running = True
        db.add_alert("info", "system",
                     f"Auto-analyze: running /analyze headlessly… up to {timeout//60} min "
                     f"(watch it in the Debates tab → Live AI).")
        try:
            # Stream Claude's output to a log file the dashboard tails live.
            # --verbose makes it emit step-by-step progress as it runs.
            with open(AI_LOG_PATH, "w") as lf:
                lf.write(f"=== /analyze started {datetime.now(timezone.utc).isoformat()} ===\n")
                lf.flush()
                # LITE = fast desk-analyst; FULL = 8-agent debate on the best pair.
                # In lite mode, if specific symbols are passed (the gated candidates)
                # we debate ONLY those — no wasted calls on pairs that didn't qualify.
                if db.get_trading_config().get("ai_lite", True):
                    command = "/analyze-lite" + ((" " + " ".join(symbols)) if symbols else "")
                else:
                    command = "/analyze"
                proc = subprocess.run(
                    [binp, "-p", command, "--output-format", "stream-json", "--verbose",
                     "--dangerously-skip-permissions"],
                    cwd=str(PROJECT_ROOT), stdout=lf, stderr=subprocess.STDOUT,
                    text=True, timeout=timeout,
                )
            if proc.returncode == 0:
                db.add_alert("success", "system", "Auto-analyze: debate complete; decision written.")
                return {"ok": True, "message": "analyze complete"}
            db.add_alert("warning", "system",
                         f"Auto-analyze failed (rc={proc.returncode}): {_tail(AI_LOG_PATH, 4)}")
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

    def _ai_gated_cycle(self, rows, threshold, cfg) -> dict:
        """AI-GATED: the screener only pre-filters; the AGENTS decide + trade.

        1. Find mechanical candidates >= threshold (not already open / on cooldown).
        2. If any, run the AI debate (synchronous — this is the gate).
        3. Execute ONLY the AI's resulting decision, and only if the AI's own
           confidence clears the threshold. No mechanical-only trades happen here.
        """
        open_syms = self._open_symbols()
        cands = [r for r in rows
                 if r["composite"]["confidence_pct"] >= threshold
                 and r["composite"]["direction"] != "flat"
                 and r["symbol"] not in open_syms
                 and engine.cooldown_remaining(r["symbol"]) <= 0]
        if not cands:
            best = max(rows, key=lambda r: r["composite"]["confidence_pct"], default=None)
            if best and best["composite"]["confidence_pct"] >= threshold:
                sym, c = best["symbol"], best["composite"]
                if c["direction"] == "flat":
                    why = "direction is flat"
                elif sym in open_syms:
                    why = "you already hold a position in it"
                elif engine.cooldown_remaining(sym) > 0:
                    why = f"it's in a {engine.cooldown_remaining(sym)}m cooldown"
                else:
                    why = "it was excluded"
                msg = (f"AI-gated: top pair {sym} is {round(c['confidence_pct'])}% (≥ {round(threshold)}%) "
                       f"but {why} — no new debate.")
            else:
                bv = round(best['composite']['confidence_pct']) if best else 0
                msg = (f"AI-gated: no pair ≥ {round(threshold)}% this cycle (best was {bv}%) — "
                       f"no debate. The anti-chase scoring is finding nothing fresh.")
            db.add_alert("info", "system", msg)
            return {"ai_gated": "no tradeable candidate"}
        if _claude_bin() is None:
            db.add_alert("warning", "system",
                         "AI-gated: candidate found but Claude CLI not available — NO trade "
                         "(this is the gate working). Set up Claude Code to enable.")
            return {"ai_gated": "claude unavailable — gated, no trade"}

        cand_syms = [c["symbol"] for c in cands]
        top = ", ".join(f"{c['symbol']}({c['composite']['confidence_pct']}%)" for c in cands[:3])
        db.add_alert("info", "system",
                     f"AI-gated: {len(cands)} candidate(s) [{top}] — debating only these…")
        self.run_ai_analyze(symbols=cand_syms)     # debate ONLY the qualifying pairs
        res = self._auto_trade_ai(threshold, cfg)  # execute the AI's call if it qualifies
        return {"ai_gated": "debate complete", **res}

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

    def _scanner_conf(self, sym) -> float | None:
        """Latest mechanical scanner confidence (%) for a symbol."""
        try:
            for r in (scanner.latest() or {}).get("rows", []):
                if r["symbol"] == sym:
                    return float(r["composite"]["confidence_pct"])
        except Exception:
            pass
        return None

    def _auto_trade_ai(self, threshold, cfg) -> dict:
        """Execute every RECENT, still-pending AI decision that qualifies.

        Gate logic (per your design): the AI sets DIRECTION; a HOLD never trades.
        For a buy/short, the trade must clear the threshold on the SCANNER's
        mechanical confidence (NOT the AI's own confidence — that only sizes the
        trade via the decision's `size`). Handles full mode (one decision) and
        lite mode (one per pair)."""
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        open_syms = self._open_symbols()
        traded, skipped = [], []
        for row in db.list_decisions(50):
            if row.get("status") != "pending" or (row.get("ts") or "") < cutoff:
                continue
            fn = row["filename"]
            full = decisions_io.read_decision(fn)
            if not full:
                continue
            sym = full.get("symbol")
            action = (full.get("action") or "").lower()

            if action not in ("buy", "short"):          # HOLD/close/sell => no trade
                db.set_decision_status(fn, "reviewed")
                db.add_alert("info", "auto_trade", f"AI: NO trade on {sym} — agents said HOLD.", symbol=sym)
                continue
            mech = self._scanner_conf(sym)              # the gate = scanner confidence
            if mech is None or mech < threshold:
                db.set_decision_status(fn, "reviewed")
                db.add_alert("info", "auto_trade",
                             f"AI: {action.upper()} {sym} but scanner conf "
                             f"{round(mech) if mech is not None else '?'}% < {round(threshold)}% — no trade.",
                             symbol=sym)
                continue
            if sym in open_syms or engine.cooldown_remaining(sym) > 0:
                skipped.append(f"{sym}: open/cooldown")
                db.add_alert("info", "auto_trade",
                             f"AI: skipped {sym} — already open or in cooldown.", symbol=sym)
                continue
            res = engine.execute_decision(full, decision_file=fn)
            if res["ok"]:
                traded.append(sym)
                open_syms.add(sym)
                db.add_alert("success", "auto_trade",
                             f"AUTO (AI) {action.upper()} {sym} @ scanner {round(mech)}% — {res['message']}",
                             symbol=sym)
            else:
                skipped.append(f"{sym}: {res['message']}")
        return {"ai_traded": traded, "ai_skipped": skipped}

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
