"""MLSIG#5 regression: declared inputs must either run or be reported as not run.

The seed declares label_horizon, model_family, feature_set, label_type,
train_pct and frequency. Before the fix only horizon/days/interval were read,
so label_horizon=5 silently ran a 1-bar label and model_family=lightgbm silently
ran the NumPy linear-probability backend. These tests pin that:

* label_horizon is the horizon that is actually used (and is echoed back);
* a requested option that cannot run is listed under ignored_options with the
  backend that actually ran, rather than dropped without a trace.

No network: the market-data adapter is a fake and the ML backends are blocked so
the NumPy path runs deterministically.
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


class _FakeYfinance:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        return self._frame


def _random_walk(n: int = 900, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    idx = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame(
        {"open": close, "high": close * 1.002, "low": close * 0.998, "close": close,
         "volume": np.full(n, 1000.0)},
        index=idx,
    )


@pytest.fixture()
def numpy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("lightgbm", "xgboost", "sklearn", "sklearn.ensemble"):
        monkeypatch.setitem(sys.modules, name, None)


def _run(**params: Any):
    deps = FunctionDeps(yfinance=_FakeYfinance(_random_walk()))
    return asyncio.run(MLSIGFunction(deps).execute(symbol="AAPL", asset_class="EQUITY", live=True, **params))


def test_label_horizon_is_the_horizon_that_runs(numpy_backend) -> None:
    out = _run(label_horizon=5, horizon=1)

    assert out.data["horizon_days"] == 5
    assert out.metadata["horizon"] == 5


def test_legacy_horizon_input_still_works(numpy_backend) -> None:
    out = _run(horizon=3)

    assert out.data["horizon_days"] == 3


def test_requested_options_that_do_not_run_are_reported(numpy_backend) -> None:
    out = _run(
        label_horizon=5,
        model_family="lightgbm",
        feature_set=["returns_1d", "rsi_14"],
        label_type="regression_return",
    )

    assert out.data["backend"] == "lstsq_linear_probability"
    ignored = {row["option"]: row for row in out.data["ignored_options"]}
    assert set(ignored) == {"model_family", "feature_set", "label_type"}
    assert ignored["model_family"]["requested"] == "lightgbm"
    assert ignored["model_family"]["used"] == "lstsq_linear_probability"
    assert ignored["feature_set"]["used"] == "fixed built-in feature set"


def test_options_that_match_what_runs_are_not_listed_as_ignored(numpy_backend) -> None:
    out = _run(label_horizon=1, label_type="binary_updown", train_pct=0.7, model_family="ridge")

    options = {row["option"] for row in out.data["ignored_options"]}
    assert "label_type" not in options
    assert "train_pct" not in options
    assert "model_family" in options, "ridge is not run, so it must be reported"
