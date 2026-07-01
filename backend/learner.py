"""
learner.py
==========
The FEEDBACK LOOP (plain Python, no numpy, NO Claude tokens).

Every executed entry gets a feature snapshot (what the signal looked like);
every close gets a win/loss label. Once there are enough labeled trades, a
tiny logistic regression learns which conditions actually made money FOR THIS
ACCOUNT, and:

  1. calibrate_rows(): blends the learned win-probability into the scanner's
     composite confidence (so confidence starts to MEAN "probability of
     winning" instead of "strength of indicator agreement").
  2. refit(): retrains after each closure batch and writes
     decisions/_learner_stats.json — a human/AI-readable summary the desk
     analyst and portfolio manager read before deciding.

Deliberately conservative: does nothing until MIN_SAMPLES closed trades, and
the blend is capped so the model can never swing confidence by more than
+/-LEARN_BLEND of the mechanical value.
"""

from __future__ import annotations
import json
import math
from pathlib import Path

from . import db, config

MIN_SAMPLES = 30          # do nothing until this many labeled trades
LEARN_BLEND = 0.35        # max fraction of confidence the model may adjust
L2 = 0.1                  # ridge penalty — small dataset, keep weights sane
EPOCHS = 400
LR = 0.05

STATS_PATH = Path(config.DECISIONS_DIR) / "_learner_stats.json"

# Numeric features used for the fit (missing -> 0 after normalization).
FEATURES = ["confidence_pct", "adx", "rsi", "bb_pctb", "vwap_dist_pct",
            "atr_pct", "structure_bias", "btc_correlation",
            "relative_strength_pct", "ai_confidence"]


def _vec(feat: dict, direction: str) -> list[float]:
    """Feature vector, direction-normalized where sign matters."""
    sign = 1.0 if direction == "long" else -1.0
    out = []
    for k in FEATURES:
        v = feat.get(k)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        # Normalize to roughly [-1, 1] ranges.
        if k == "confidence_pct":
            v = v / 100.0
        elif k == "adx":
            v = min(v, 60.0) / 60.0
        elif k == "rsi":
            v = (v - 50.0) / 50.0 * sign      # with-direction momentum
        elif k == "bb_pctb":
            v = (v - 0.5) * 2 * sign
        elif k == "vwap_dist_pct":
            v = max(-1.0, min(1.0, v / 5.0)) * sign
        elif k == "atr_pct":
            v = min(v, 10.0) / 10.0
        elif k == "structure_bias":
            v = v * sign
        elif k == "relative_strength_pct":
            v = max(-1.0, min(1.0, v / 5.0)) * sign
        out.append(v)
    out.append(1.0 if feat.get("aligned") else 0.0)
    out.append(1.0 if (feat.get("regime") == "trend") else 0.0)
    return out


def _sigmoid(z: float) -> float:
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _fit(X: list[list[float]], y: list[int]) -> list[float]:
    """Batch-gradient logistic regression with L2. Returns weights (bias last)."""
    n, d = len(X), len(X[0])
    w = [0.0] * (d + 1)
    for _ in range(EPOCHS):
        grad = [0.0] * (d + 1)
        for xi, yi in zip(X, y):
            p = _sigmoid(sum(wj * xj for wj, xj in zip(w[:-1], xi)) + w[-1])
            err = p - yi
            for j in range(d):
                grad[j] += err * xi[j]
            grad[-1] += err
        for j in range(d):
            w[j] -= LR * (grad[j] / n + L2 * w[j] / n)
        w[-1] -= LR * grad[-1] / n
    return w


def _predict(w: list[float], x: list[float]) -> float:
    return _sigmoid(sum(wj * xj for wj, xj in zip(w[:-1], x)) + w[-1])


