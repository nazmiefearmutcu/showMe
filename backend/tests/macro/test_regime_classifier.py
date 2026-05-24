"""Regime classifier — Bug #22 regression.

When every secondary input (vol / drawdown / curve) is UNKNOWN, the
classifier used to fall through to the default "Range-bound" label,
fabricating a regime from no signal. It now returns ``regime=None`` +
``data_state="insufficient_inputs"`` + ``confidence=0.0`` so the UI can
render "Cannot classify — no inputs available."
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.services import regime_classifier as rgm  # noqa: E402


def test_classify_short_series_returns_null_regime() -> None:
    """1 close → trend UNKNOWN (<200 bars), vol UNKNOWN, dd UNKNOWN, curve UNKNOWN.

    Audit Q3 #5: with <200 bars we now report `insufficient_history` since
    trend is unresolvable; older code mislabeled this `insufficient_inputs`.
    """
    out = rgm.classify(np.asarray([100.0]))
    assert out["trend"] == "UNKNOWN"
    assert out["vol"] == "UNKNOWN"
    assert out["drawdown"] == "UNKNOWN"
    assert out["curve"] == "UNKNOWN"
    assert out["regime"] is None
    assert out["data_state"] == "insufficient_history"
    # 0/4 inputs resolved → confidence 0.0.
    assert out["confidence"] == pytest.approx(0.0)


def test_classify_full_series_returns_real_regime() -> None:
    """A 300d series with no FRED spread → trend/vol/dd known, curve UNKNOWN."""
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0005, 0.01, size=300)
    close = 100 * np.exp(np.cumsum(rets))
    out = rgm.classify(close, spread_2s10s_bp=None)
    assert out["regime"] is not None
    assert out["data_state"] == "ok"
    # 3 of 4 inputs resolved (curve still UNKNOWN) → 0.75
    assert out["confidence"] == pytest.approx(0.75)


def test_classify_with_curve_input_hits_full_confidence() -> None:
    rng = np.random.default_rng(11)
    rets = rng.normal(0.0005, 0.01, size=300)
    close = 100 * np.exp(np.cumsum(rets))
    out = rgm.classify(close, spread_2s10s_bp=42.0)
    assert out["curve"] == "FLAT"
    assert out["confidence"] == pytest.approx(1.0)


def test_composite_returns_none_when_trend_unknown() -> None:
    """Audit Q3 #5: trend UNKNOWN (insufficient MA200 history) → no regime."""
    assert rgm.composite("UNKNOWN", "NORMAL", "NORMAL", "NORMAL") is None


def test_composite_returns_none_when_all_secondary_unknown() -> None:
    assert rgm.composite("BULL", "UNKNOWN", "UNKNOWN", "UNKNOWN") is None
    assert rgm.composite("SIDEWAYS", "UNKNOWN", "UNKNOWN", "UNKNOWN") is None


def test_composite_still_labels_when_one_input_known() -> None:
    # A single known secondary input keeps us out of the insufficient bucket.
    assert rgm.composite("BULL", "NORMAL", "UNKNOWN", "UNKNOWN") == "Risk-on bull"
    assert rgm.composite("BEAR", "UNKNOWN", "CRISIS", "UNKNOWN") == "Crisis"
