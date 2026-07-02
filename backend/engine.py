"""
engine.py
=========
LAYER 2 EXECUTION ENGINE (plain Python, NO Claude tokens).

This is the muscle. It takes a decision (produced by the Layer 1 debate and
approved by you in the UI) and turns it into a real order on Bybit, in whatever
environment is active (paper/testnet or live/mainnet). It also enforces the two
hard safety stops every time:

   1. KILL SWITCH  — if engaged, nothing executes.
   2. MAX DRAWDOWN — if the equity curve is down more than the configured limit,
                     we auto-engage the kill switch and refuse to trade.

Order sizing is derived from your config: a position is `position_size_pct` of
equity, scaled by `leverage`, converted to a base-currency amount at the current
price. Stop-loss and take-profit are attached to the entry order.

Every attempt is written to SQLite (`orders` table) — success or failure — so the
dashboard's history is the full record.
"""

from __future__ import annotations

from . import db, exchange, stats
from .config import mode_manager


class ExecutionResult(dict):
    """Just a dict with ok/message/order fields, for clarity at call sites."""


def _num(x):
    """Float or None (treats 0/blank as None)."""
    try:
        v = float(x)
        return v if v != 0 else None
    except (TypeError, ValueError):
        return None


def _fail(msg: str, **extra) -> ExecutionResult:
    return ExecutionResult(ok=False, message=msg, **extra)


def _ok(msg: str, **extra) -> ExecutionResult:
    return ExecutionResult(ok=True, message=msg, **extra)


def is_protective_order(o: dict) -> bool:
    """True for stop-loss / take-profit / any reduce-only or conditional order.
    These protect an open position and must NEVER be cancelled by our
    entry-replacement logic — cancelling them would strip the position's SL/TP."""
    info = o.get("info", {}) or {}
    if o.get("reduceOnly") or info.get("reduceOnly") in (True, "true", "True", "1", 1):
        return True
    # Bybit conditional / SL / TP orders carry these fields when set.
    for k in ("stopLoss", "takeProfit", "stopPrice", "triggerPrice", "stopOrderType",
              "tpslMode", "orderType"):
        v = info.get(k) or o.get(k)
        if k == "stopOrderType" and v and str(v).lower() != "unknownstoporder":
            return True
        if k in ("stopPrice", "triggerPrice") and _num(v):
            return True
    return False


def drawdown_guard() -> tuple[bool, float, float]:
    """Return (breached, current_dd_pct, limit_pct).
    Compares the worst peak-to-trough on the equity curve to the configured
    max_drawdown_pct. If breached, the caller should halt.
    """
    cfg = db.get_trading_config()
    limit = float(cfg.get("max_drawdown_pct", 20))
    # Only the CURRENT environment's equity — paper and live are different
    # accounts; mixing them shows a fake drawdown when you switch modes.
    rows = db.list_equity(mode=mode_manager.mode)
    # After a manual kill-switch reset we only measure drawdown from that moment
    # forward, so stale history can't immediately re-trip the auto-stop.
    ref = mode_manager.dd_reference_ts
    if ref:
        rows = [r for r in rows if r["ts"] >= ref]
    equity = [r["equity"] for r in rows]
    dd = stats.max_drawdown(equity) * 100 if equity else 0.0
    return dd >= limit, round(dd, 2), limit


def daily_loss_guard() -> tuple[bool, float, float]:
    """Return (breached, today_pnl_pct, limit_pct). 0 limit => disabled."""
    cfg = db.get_trading_config()
    limit = float(cfg.get("daily_loss_limit_pct", 0) or 0)
    if limit <= 0:
        return False, 0.0, 0.0
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    rows = [r for r in db.list_equity(mode=mode_manager.mode) if r["ts"].startswith(today)]
    if len(rows) < 2:
        return False, 0.0, limit
    first, cur = rows[0]["equity"], rows[-1]["equity"]
    pct = ((cur - first) / first * 100) if first else 0.0
    return (pct <= -limit), round(pct, 2), limit