def refit() -> dict:
    """Retrain on all labeled trades; persist weights + a readable summary."""
    rows = db.closed_trade_features(limit=500)
    n = len(rows)
    if n < MIN_SAMPLES:
        out = {"ok": False, "samples": n, "needed": MIN_SAMPLES,
               "message": f"Not enough closed trades yet ({n}/{MIN_SAMPLES})."}
        _write_stats(out, rows)
        return out
    X = [_vec(r["features"], r.get("direction") or "long") for r in rows]
    y = [1 if r["outcome"] == "win" else 0 for r in rows]
    w = _fit(X, y)
    # In-sample accuracy + base rate, so we know if the model beats "always guess majority".
    preds = [_predict(w, x) for x in X]
    acc = sum(1 for p, yi in zip(preds, y) if (p >= 0.5) == (yi == 1)) / n
    base = max(sum(y), n - sum(y)) / n
    db.set_setting("learner_weights", json.dumps(w))
    db.set_setting("learner_meta", json.dumps({"samples": n, "accuracy": round(acc, 3),
                                               "base_rate": round(base, 3)}))
    out = {"ok": True, "samples": n, "accuracy": round(acc, 3), "base_rate": round(base, 3),
           "usable": acc > base + 0.02}
    _write_stats(out, rows, w)
    return out


def _write_stats(meta: dict, rows: list[dict], w: list[float] | None = None):
    """Readable summary for the AI agents + dashboard: what's been winning."""
    def rate(sel):
        s = [r for r in rows if sel(r)]
        if not s:
            return None
        return {"n": len(s), "win_rate": round(sum(1 for r in s if r["outcome"] == "win") / len(s), 2),
                "avg_pnl": round(sum(r.get("pnl") or 0 for r in s) / len(s), 2)}
    stats = {
        "meta": meta,
        "overall": rate(lambda r: True),
        "by_direction": {"long": rate(lambda r: r.get("direction") == "long"),
                         "short": rate(lambda r: r.get("direction") == "short")},
        "by_regime": {"trend": rate(lambda r: (r["features"].get("regime")) == "trend"),
                      "chop": rate(lambda r: (r["features"].get("regime")) == "chop"),
                      "squeeze": rate(lambda r: (r["features"].get("regime")) == "squeeze")},
        "by_playbook": {pb: rate(lambda r, p=pb: (r["features"].get("playbook")) == p)
                        for pb in ("trend", "range", "breakout")},
        "by_source": {"ai": rate(lambda r: (r["features"].get("source")) in ("ai", None)),
                      "screener": rate(lambda r: (r["features"].get("source")) == "screener")},
        "high_adx": rate(lambda r: (r["features"].get("adx") or 0) >= 25),
        "low_adx": rate(lambda r: (r["features"].get("adx") or 0) < 20),
        "note": ("win_rate/avg_pnl per condition, computed from THIS account's closed trades. "
                 "Weight decisions toward conditions that have been winning."),
    }
    if w is not None:
        stats["model_weights"] = {k: round(v, 3) for k, v in
                                  zip(FEATURES + ["aligned", "regime_trend", "bias"], w)}
    try:
        STATS_PATH.write_text(json.dumps(stats, indent=2))
    except Exception:
        pass


def calibrate_rows(rows: list[dict]):
    """Blend the learned win-probability into each scan row's confidence.
    No-op until the model exists, has enough data, AND beats the base rate."""
    try:
        w = json.loads(db.get_setting("learner_weights") or "null")
        meta = json.loads(db.get_setting("learner_meta") or "{}")
    except Exception:
        return
    if not w or (meta.get("samples") or 0) < MIN_SAMPLES:
        return
    if (meta.get("accuracy") or 0) <= (meta.get("base_rate") or 1) + 0.02:
        return   # model doesn't beat guessing — don't let it touch anything
    for r in rows:
        comp = r.get("composite") or {}
        direction = comp.get("direction")
        if direction not in ("long", "short"):
            continue
        feat = {
            "confidence_pct": comp.get("confidence_pct"),
            "aligned": comp.get("aligned"), "regime": comp.get("regime"),
            **{k: (r.get("indicators_ref") or {}).get(k)
               for k in ("adx", "rsi", "bb_pctb", "vwap_dist_pct", "atr_pct")},
            "structure_bias": (r.get("structure") or {}).get("structure_bias"),
            "btc_correlation": r.get("btc_correlation"),
            "relative_strength_pct": r.get("relative_strength_pct"),
        }
        p_win = _predict(w, _vec(feat, direction))
        mech = float(comp.get("confidence_pct") or 0)
        blended = (1 - LEARN_BLEND) * mech + LEARN_BLEND * (p_win * 100)
        comp["p_win_learned"] = round(p_win, 3)
        comp["confidence_pct"] = round(min(100.0, max(0.0, blended)), 1)
