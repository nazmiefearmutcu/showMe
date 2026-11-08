"""MLSIG#7 regression: test accuracy needs a baseline and an interval.

With roughly 70 scored test rows the standard error of accuracy is about six
points, so a bare accuracy figure reads as more precise than it is. These tests
pin that the report carries the always-long baseline (share of up labels among
scored test rows), the number of scored rows, and a 95% Wilson interval around
the accuracy. Explicit missing-data states carry the same keys as null.

No network: the ML backends are blocked so the NumPy path runs deterministically.
"""

from __future__ import annotations

import asyncio
import math
import sys
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.mlsig import MLSIGFunction
from showme.engine.services.ml_signals import fit_predict, make_features


@pytest.fixture()
def numpy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("lightgbm", "xgboost", "sklearn", "sklearn.ensemble"):
        monkeypatch.setitem(sys.modules, name, None)


def _random_walk(n: int = 900, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = rng.integers(1_000, 5_000, n).astype(float)
    idx = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def _expected_baseline_and_counts(features: pd.DataFrame, horizon: int) -> tuple[float, int]:
    labelled = features.loc[features["target"].notna()]
    split = int(len(labelled) * 0.7)
    y_test = labelled["target"].iloc[split:].to_numpy()
    nonzero = y_test[y_test != 0]
    return float((nonzero == 1).mean()), int(nonzero.size)


def test_report_carries_always_long_baseline_and_scored_count(numpy_backend) -> None:
    features = make_features(_random_walk(), horizon=1)
    report = fit_predict(features)

    baseline, scored = _expected_baseline_and_counts(features, horizon=1)
    assert report["test_baseline_always_long_accuracy"] == pytest.approx(baseline, rel=1e-12)
    assert report["scored_samples"] == scored


def test_report_carries_wilson_interval_around_accuracy(numpy_backend) -> None:
    features = make_features(_random_walk(), horizon=1)
    report = fit_predict(features)

    low, high = report["test_accuracy_ci95"]
    assert 0.0 <= low <= report["test_accuracy"] <= high <= 1.0
    assert high - low > 0.0


def test_wilson_interval_matches_reference_formula(numpy_backend) -> None:
    from showme.engine.services import ml_signals

    correct, n = 39, 69
    z = 1.959963984540054
    p = correct / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom

    low, high = ml_signals._wilson_interval(correct, n)
    assert low == pytest.approx(centre - half, rel=1e-9)
    assert high == pytest.approx(centre + half, rel=1e-9)


def test_function_output_includes_baseline_and_interval(numpy_backend) -> None:
    deps = FunctionDeps(yfinance=_FakeYfinance(_random_walk()))
    out = asyncio.run(MLSIGFunction(deps).execute(symbol="AAPL", asset_class="EQUITY", live=True))

    assert out.data["status"] == "ok"
    assert out.data["test_baseline_always_long_accuracy"] is not None
    assert out.data["test_accuracy_ci95"] is not None
    assert out.data["scored_samples"] > 0


def test_missing_data_state_has_the_same_keys_as_null() -> None:
    out = asyncio.run(MLSIGFunction().execute(symbol="AAPL", asset_class="EQUITY", days=252))

    assert out.data["status"] == "needs_input"
    assert out.data["test_baseline_always_long_accuracy"] is None
    assert out.data["test_accuracy_ci95"] is None
    assert out.data["scored_samples"] == 0


class _FakeYfinance:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        return self._frame