def cooldown_remaining(symbol: str) -> float:
    """Minutes left on a symbol's trade cooldown (0 if none / disabled)."""
    cfg = db.get_trading_config()
    mins = float(cfg.get("min_minutes_between_trades", 0) or 0)
    if mins <= 0:
        return 0.0
    ts = db.last_order_ts(symbol)
    if not ts:
        return 0.0
    from datetime import datetime, timezone
    try:
        age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 60
        return max(0.0, round(mins - age_min, 1))
    except Exception:
        return 0.0


def loss_streak_guard() -> tuple[bool, int, str]:
    """Circuit breaker: after N consecutive losing closes, pause NEW entries
    for a cooldown window (closes are always allowed). Returns
    (paused, streak, message)."""
    cfg = db.get_trading_config()
    n = int(cfg.get("loss_streak_pause", 3) or 0)
    if n <= 0:
        return False, 0, ""
    cooldown_min = float(cfg.get("loss_streak_cooldown_min", 240) or 0)
    try:
        closed = exchange.fetch_closed_trades(cfg.get("symbol_universe"), per_sym=20)
    except Exception:
        return False, 0, ""
    streak, newest_loss_ms = 0, 0
    for t in closed:                       # newest first
        if (t.get("realized") or 0) < 0:
            streak += 1
            newest_loss_ms = max(newest_loss_ms, t.get("closed_at") or 0)
        else:
            break
    if streak < n or not newest_loss_ms:
        return False, streak, ""
    import time
    mins_since = (time.time() * 1000 - newest_loss_ms) / 60000
    if mins_since >= cooldown_min:
        return False, streak, ""
    left = max(1, round(cooldown_min - mins_since))
    return True, streak, (f"{streak} consecutive losses — new entries paused for {left}m more "
                          f"(loss-streak circuit breaker).")


def funding_guard(symbol: str, is_long: bool) -> str | None:
    """Skip an entry that would immediately pay a punitive funding rate:
    within `funding_avoid_min` minutes of the next funding AND the rate is
    against the trade's direction. Returns a message if blocked, else None."""
    cfg = db.get_trading_config()
    avoid_min = float(cfg.get("funding_avoid_min", 10) or 0)
    if avoid_min <= 0:
        return None
    thr = float(cfg.get("funding_avoid_rate", 0.0003) or 0.0003)
    try:
        from . import market_structure
        f = market_structure._funding(market_structure._client(), symbol)
        rate, nxt = f.get("rate"), f.get("next")
        if rate is None or not nxt:
            return None
        import time
        mins_to = (float(nxt) - time.time() * 1000) / 60000
        pays = (is_long and rate >= thr) or ((not is_long) and rate <= -thr)
        if pays and 0 <= mins_to <= avoid_min:
            side = "long" if is_long else "short"
            return (f"Funding {rate * 100:+.4f}% is against this {side} and pays in "
                    f"~{max(1, round(mins_to))}m — entry deferred past funding.")
    except Exception:
        return None
    return None


def _scan_row(symbol: str) -> dict:
    """The latest scan row for a symbol (ATR%, features, structure)."""
    try:
        from . import scanner
        for r in (scanner.latest() or {}).get("rows", []):
            if r.get("symbol") == symbol:
                return r
    except Exception:
        pass
    return {}


def preflight() -> ExecutionResult:
    """Run the safety checks that must pass before ANY order."""
    if mode_manager.kill_switch_active:
        return _fail("Kill switch is engaged — trading halted.")
    breached, dd, limit = drawdown_guard()
    if breached:
        mode_manager.engage_kill_switch()  # auto-stop
        return _fail(f"Max drawdown breached ({dd}% >= {limit}%). Kill switch auto-engaged.",
                     drawdown_pct=dd, limit_pct=limit)
    dl_breached, day_pct, dl_limit = daily_loss_guard()
    if dl_breached:
        mode_manager.engage_kill_switch()  # daily auto-stop
        return _fail(f"Daily loss limit hit ({day_pct}% <= -{dl_limit}%). Trading halted for today.",
                     daily_pnl_pct=day_pct, daily_limit_pct=dl_limit)
    return _ok("preflight passed", drawdown_pct=dd, limit_pct=limit)


