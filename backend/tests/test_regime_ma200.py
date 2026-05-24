"""Audit Q3 #5 — Regime classifier MA200 was literally close.mean().

Pin: when history < 200 bars, `_trend_label` returns ('UNKNOWN', 0.0)
and `classify()` surfaces `data_state='insufficient_history'` with
`confidence_rationale='insufficient_history'`.
"""
from __future__ import annotations

import numpy as np

from showme.engine.services.regime_classifier import (
    _trend_label,
    classify,
)


def test_trend_label_unknown_with_short_history():
    close = np.arange(50, dtype=float) + 100
    label, spread = _trend_label(close)
    assert label == "UNKNOWN"
    assert spread == 0.0


def test_trend_label_bull_with_full_200_window_uptrend():
    # Last 50 bars rise sharply above the first 150 → MA50 > MA200.
    close = np.concatenate([np.full(150, 100.0), np.linspace(110, 130, 50)])
    label, spread = _trend_label(close)
    assert label == "BULL"
    assert spread > 1.0


def test_trend_label_bear_with_full_200_window_downtrend():
    close = np.concatenate([np.full(150, 100.0), np.linspace(90, 70, 50)])
    label, spread = _trend_label(close)
    assert label == "BEAR"
    assert spread < -1.0


def test_classify_emits_insufficient_history_signal():
    close = np.linspace(100.0, 102.0, 50)
    out = classify(close, spread_2s10s_bp=10.0)
    assert out["trend"] == "UNKNOWN"
    assert out["regime"] is None
    assert out["data_state"] == "insufficient_history"
    assert out["confidence_rationale"] == "insufficient_history"


def test_classify_full_history_returns_regime():
    # 250 bars: long flat + final rally → BULL.
    close = np.concatenate([np.full(200, 100.0), np.linspace(101, 115, 50)])
    out = classify(close)
    assert out["trend"] == "BULL"
    assert out["regime"] in {"Risk-on bull", "Risk-on melt-up", "Recovery", "Late-cycle"}
    assert out["data_state"] == "ok"
    assert out["confidence_rationale"] == "ok"


def test_classify_ma200_is_not_close_mean():
    """Regression guard for the literal `close.mean()` bug. We need ma50
    spread vs ma200, NOT spread vs cumulative average."""
    # Linear uptrend over 250 bars: MA50 (recent) >> MA200 (older).
    close = np.linspace(100.0, 200.0, 250)
    out = classify(close)
    # cumulative mean of `close` would be ~150 (midpoint); MA50 ~196.
    # spread vs 150 ~ +30%; spread vs MA200 (avg of last 200 = 150) =
    # (196/150 - 1)*100 ~ +30.6%. Both are BULL, but the SPREAD value
    # should match the MA50/MA200 formula, not close.mean().
    ma50 = close[-50:].mean()
    ma200 = close[-200:].mean()
    expected_spread = (ma50 / ma200 - 1.0) * 100
    assert abs(out["ma50_vs_200_pct"] - expected_spread) < 1e-9
