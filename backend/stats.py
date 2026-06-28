"""
stats.py
========
Portfolio performance metrics computed from the equity_curve table and the
orders table. Pure functions, no external deps (no numpy) so they're easy to
audit.

  total_return  : (last_equity / first_equity) - 1
  win_rate      : winning closed orders / closed orders with known pnl
  sharpe        : mean(period returns) / std(period returns) * sqrt(periods/yr)
  max_drawdown  : worst peak-to-trough decline on the equity curve
"""

from __future__ import annotations
import math

from . import db


def _returns(equity: list[float]) -> list[float]:
    out = []
    for prev, cur in zip(equity, equity[1:]):
        if prev:
            out.append((cur - prev) / prev)
    return out


def max_drawdown(equity: list[float]) -> float:
    """Largest peak-to-trough drop as a positive fraction (0.20 == -20%)."""
    peak = -math.inf
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd


def sharpe(returns: list[float], periods_per_year: int = 365 * 24) -> float:
    """Annualized Sharpe (risk-free = 0). Defaults assume hourly snapshots."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def compute_stats() -> dict:
    from .config import mode_manager
    equity_rows = db.list_equity(mode=mode_manager.mode)
    equity = [r["equity"] for r in equity_rows]

    total_return = 0.0
    if len(equity) >= 2 and equity[0]:
        total_return = equity[-1] / equity[0] - 1

    rets = _returns(equity)

    # Win rate from orders that have a realized pnl recorded.
    orders = db.list_orders(limit=10000)
    closed = [o for o in orders if o.get("pnl") is not None]
    wins = [o for o in closed if (o.get("pnl") or 0) > 0]
    win_rate = (len(wins) / len(closed)) if closed else 0.0

    return {
        "total_return_pct": round(total_return * 100, 2),
        "win_rate_pct": round(win_rate * 100, 2),
        "sharpe": round(sharpe(rets), 2),
        "max_drawdown_pct": round(max_drawdown(equity) * 100, 2),
        "num_closed_trades": len(closed),
        "num_snapshots": len(equity),
    }
