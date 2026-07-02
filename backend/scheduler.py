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
            "ai_order_ttl_min": cfg.get("ai_order_ttl_min", 120),
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
            self._reconcile_filled()      # flip 'resting' -> 'executed' once a limit fills
            self._log_new_closures(cfg)   # surface SL/TP/manual closes in the feed
            self._expire_stale_orders(cfg)  # cancel unfilled limits that never reached price
            self._manage_positions(cfg)   # break-even / ATR trail / time-stop

            if not cfg.get("scan_enabled", True):
                self.last_summary = {"skipped": "scanning disabled"}
                return self.last_summary

            result = scanner.scan()
            rows = result.get("rows", [])
            source = result.get("data_source")
            skipped_syms = result.get("skipped_symbols", 0)
            db.add_alert("info", "scan",
                         f"Scan complete: {len(rows)} pairs ({source})"
                         + (f", {skipped_syms} skipped on fetch errors" if skipped_syms else "")
                         + ".")

            # HARD GUARD: never gate, debate, or trade on anything but LIVE
            # market data. Synthetic/unavailable data must not reach a decision.
            if source != "bybit-mainnet-live" or not rows:
                db.add_alert("warning", "system",
                             f"Scan data source is '{source}' — skipping auto-trade/AI this "
                             f"cycle; will retry next cycle. ({result.get('error') or 'no rows'})")
                self.last_summary = {"scanned": len(rows), "skipped_cycle": f"data source {source}"}
                return self.last_summary

            summary = {"scanned": len(rows), "traded": [], "skipped": []}
            ai_gated = cfg.get("ai_gated", False)
            threshold = float(cfg.get("auto_trade_confidence", 65))

            # "Cron from the dashboard": when NOT gated, optionally run the AI in a
            # background thread so a slow run never freezes the loop. When gated,
            # the AI is run synchronously below (it IS the decision step).
            # NOTE: pass the qualifying candidates explicitly — running with no
            # symbols means a FULL-universe sweep (token burn) every cycle.
            if cfg.get("auto_analyze", False) and not ai_gated and not self._ai_running:
                auto_syms = [r["symbol"] for r in rows
                             if r["composite"]["confidence_pct"] >= threshold
                             and r["composite"]["direction"] != "flat"]
                if auto_syms:
                    threading.Thread(target=self.run_ai_analyze, daemon=True,
                                     kwargs={"symbols": auto_syms},
                                     name="auto-analyze").start()

            if cfg.get("auto_trade", False):
                if ai_gated:
                    # Fired HOLD triggers ("what would flip me" levels crossed)
                    # join this cycle's debate list — no waiting for the setup
                    # to resolve between scans.
                    trig_syms = self._fired_hold_triggers(rows, cfg)
                    summary.update(self._ai_gated_cycle(rows, threshold, cfg,
                                                        extra_syms=trig_syms))
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
        import json as _json
        AI_LOG_PATH.parent.mkdir(exist_ok=True)
        # Write the EXACT pairs to debate to a file the command reads. This is
        # robust — headless `claude -p` doesn't reliably pass slash-command args,
        # so relying on $ARGUMENTS made it debate the whole universe (token burn).
        try:
            (PROJECT_ROOT / "decisions").mkdir(exist_ok=True)
            # symbols given -> debate exactly those (AI-gated). No symbols -> this
            # is a manual "Run analysis now": mark it an explicit FULL sweep so the
            # picker knows to use the whole universe (empty must NEVER mean "all").
            payload = {"symbols": list(symbols)} if symbols else {"full": True}
            (PROJECT_ROOT / "decisions" / "_debate_targets.json").write_text(_json.dumps(payload))
        except Exception:
            pass
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

    def _ai_gated_cycle(self, rows, threshold, cfg, extra_syms=None) -> dict:
        """AI-GATED: the screener only pre-filters; the AGENTS decide + trade.

        1. Find mechanical candidates >= threshold (not already open / on cooldown).
           A pair also qualifies via a VOLATILITY BREAKOUT flag (muddy composite
           but the move is starting) or a fired HOLD trigger (`extra_syms`) —
           both get a temporary pass on the mechanical gate; the AI still decides.
        2. If any, run the AI debate (synchronous — this is the gate).
        3. Execute ONLY the AI's resulting decision, and only if the AI's own
           confidence clears the threshold. No mechanical-only trades happen here.
        """
        open_syms = self._open_symbols()
        extra_syms = set(extra_syms or ())
        cands, promoted = [], {}          # promoted: sym -> "breakout"/"trigger"
        for r in rows:
            comp, sym = r["composite"], r["symbol"]
            bo = r.get("breakout") or {}
            mech_ok = comp["confidence_pct"] >= threshold and comp["direction"] != "flat"
            bo_ok = bool(cfg.get("breakout_promote", True)) and \
                bo.get("direction") in ("long", "short")
            trig_ok = sym in extra_syms
            if not (mech_ok or bo_ok or trig_ok):
                continue
            direction = comp["direction"] if mech_ok else \
                (bo.get("direction") or comp.get("raw_direction") or comp["direction"])
            if (sym in open_syms
                    or engine.cooldown_remaining(sym) > 0
                    or self._corr_blocked(sym, direction, cfg)):
                continue
            cands.append(r)
            if not mech_ok:
                promoted[sym] = "trigger" if trig_ok else "breakout"
        # Promoted pairs get a TIMED pass on the scanner-confidence gate in
        # _auto_trade_ai — otherwise the AI's BUY on a 30% composite would be
        # blocked by the very muddiness the promotion exists to bypass.
        for sym, why in promoted.items():
            self._grant_gate_exception(sym, why)
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
        top = ", ".join(
            f"{c['symbol']}({c['composite']['confidence_pct']}%"
            + (f", {promoted[c['symbol']]}" if c["symbol"] in promoted else "") + ")"
            for c in cands[:3])
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
            corr_msg = self._corr_blocked(sym, comp["direction"], cfg)
            if corr_msg:
                skipped.append(f"{sym}: {corr_msg}")
                db.add_alert("info", "auto_trade", f"Skipped {sym}: {corr_msg}.", symbol=sym)
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

    def _log_new_closures(self, cfg=None):
        """Detect positions that closed since last check (SL/TP/manual, even when
        closed exchange-side) and post them to the alerts feed."""
        cfg = cfg or db.get_trading_config()
        try:
            closed = exchange.fetch_closed_trades(cfg.get("symbol_universe"), per_sym=20)
        except Exception:
            return
        if not closed:
            return
        last = int(db.get_setting("last_closed_alert_ms") or 0)
        newest = max(t["closed_at"] for t in closed)
        if last == 0:
            # First run after deploy: set the baseline, don't flood with old closes.
            db.set_setting("last_closed_alert_ms", newest)
            return
        new = sorted([t for t in closed if t["closed_at"] > last], key=lambda x: x["closed_at"])
        for t in new:
            pnl = t.get("realized") or 0
            lvl = "success" if pnl > 0 else "warning"
            db.add_alert(lvl, "auto_trade",
                         f"Position CLOSED: {t.get('side')} {t['symbol']} — realized "
                         f"{'+' if pnl >= 0 else ''}{round(pnl, 2)} USDT.", symbol=t["symbol"])
        if new:
            db.set_setting("last_closed_alert_ms", newest)
            self._close_trade_features(new)   # label outcomes for the learner

    def _reconcile_filled(self):
        """A 'resting' limit that later fills becomes a real position — flip its
        decision status to 'executed' so the history isn't stuck at 'resting'."""
        try:
            open_syms = self._open_symbols()
        except Exception:
            return
        for d in db.list_decisions(50):
            if d.get("status") == "resting" and d.get("symbol") in open_syms:
                db.set_decision_status(d["filename"], "executed")

    def _expire_stale_orders(self, cfg=None):
        """Cancel unfilled LIMIT orders older than ai_order_ttl_min so a stale
        'wait for a bounce' plan can't block a symbol indefinitely."""
        cfg = cfg or db.get_trading_config()
        ttl = float(cfg.get("ai_order_ttl_min", 120) or 0)
        if ttl <= 0:
            return
        import time
        now_ms = time.time() * 1000
        try:
            client = exchange.get_client()
        except Exception:
            return
        for sym in (cfg.get("symbol_universe") or []):
            try:
                for o in client.fetch_open_orders(sym):
                    if engine.is_protective_order(o):
                        continue  # never expire a position's SL/TP
                    ts = o.get("timestamp") or 0
                    if ts and (now_ms - ts) > ttl * 60000:
                        try:
                            client.cancel_order(o["id"], sym)
                            db.add_alert("info", "auto_trade",
                                         f"Cancelled unfilled limit on {sym} after {round(ttl)}m — "
                                         f"price never reached the entry.", symbol=sym)
                        except Exception:
                            pass
            except Exception:
                pass

    def _atr_abs(self, sym, last) -> float | None:
        """Absolute ATR for a symbol from the latest scan (ref timeframe)."""
        try:
            for r in (scanner.latest() or {}).get("rows", []):
                if r["symbol"] == sym:
                    ap = (r.get("indicators_ref") or {}).get("atr_pct")
                    return last * float(ap) / 100 if ap and last else None
        except Exception:
            pass
        return None

    def _manage_positions(self, cfg=None):
        """Active position management, every cycle:
          - TIME-STOP: close positions older than max_holding_hours (stale
            trades drift into the stop; free the margin).
          - BREAK-EVEN: once up >= breakeven_atr x ATR, move SL to entry — a
            winner should not turn into a loser.
          - ATR TRAIL: once up >= trail_atr_mult x ATR, trail the SL at
            trail_atr_mult x ATR behind price. Stops only ever TIGHTEN."""
        cfg = cfg or db.get_trading_config()
        be_atr = float(cfg.get("breakeven_atr", 1.0) or 0)
        trail_mult = float(cfg.get("trail_atr_mult", 1.5) or 0)
        max_hold_h = float(cfg.get("max_holding_hours", 0) or 0)
        if be_atr <= 0 and trail_mult <= 0 and max_hold_h <= 0:
            return
        try:
            positions = exchange.fetch_positions()
            client = exchange.get_client()
        except Exception:
            return
        now_ms = time.time() * 1000
        for p in positions:
            sym, side = p.get("symbol"), p.get("side")
            entry = float(p.get("entryPrice") or 0)
            contracts = float(p.get("contracts") or 0)
            if not sym or not entry or not contracts or side not in ("long", "short"):
                continue
            is_long = side == "long"
            info = p.get("info", {}) or {}

            # --- time-stop -------------------------------------------------
            created = float(info.get("createdTime") or p.get("timestamp") or 0)
            if max_hold_h > 0 and created and (now_ms - created) > max_hold_h * 3_600_000:
                try:
                    client.create_order(sym, "market", "sell" if is_long else "buy",
                                        contracts, None, params={"reduceOnly": True})
                    db.add_alert("info", "auto_trade",
                                 f"Time-stop: closed {side} {sym} after "
                                 f"{round((now_ms - created) / 3_600_000, 1)}h without resolution.",
                                 symbol=sym)
                    continue
                except Exception:
                    pass

            # --- break-even + trail -----------------------------------------
            last = float(p.get("markPrice") or 0)
            if not last:
                try:
                    last = float(client.fetch_ticker(sym).get("last") or 0)
                except Exception:
                    continue
            atr_abs = self._atr_abs(sym, last)
            if not atr_abs or atr_abs <= 0:
                continue
            profit = (last - entry) if is_long else (entry - last)
            if profit <= 0:
                continue
            cur_sl = 0.0
            try:
                cur_sl = float(info.get("stopLoss") or p.get("stopLossPrice") or 0)
            except Exception:
                pass
            new_sl = be_sl = None
            if be_atr > 0 and profit >= be_atr * atr_abs:
                # "Break-even" = entry PLUS the round-trip fee, so a stop-out
                # here books a true 0 (not a fee-sized loss that dents the win
                # rate and feeds the loss-streak breaker).
                off = float(cfg.get("breakeven_offset_bps", 12) or 0) / 10000.0
                be_sl = entry * (1 + off) if is_long else entry * (1 - off)
                new_sl = be_sl                              # never let it go red
            if trail_mult > 0 and profit >= trail_mult * atr_abs:
                t_sl = last - trail_mult * atr_abs if is_long else last + trail_mult * atr_abs
                new_sl = max(new_sl or 0, t_sl) if is_long else min(new_sl or 1e18, t_sl)
            if not new_sl:
                continue
            # Only ever tighten (long: SL up; short: SL down), with a small
            # deadband so we don't spam the API for dust moves.
            improves = (not cur_sl) or (is_long and new_sl > cur_sl * 1.0005) \
                or ((not is_long) and new_sl < cur_sl * 0.9995)
            if not improves:
                continue
            try:
                px = client.price_to_precision(sym, new_sl)
                client.private_post_v5_position_trading_stop({
                    "category": "linear", "symbol": client.market_id(sym),
                    "stopLoss": str(px),
                    "positionIdx": int(info.get("positionIdx") or 0),
                })
                kind = "break-even" if (be_sl is not None and new_sl == be_sl) else "trailing"
                db.add_alert("success", "auto_trade",
                             f"Moved SL to {px} on {side} {sym} ({kind}, "
                             f"+{round(profit / atr_abs, 1)} ATR in profit).", symbol=sym)
            except Exception:
                pass

    def _corr_blocked(self, sym: str, direction: str, cfg=None) -> str | None:
        """Correlation cap: refuse a new entry when an OPEN position in the
        same direction is highly correlated — that's the same trade twice."""
        cfg = cfg or db.get_trading_config()
        cap = float(cfg.get("correlation_cap", 0.8) or 0)
        if cap <= 0:
            return None
        scan = scanner.latest() or {}
        try:
            positions = exchange.fetch_positions()
        except Exception:
            return None
        for p in positions:
            psym, pside = p.get("symbol"), p.get("side")
            if not psym or psym == sym or pside not in ("long", "short"):
                continue
            if pside != direction:
                continue
            c = scanner.pair_correlation(scan, sym, psym)
            if c is not None and c >= cap:
                return (f"corr {round(c, 2)} with open {pside} {psym} ≥ cap {cap} "
                        f"— same risk twice")
        return None

    def _close_trade_features(self, closed_trades):
        """Match newly-closed trades to their entry feature snapshots so the
        learner gets labeled outcomes, then refit."""
        try:
            open_rows = db.open_trade_features(mode=mode_manager.mode)
        except Exception:
            return
        if not open_rows:
            return
        open_syms_now = self._open_symbols()
        matched = False
        for t in closed_trades:
            sym = t.get("symbol")
            if sym in open_syms_now:      # still open (partial close) — keep waiting
                continue
            for row in open_rows:
                if row["symbol"] == sym and row.get("outcome") is None:
                    db.close_trade_feature(row["id"], float(t.get("realized") or 0))
                    row["outcome"] = "done"
                    matched = True
                    break
        if matched:
            try:
                from . import learner
                learner.refit()
            except Exception:
                pass

    # --- gate exceptions (breakout promotion / fired HOLD trigger) ----------
    def _grant_gate_exception(self, sym: str, why: str):
        """Give `sym` a timed pass on the mechanical-confidence gate. The AI's
        decision still rules — this only stops the muddy composite from
        blocking the very trade the promotion exists to enable."""
        from datetime import datetime, timezone
        try:
            db.set_setting(f"gate_exception:{sym}",
                           f"{datetime.now(timezone.utc).isoformat()}|{why}")
        except Exception:
            pass

    def _gate_exception(self, sym: str, max_age_min: float = 120) -> str | None:
        """Return the active exception kind ('breakout'/'trigger') or None."""
        try:
            from datetime import datetime, timezone
            raw = db.get_setting(f"gate_exception:{sym}")
            if not raw:
                return None
            ts_s, _, why = raw.partition("|")
            ts = datetime.fromisoformat(ts_s)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            return (why or "breakout") if age_min <= max_age_min else None
        except Exception:
            return None

    def _fired_hold_triggers(self, rows, cfg) -> list[str]:
        """Structured HOLD triggers: agents attach a `reconsider` block to HOLD
        decisions — {"condition": "price_above"|"price_below", "level": <px>,
        "expires_min": <m>, "note": "..."} — meaning "this is what would flip
        me". When the level is crossed while the trigger is armed, re-debate
        the symbol THIS cycle instead of letting the setup resolve unseen
        between 30-minute scans. Each trigger fires at most once."""
        if not cfg.get("hold_triggers", True):
            return []
        from datetime import datetime, timezone, timedelta
        prices = {r["symbol"]: r.get("last") for r in rows}
        cap_min = float(cfg.get("hold_trigger_max_min", 240) or 240)
        fired = []
        for row in db.list_decisions(50):
            if row.get("status") != "reviewed":     # HOLDs land here; fire once
                continue
            full = decisions_io.read_decision(row["filename"]) or {}
            if (full.get("action") or "").lower() != "hold":
                continue
            rec = full.get("reconsider") or {}
            cond, level, sym = rec.get("condition"), rec.get("level"), full.get("symbol")
            px = prices.get(sym)
            if cond not in ("price_above", "price_below") or level is None or px is None:
                continue
            try:                                     # still armed?
                ts = datetime.fromisoformat(row.get("ts"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                exp = rec.get("expires_min")
                ttl = cap_min if exp is None else min(float(exp), cap_min)
                if ttl <= 0:                         # 0 = unconditional HOLD
                    continue
                if datetime.now(timezone.utc) > ts + timedelta(minutes=ttl):
                    continue
            except Exception:
                continue
            hit = (cond == "price_above" and float(px) >= float(level)) or \
                  (cond == "price_below" and float(px) <= float(level))
            if not hit:
                continue
            db.set_decision_status(row["filename"], "triggered")   # never refire
            note = f" ({rec.get('note')})" if rec.get("note") else ""
            db.add_alert("info", "system",
                         f"HOLD trigger hit on {sym}: {cond.replace('_', ' ')} {level} "
                         f"(now {px}){note} — re-debating this cycle.", symbol=sym)
            fired.append(sym)
        return fired

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
                exc = self._gate_exception(sym)
                if exc:
                    db.add_alert("info", "auto_trade",
                                 f"AI: {action.upper()} {sym} — scanner conf "
                                 f"{round(mech) if mech is not None else '?'}% is below the "
                                 f"{round(threshold)}% gate, but a {exc} promotion is active "
                                 f"— proceeding on the AI's call.", symbol=sym)
                else:
                    db.set_decision_status(fn, "reviewed")
                    db.add_alert("info", "auto_trade",
                                 f"AI: {action.upper()} {sym} but scanner conf "
                                 f"{round(mech) if mech is not None else '?'}% < {round(threshold)}% — no trade.",
                                 symbol=sym)
                    continue
            if sym in open_syms or engine.cooldown_remaining(sym) > 0:
                db.set_decision_status(fn, "reviewed")   # don't leave it 'pending'
                skipped.append(f"{sym}: open/cooldown")
                db.add_alert("info", "auto_trade",
                             f"AI: skipped {sym} — already open or in cooldown.", symbol=sym)
                continue
            corr_msg = self._corr_blocked(sym, "long" if action == "buy" else "short", cfg)
            if corr_msg:
                db.set_decision_status(fn, "reviewed")
                skipped.append(f"{sym}: {corr_msg}")
                db.add_alert("info", "auto_trade", f"AI: skipped {sym} — {corr_msg}.", symbol=sym)
                continue
            res = engine.execute_decision(full, decision_file=fn)
            if res["ok"]:
                traded.append(sym)
                open_syms.add(sym)
                db.add_alert("success", "auto_trade",
                             f"AUTO (AI) {action.upper()} {sym} @ scanner {round(mech)}% — {res['message']}",
                             symbol=sym)
            else:
                # Order didn't go through (e.g. stock market closed, min size).
                # Mark it 'failed' so it doesn't linger as 'pending' forever.
                db.set_decision_status(fn, "failed")
                skipped.append(f"{sym}: {res['message']}")
                db.add_alert("warning", "auto_trade",
                             f"AI: {action.upper()} {sym} NOT placed — {res['message']}", symbol=sym)
        return {"ai_traded": traded, "ai_skipped": skipped}

    def _row_to_decision(self, row, comp, cfg) -> dict:
        """Build an executable decision from a mechanical scan row."""
        last = row["last"]
        long = comp["direction"] == "long"
        # SL/TP left None ON PURPOSE: the engine derives ATR-scaled stops
        # (volatility-aware) and falls back to the config % only if ATR is
        # unavailable. Hardcoding the fixed % here would defeat that.
        return {
            "action": "buy" if long else "short",
            "symbol": row["symbol"],
            "size": float(cfg.get("position_size_pct", 5)),
            "entry": last,
            "stop_loss": None,
            "take_profit": None,
            "confidence": comp["confidence_pct"] / 100,
            "rationale": f"Mechanical screener: {comp['confidence_pct']}% {comp['direction']} "
                         f"(aligned={comp['aligned']}) across {len(row['per_tf'])} timeframes.",
            "source": "screener",
        }


# Shared instance.
scheduler = Scheduler()
