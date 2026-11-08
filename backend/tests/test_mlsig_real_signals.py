"""MLSIG strategy-Sharpe honesty tests (MLSIG#1).

The strategy Sharpe must be scored with out-of-sample positions times the
realised next-bar return. The pre-fix code used in-sample predictions times
the sign of an N-bar forward return, which manufactures an edge on pure noise.

No network: the ML backends are blocked so the pure-NumPy lstsq path runs
deterministically, and xgboost is replaced by an inline fake where needed.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.services.ml_signals import fit_predict, make_features


@pytest.fixture()
def no_ml_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force fit_predict onto the NumPy lstsq backend."""
    for name in ("lightgbm", "xgboost", "sklearn", "sklearn.ensemble"):
        monkeypatch.setitem(sys.modules, name, None)


def _random_walk_ohlcv(n: int = 900, seed: int = 7) -> pd.DataFrame:
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


def _lstsq_oos_predictions(X: pd.DataFrame, y: pd.Series, split: int) -> np.ndarray:
    """Independent replication of the lstsq backend's out-of-sample ±1 call."""
    yt = y.iloc[:split].replace({-1: 0, 0: 0, 1: 1}).to_numpy(dtype=float)
    design = np.column_stack([np.ones(split), X.iloc[:split].to_numpy()])
    beta, *_ = np.linalg.lstsq(design, yt, rcond=None)
    z = np.column_stack([np.ones(len(X) - split), X.iloc[split:].to_numpy()]) @ beta
    return np.where(z > 0.5, 1, -1)


def test_strategy_sharpe_uses_oos_positions_times_next_bar_returns(no_ml_backends: None) -> None:
    """Pre-fix: Sharpe = mean/std of pred_full(in-sample) * sign(N-bar fwd return)."""
    df = _random_walk_ohlcv()
    horizon = 5
    features = make_features(df, horizon=horizon)
    report = fit_predict(features)

    labelled = features.loc[features["target"].notna()]
    X = labelled[[c for c in labelled.columns if c not in ("target", "fwd_ret_1")]]
    y = labelled["target"]
    split = int(len(X) * 0.7)
    pos = _lstsq_oos_predictions(X, y, split)
    next_ret = df["close"].pct_change().shift(-1).reindex(labelled.index)
    strat = pd.Series(pos * next_ret.iloc[split:].to_numpy(dtype=float))
    expected = float(strat.mean() / strat.std() * (252 ** 0.5))

    assert report["backend"] == "lstsq_logistic"
    assert report["strategy_sharpe"] == pytest.approx(expected, rel=1e-9, abs=1e-9)


def test_random_walk_has_no_manufactured_edge(no_ml_backends: None) -> None:
    """A pure random walk has no edge; an honest OOS Sharpe stays near zero."""
    df = _random_walk_ohlcv(n=1200, seed=11)
    report = fit_predict(make_features(df, horizon=5))
    assert abs(report["strategy_sharpe"]) < 1.5, report["strategy_sharpe"]


def test_xgboost_positions_are_signed_not_zero_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """xgboost predicts 0/1; a 0 must map to a short position, not to 'no position'.

    With every prediction mapped to short, accuracy equals the share of
    down-labels among non-zero test labels. The pre-fix 0/1 output never
    matched a -1 label and reported 0.0.
    """

    class _FakeXGBClassifier:
        def __init__(self, **_kwargs: Any) -> None:
            self.feature_importances_ = np.ones(1)

        def fit(self, X: Any, _y: Any) -> None:
            self.feature_importances_ = np.ones(X.shape[1])

        def predict(self, X: Any) -> np.ndarray:
            return np.zeros(len(X))

    fake = types.ModuleType("xgboost")
    fake.XGBClassifier = _FakeXGBClassifier  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "lightgbm", None)
    monkeypatch.setitem(sys.modules, "xgboost", fake)

    features = make_features(_random_walk_ohlcv(n=600, seed=5), horizon=1)
    labelled = features.loc[features["target"].notna()]
    report = fit_predict(features)
    y_test = labelled["target"].iloc[int(len(labelled) * 0.7):]
    nonzero = y_test[y_test != 0]

    assert report["backend"] == "xgboost"
    assert report["test_accuracy"] == pytest.approx(float((nonzero == -1).mean()))
