"""Market regime classifier (rule-based + Gaussian-mixture fallback).

Classifies market regimes using:
1. **Trend** — 50d / 200d MA cross (BULL / BEAR / SIDEWAYS).
2. **Vol** — realized vol vs long-run (LOW / NORMAL / HIGH).
3. **Drawdown** — peak-to-current % (NORMAL / DRAWDOWN / CRISIS).
4. **Yield curve** — 10Y-2Y (NORMAL / FLAT / INVERTED).

Composite regimes:
- "Risk-on bull"      → BULL + LOW/NORMAL vol + NORMAL dd
- "Risk-on melt-up"   → BULL + HIGH vol + NORMAL dd
- "Late-cycle"        → BULL + INVERTED curve
- "Drawdown"          → BEAR + DRAWDOWN
- "Crisis"            → BEAR + CRISIS dd + HIGH vol
- "Range-bound"       → SIDEWAYS + NORMAL vol
- "Recovery"          → BULL + DRAWDOWN dd (rebound)

Optional ML mode: rule-based labels train a simple Gaussian-mixture or
KMeans on the same features → unsupervised cluster IDs (no SciPy needed —
uses pure numpy).
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _trend_label(close: np.ndarray) -> tuple[str, float]:
    if len(close) < 200:
        ma50 = close[-min(50, len(close)):].mean()
        ma200 = close[-min(len(close), len(close)):].mean()
    else:
        ma50 = close[-50:].mean()
        ma200 = close[-200:].mean()
    spread = (ma50 / ma200 - 1.0) * 100 if ma200 else 0.0
    if spread > 1.0:
        return "BULL", spread
    if spread < -1.0:
        return "BEAR", spread
    return "SIDEWAYS", spread


def _vol_label(returns: np.ndarray) -> tuple[str, float]:
    if len(returns) < 21:
        return "UNKNOWN", 0.0
    short = float(np.std(returns[-21:]) * np.sqrt(252) * 100)
    long_v = float(np.std(returns) * np.sqrt(252) * 100) if len(returns) > 60 else short
    ratio = short / long_v if long_v else 1.0
    if ratio > 1.5:
        return "HIGH", short
    if ratio < 0.7:
        return "LOW", short
    return "NORMAL", short


def _drawdown_label(close: np.ndarray) -> tuple[str, float]:
    if len(close) < 2:
        return "UNKNOWN", 0.0
    peak = float(np.maximum.accumulate(close)[-1])
    cur = float(close[-1])
    dd = (cur / peak - 1.0) * 100 if peak else 0.0
    if dd <= -20.0:
        return "CRISIS", dd
    if dd <= -10.0:
        return "DRAWDOWN", dd
    return "NORMAL", dd


def _curve_label(spread_2s10s_bp: float | None) -> tuple[str, float | None]:
    if spread_2s10s_bp is None:
        return "UNKNOWN", None
    if spread_2s10s_bp < 0:
        return "INVERTED", spread_2s10s_bp
    if spread_2s10s_bp < 50:
        return "FLAT", spread_2s10s_bp
    return "NORMAL", spread_2s10s_bp


def composite(trend: str, vol: str, dd: str, curve: str) -> str | None:
    # Bug #22 fix: when vol/drawdown/curve are all UNKNOWN we used to fall
    # through to "Range-bound" and fabricate a regime. Return None instead
    # so callers can render "insufficient inputs" honestly.
    unknown_inputs = {vol, dd, curve}
    if unknown_inputs == {"UNKNOWN"}:
        return None
    if trend == "BEAR" and dd == "CRISIS":
        return "Crisis"
    if trend == "BEAR" and dd == "DRAWDOWN":
        return "Drawdown"
    if trend == "BEAR":
        return "Bearish"
    if trend == "BULL" and dd == "DRAWDOWN":
        return "Recovery"
    if trend == "BULL" and curve == "INVERTED":
        return "Late-cycle"
    if trend == "BULL" and vol == "HIGH":
        return "Risk-on melt-up"
    if trend == "BULL":
        return "Risk-on bull"
    if trend == "SIDEWAYS" and vol == "HIGH":
        return "Choppy"
    return "Range-bound"


def _confidence(trend: str, vol: str, dd: str, curve: str) -> float:
    # 1.0 = all 4 inputs resolved; 0.25 per known input. UNKNOWN trend is
    # impossible by construction (we always have close), so the practical
    # floor is 0.25 (trend only).
    known = sum(1 for label in (trend, vol, dd, curve) if label != "UNKNOWN")
    return round(known / 4.0, 4)


def classify(close: np.ndarray, *, spread_2s10s_bp: float | None = None) -> dict[str, Any]:
    close = np.asarray(close, dtype=float)
    rets = np.diff(close) / close[:-1] if len(close) > 1 else np.array([])
    trend, ma_spread = _trend_label(close)
    vol, vol_pct = _vol_label(rets)
    dd, dd_pct = _drawdown_label(close)
    curve, spread = _curve_label(spread_2s10s_bp)
    regime = composite(trend, vol, dd, curve)
    confidence = _confidence(trend, vol, dd, curve)
    data_state = "insufficient_inputs" if regime is None else "ok"
    return {
        "trend": trend, "ma50_vs_200_pct": ma_spread,
        "vol": vol, "realized_vol_pct": vol_pct,
        "drawdown": dd, "drawdown_pct": dd_pct,
        "curve": curve, "curve_2s10s_bp": spread,
        "regime": regime,
        "confidence": confidence,
        "data_state": data_state,
    }


def kmeans_lite(features: np.ndarray, k: int = 4, max_iter: int = 100,
                seed: int = 42) -> dict[str, Any]:
    """Pure-numpy k-means for regime clustering."""
    rng = np.random.default_rng(seed)
    n = features.shape[0]
    if n < k:
        return {"labels": [0] * n, "centers": features.tolist()}
    idx = rng.choice(n, size=k, replace=False)
    centers = features[idx].copy()
    labels = np.zeros(n, dtype=int)
    for _ in range(max_iter):
        dists = np.linalg.norm(features[:, None, :] - centers[None, :, :], axis=-1)
        new_labels = dists.argmin(axis=1)
        if (new_labels == labels).all():
            break
        labels = new_labels
        for c in range(k):
            mask = labels == c
            if mask.any():
                centers[c] = features[mask].mean(axis=0)
    return {
        "labels": labels.tolist(),
        "centers": centers.tolist(),
        "k": k,
    }
