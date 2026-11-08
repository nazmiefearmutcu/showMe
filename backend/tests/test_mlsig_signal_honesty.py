"""MLSIG signal-honesty tests (MLSIG#2).

The signal must come from the model's prediction for the latest completed
bar, not from the test accuracy. Pre-fix, every symbol with accuracy >= 0.53
was labelled long_bias regardless of its current direction, and the reference
profile (which makes no prediction) emitted a bias from hard-coded accuracy.

No network: the market-data adapter is a fake and the ML backends are blocked
so the pure-NumPy lstsq path runs deterministically.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.mlsig import MLSIGFunction
from showme.engine.services.ml_signals import fit_predict, make_features


@pytest.fixture()
def no_ml_backends(monkeypatch: pytest.MonkeyPatch) -> None:
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


class _FakeYfinance:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        return self._frame


def test_latest_prediction_is_scored_on_the_newest_bar(no_ml_backends: None) -> None:
    """The latest call uses the newest completed bar (no forward label yet), not the last labelled row."""
    df = _random_walk_ohlcv()
    features = make_features(df, horizon=1)
    report = fit_predict(features)

    cols = [c for c in features.columns if c not in ("target", "fwd_ret_1")]
    labelled = features.loc[features["target"].notna()]
    split = int(len(labelled) * 0.7)
    yt = labelled["target"].iloc[:split].replace({-1: 0, 0: 0, 1: 1}).to_numpy(dtype=float)
    design = np.column_stack([np.ones(split), labelled[cols].iloc[:split].to_numpy()])
    beta, *_ = np.linalg.lstsq(design, yt, rcond=None)
    z_last = float(np.concatenate([[1.0], features[cols].iloc[-1].to_numpy()]) @ beta)
    expected_value = 1 if z_last > 0.5 else -1

    assert report["latest_prediction_value"] == expected_value
    assert report["latest_bar"].startswith(str(df.index[-1].date()))
    assert report["signal"] == {1: "long_bias", -1: "short_bias"}[expected_value]


def test_signal_comes_from_latest_prediction_not_accuracy(no_ml_backends: None) -> None:
    """Pre-fix: signal = long_bias whenever test accuracy >= 0.53, whatever the latest call."""
    df = _random_walk_ohlcv(n=900, seed=7)
    deps = FunctionDeps(yfinance=_FakeYfinance(df))
    out = asyncio.run(
        MLSIGFunction(deps).execute(symbol="EURUSD", asset_class="FX", days=900, horizon=1, live=True)
    )
    data = out.data

    assert data["status"] == "ok"
    assert data["latest_prediction"] in {"up", "down", "flat"}
    expected_signal = {"up": "long_bias", "down": "short_bias", "flat": "neutral"}[data["latest_prediction"]]
    assert data["signal"] == expected_signal
    assert data["latest_bar"].startswith(str(df.index[-1].date()))


def test_reference_model_does_not_emit_a_signal() -> None:
    """The deterministic reference profile has no prediction, so it must not label a bias."""
    out = asyncio.run(MLSIGFunction().execute(symbol="BTCUSDT", asset_class="CRYPTO", days=365))
    assert out.data["status"] == "needs_input"
    assert out.data["signal"] is None
    assert out.data["latest_prediction"] is None
