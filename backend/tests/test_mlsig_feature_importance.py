"""MLSIG feature-importance units tests (MLSIG#3).

The linear fallback ranks features by |coefficient|. On raw features an ATR in
price units or a dow integer gets a coefficient whose size reflects its units,
not its predictive contribution. Importances must not depend on units.

No network: the ML backends are blocked so the pure-NumPy lstsq path runs.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest

from showme.engine.services.ml_signals import fit_predict, make_features


@pytest.fixture()
def no_ml_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("lightgbm", "xgboost", "sklearn", "sklearn.ensemble"):
        monkeypatch.setitem(sys.modules, name, None)


def _random_walk_ohlcv(n: int = 600, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = rng.integers(1_000, 5_000, n).astype(float)
    idx = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_feature_importance_is_invariant_to_feature_units(no_ml_backends: None) -> None:
    """Rescaling ATR (price units vs cents) must not change any importance."""
    features = make_features(_random_walk_ohlcv(), horizon=1)
    base = fit_predict(features)
    scaled = features.copy()
    scaled["atr_14"] = scaled["atr_14"] * 1000.0
    rescaled = fit_predict(scaled)

    assert base["backend"] == "lstsq_linear_probability"
    assert base["feature_importance"]["atr_14"] == pytest.approx(
        rescaled["feature_importance"]["atr_14"], rel=1e-6
    )
    assert base["feature_importance"]["rsi_14"] == pytest.approx(
        rescaled["feature_importance"]["rsi_14"], rel=1e-6
    )


def test_rescaling_a_feature_leaves_predictions_unchanged(no_ml_backends: None) -> None:
    """Standardisation is affine, so the OOS calls and the accuracy must not move."""
    features = make_features(_random_walk_ohlcv(), horizon=1)
    base = fit_predict(features)
    scaled = features.copy()
    scaled["atr_14"] = scaled["atr_14"] * 1000.0
    rescaled = fit_predict(scaled)

    assert base["test_accuracy"] == pytest.approx(rescaled["test_accuracy"])
    assert base["strategy_sharpe"] == pytest.approx(rescaled["strategy_sharpe"], rel=1e-9)
    assert base["latest_prediction_value"] == rescaled["latest_prediction_value"]