def _equity_usdt() -> float:
    """Account equity in USDT, robust to Bybit unified/demo balance shapes."""
    bal = exchange.fetch_balance()
    try:
        acct = bal["info"]["result"]["list"][0]
        eq = float(acct.get("totalEquity") or 0) or float(acct.get("totalWalletBalance") or 0)
        if eq > 0:
            return eq
    except Exception:
        pass
    return float((bal.get("total", {}) or {}).get("USDT", 0) or 0)


def _amount_from_size(symbol: str, size_pct: float, leverage: int, price: float) -> float:
    """Convert a %-of-equity position into a base-currency amount."""
    equity = _equity_usdt()
    notional = equity * (size_pct / 100.0) * leverage
    if price <= 0:
        return 0.0
    return notional / price


def execute_decision(decision: dict, decision_file: str | None = None) -> ExecutionResult:
    """Execute one decision dict. Returns an ExecutionResult and logs to SQLite."""
    pre = preflight()
    if not pre["ok"]:
        return pre

    action = (decision.get("action") or "").lower()
    symbol = decision.get("symbol")
    if action == "hold":
        return _ok("Decision is HOLD — no order placed.")
    if action not in ("buy", "short", "sell", "close"):
        return _fail(f"Unknown action '{action}'.")

    cfg = db.get_trading_config()
    leverage = int(cfg.get("leverage", 3))
    client = exchange.get_client()
    mode = mode_manager.mode

    # Current price for sizing (fall back to the decision's entry).
    price = decision.get("entry")
    try:
        t = client.fetch_ticker(symbol)
        price = float(t.get("last") or price)
    except Exception:
        pass
    if not price:
        return _fail("Could not determine a price for sizing.")

    # --- CLOSE / SELL: reduce existing position -----------------------------
    if action in ("close", "sell"):
        positions = exchange.fetch_positions()
        pos = next((p for p in positions if p.get("symbol") == symbol and p.get("contracts")), None)
        if not pos:
            return _ok(f"No open position on {symbol} to close.")
        close_side = "sell" if pos.get("side") == "long" else "buy"
        amount = float(pos.get("contracts"))
        try:
            order = client.create_order(symbol, "market", close_side, amount, None,
                                        params={"reduceOnly": True})
        except Exception as e:
            db.record_order(mode=mode, symbol=symbol, side=close_side, order_type="market",
                            qty=amount, price=price, status="rejected",
                            decision_file=decision_file, raw=str(e))
            return _fail(f"Close order rejected: {e}")
        db.record_order(mode=mode, symbol=symbol, side=close_side, order_type="market",
                        qty=amount, price=price, status="submitted",
                        exchange_id=order.get("id"), decision_file=decision_file,
                        raw=str(order))
        if decision_file:
            db.set_decision_status(decision_file, "executed")
        return _ok(f"Close submitted for {symbol}.", order_id=order.get("id"))

    # --- BUY / SHORT: open a new position --------------------------------
    side = "buy" if action == "buy" else "sell"
    is_long = action == "buy"

    # Entry-only guards (closes above are never blocked by these).
    paused, streak, ls_msg = loss_streak_guard()
    if paused:
        return _fail(ls_msg, loss_streak=streak)
    f_msg = funding_guard(symbol, is_long)
    if f_msg:
        return _fail(f_msg)

    # If a position is already OPEN, don't stack another entry onto it.
    try:
        if any(p.get("contracts") for p in exchange.fetch_positions() if p.get("symbol") == symbol):
            if decision_file:
                db.set_decision_status(decision_file, "reviewed")
            return _ok(f"{symbol}: position already open — not adding to it.")
    except Exception:
        pass
    # Otherwise REPLACE any stale resting ENTRY limit with this fresh decision —
    # the AI's entry should reflect the newest debate, not an hour-old plan. We
    # ONLY cancel plain entry limits; stop-loss / take-profit / reduce-only orders
    # are left untouched so we never strip a position's protection.
    try:
        for o in client.fetch_open_orders(symbol):
            if is_protective_order(o):
                continue
            try:
                client.cancel_order(o["id"], symbol)
            except Exception:
                pass
    except Exception:
        pass

    # SIZE & LEVERAGE come straight from YOUR config — your risk budget / how much
    # you want to invest. The AI only sets direction, entry, and (cautious) SL/TP.
    # Risk-based sizing below can only SHRINK the position, never exceed your size.
    size_pct = float(cfg.get("position_size_pct", 5))

    # ENTRY: honor the AI's planned entry as a LIMIT order when it's a better,
    # passive price on the correct side (short ABOVE market / long BELOW market).
    # Otherwise fall back to a market order — never chase past the plan.
    ai_entry = _num(decision.get("entry"))
    order_type, limit_price = "market", None
    post_only = False
    if ai_entry:
        if is_long and ai_entry < price * 0.999:
            order_type, limit_price = "limit", ai_entry
        elif (not is_long) and ai_entry > price * 1.001:
            order_type, limit_price = "limit", ai_entry

    # MAKER ENTRY: when we'd otherwise cross the spread with a market order,
    # optionally rest a post-only limit at the touch instead. Saves the taker
    # fee both ways (~0.11% round trip vs a 4% target is real edge). The TTL
    # expiry in the scheduler cleans it up if price runs away.
    if order_type == "market" and cfg.get("maker_entries", False):
        try:
            t = client.fetch_ticker(symbol)
            bid, ask = _num(t.get("bid")), _num(t.get("ask"))
            off = float(cfg.get("maker_offset_bps", 2) or 0) / 10000.0
            if is_long and bid:
                order_type, limit_price, post_only = "limit", bid * (1 - off), True
            elif (not is_long) and ask:
                order_type, limit_price, post_only = "limit", ask * (1 + off), True
        except Exception:
            pass
    ref_price = limit_price or price

    # --- SL/TP FIRST (they drive sizing): prefer the AI's structural levels;
    # else ATR-scaled distances (adapt to each pair's volatility); else config %.
    sl = _num(decision.get("stop_loss"))
    tp = _num(decision.get("take_profit"))
    scan_row = _scan_row(symbol)
    atr_pct = _num((scan_row.get("indicators_ref") or {}).get("atr_pct"))
    atr_sl_mult = float(cfg.get("atr_stop_mult", 1.5) or 0)
    atr_tp_mult = float(cfg.get("atr_tp_mult", 3.0) or 0)
    if not sl:
        if atr_pct and atr_sl_mult > 0:
            dist = ref_price * atr_pct / 100 * atr_sl_mult
            sl = ref_price - dist if is_long else ref_price + dist
        else:
            slp = float(cfg.get("stop_loss_pct", 2))
            sl = ref_price * (1 - slp / 100) if is_long else ref_price * (1 + slp / 100)
    if not tp:
        if atr_pct and atr_tp_mult > 0:
            dist = ref_price * atr_pct / 100 * atr_tp_mult
            tp = ref_price + dist if is_long else ref_price - dist
        else:
            tpp = float(cfg.get("take_profit_pct", 4))
            tp = ref_price * (1 + tpp / 100) if is_long else ref_price * (1 - tpp / 100)

    # --- SIZING: your configured size is the CEILING. If risk_per_trade_pct is
    # set, normalize so a stop-out loses ~that % of equity — wide stop = smaller
    # position, tight stop = up to (but never beyond) your configured size.
    amount = _amount_from_size(symbol, size_pct, leverage, ref_price)
    risk_pct = float(cfg.get("risk_per_trade_pct", 0) or 0)
    stop_dist = abs(ref_price - sl)
    risk_cap_note = ""
    if risk_pct > 0 and stop_dist > 0:
        risk_amount = _equity_usdt() * (risk_pct / 100.0) / stop_dist
        if 0 < risk_amount < amount:
            risk_cap_note = (f" [risk cap {risk_pct}%: size cut "
                             f"{amount:.4g} → {risk_amount:.4g} "
                             f"({risk_amount / amount * 100:.0f}% of configured) — "
                             f"set risk_per_trade_pct: 0 to always use full size]")
            amount = risk_amount
    if amount <= 0:
        return _fail("Computed order size is zero (no equity / price). Fund the account or check keys.")
    try:
        amount = float(client.amount_to_precision(symbol, amount))
    except Exception:
        pass

    try:
        client.set_leverage(leverage, symbol)
    except Exception:
        pass

    def _p(v):
        try:
            return client.price_to_precision(symbol, v)
        except Exception:
            return str(v)
    params = {"stopLoss": _p(sl), "takeProfit": _p(tp)}
    if post_only:
        params["postOnly"] = True

    try:
        if order_type == "limit":
            order = client.create_order(symbol, "limit", side, amount, float(_p(limit_price)), params=params)
        else:
            order = client.create_order(symbol, "market", side, amount, None, params=params)
    except Exception as e:
        db.record_order(mode=mode, symbol=symbol, side=side, order_type=order_type,
                        qty=amount, price=ref_price, status="rejected",
                        decision_file=decision_file, raw=str(e))
        return _fail(f"Entry order rejected: {e}")

    # --- Feature snapshot for the learner: what the signal looked like at entry.
    try:
        comp = scan_row.get("composite") or {}
        iref = scan_row.get("indicators_ref") or {}
        struct = scan_row.get("structure") or {}
        db.record_trade_features(
            mode=mode, symbol=symbol, direction="long" if is_long else "short",
            entry=ref_price, decision_file=decision_file,
            features={
                "confidence_pct": comp.get("confidence_pct"),
                "blended_score": comp.get("blended_score"),
                "aligned": comp.get("aligned"),
                "regime": comp.get("regime"),
                "adx": iref.get("adx"), "rsi": iref.get("rsi"),
                "bb_pctb": iref.get("bb_pctb"), "vwap_dist_pct": iref.get("vwap_dist_pct"),
                "atr_pct": atr_pct, "divergence": iref.get("divergence"),
                "structure_bias": struct.get("structure_bias"),
                "funding_rate": struct.get("funding_rate"),
                "btc_correlation": scan_row.get("btc_correlation"),
                "relative_strength_pct": scan_row.get("relative_strength_pct"),
                "ai_confidence": _num(decision.get("confidence")),
                "playbook": decision.get("playbook"),
                "source": decision.get("source") or "ai",
            })
    except Exception:
        pass

    # A market order fills now (=> position opened => "executed"). A limit order
    # usually rests unfilled (=> NO position yet => "resting", not "executed").
    filled = order_type == "market" or order.get("status") in ("closed", "filled")
    status = "executed" if filled else "resting"
    db.record_order(mode=mode, symbol=symbol, side=side, order_type=order_type,
                    qty=amount, price=order.get("average") or ref_price,
                    status="filled" if filled else "resting", filled_qty=order.get("filled"),
                    avg_fill_price=order.get("average"),
                    exchange_id=order.get("id"), decision_file=decision_file, raw=str(order))
    if decision_file:
        db.set_decision_status(decision_file, status)
    if filled:
        placed = f"MARKET filled @ ~{_p(price)} — position OPEN"
    else:
        placed = f"LIMIT resting @ {_p(limit_price)} — waiting for a bounce, NOT a position yet"
    return _ok(f"{action.upper()} {symbol} {placed}: {amount} (lev {leverage}x, size {round(size_pct, 2)}%, "
               f"SL {_p(sl)}, TP {_p(tp)}).{risk_cap_note}",
               order_id=order.get("id"), amount=amount, price=ref_price, status=status, mode=mode)
