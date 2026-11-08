"""MLSIG#6 regression: an explicit live_ml=false must not be overridden by the routed live=true.

The agent router injects live=true for every routed call. The pane sends
live_ml=false for MODEL. The old expression `live_ml or live_returns or live`
let the routed default win, so MODEL still trained on live OHLCV. These tests
pin that an explicit value wins and the routed default applies only when the
caller sent no live flag.

No network: the OHLCV adapter is a fake that records whether it was called.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.mlsig import MLSIGFunction


class _RecordingYfinance:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame
        self.calls = 0

    async def fetch(self, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        self.calls += 1
        return self._frame


def _frame(n: int = 900) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    idx = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"open": close, "high": close * 1.002, "low": close * 0.998, "close": close,
                         "volume": np.full(n, 1000.0)}, index=idx)


def _run(params: dict[str, Any]):
    fake = _RecordingYfinance(_frame())
    out = asyncio.run(MLSIGFunction(FunctionDeps(yfinance=fake)).execute(symbol="AAPL", asset_class="EQUITY", **params))
    return out, fake


@pytest.fixture()
def numpy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    for name in ("lightgbm", "xgboost", "sklearn", "sklearn.ensemble"):
        monkeypatch.setitem(sys.modules, name, None)


def test_explicit_live_ml_false_wins_over_routed_live_true() -> None:
    out, fake = _run({"live_ml": False, "live": True})

    assert fake.calls == 0, "MODEL must not fetch live OHLCV"
    assert out.data["status"] == "needs_input"
    assert out.metadata["live"] is False


def test_explicit_live_ml_string_false_wins_over_routed_live_true() -> None:
    out, fake = _run({"live_ml": "false", "live": True})

    assert fake.calls == 0
    assert out.data["status"] == "needs_input"


def test_explicit_live_ml_true_runs_live(numpy_backend) -> None:
    out, fake = _run({"live_ml": True, "live": False})

    assert fake.calls == 1
    assert out.metadata["live"] is True


def test_routed_live_true_without_live_ml_still_runs_live(numpy_backend) -> None:
    out, fake = _run({"live": True})

    assert fake.calls == 1
    assert out.metadata["live"] is True


def test_no_live_flag_at_all_stays_reference_state() -> None:
    out, fake = _run({})

    assert fake.calls == 0
    assert out.data["status"] == "needs_input"
