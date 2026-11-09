"""MLSIG reference-path honesty tests (MLSIG#1, MLSIG#3 and the reference template).

When no live OHLCV model run exists, MLSIG must return an explicit missing-data
state. It must not serve hard-coded accuracy, Sharpe, feature importance or
sample counts from a per-asset-class profile table (data policy: never invent).

No network: the market-data adapter is a fake and no ML backend is needed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.mlsig import MLSIGFunction


_INVENTED_CONSTANTS = (0.42, 0.36, 0.31, 0.24, 0.28, 0.33, 0.56, 0.54, 0.53, 0.52, 0.55)


class _FakeYfinance:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        return self._frame


def _ohlcv(n: int) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    idx = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame(
        {"open": close, "high": close * 1.002, "low": close * 0.998, "close": close, "volume": np.full(n, 1000.0)},
        index=idx,
    )


def _assert_no_measured_values(data: dict[str, Any]) -> None:
    for key in ("test_accuracy", "strategy_sharpe", "latest_prediction", "latest_prediction_value", "signal", "backend"):
        assert data[key] is None, (key, data[key])
    assert data["feature_importance"] == {}
    assert data["rows"] == []
    assert data["summary"]["test_accuracy"] is None
    assert data["summary"]["strategy_sharpe"] is None
    assert data["summary"]["signal"] is None
    assert data["next_actions"], "an explicit missing-data state must say what to do next"
    flat = repr(data)
    for constant in _INVENTED_CONSTANTS:
        assert repr(constant) not in flat, constant


def test_default_call_without_live_run_is_needs_input_not_reference_metrics() -> None:
    out = asyncio.run(MLSIGFunction().execute(symbol="BTCUSDT", asset_class="CRYPTO", days=365))

    assert out.data["status"] == "needs_input"
    assert out.data["reason"]
    assert out.metadata["live"] is False
    assert out.metadata["rows"] == 0
    _assert_no_measured_values(out.data)


def test_every_asset_class_reference_path_is_explicit_and_identical_in_shape() -> None:
    for asset_class in ("CRYPTO", "EQUITY", "ETF", "FX", "COMMODITY", "INDEX", "BOND"):
        out = asyncio.run(MLSIGFunction().execute(symbol="X", asset_class=asset_class, days=252))
        assert out.data["status"] == "needs_input", asset_class
        _assert_no_measured_values(out.data)


def test_provider_unavailable_is_explicit_with_no_invented_metrics() -> None:
    out = asyncio.run(MLSIGFunction(FunctionDeps()).execute(symbol="EURUSD", asset_class="FX", live=True))

    assert out.data["status"] == "provider_unavailable"
    assert out.metadata["fallback"] is True
    _assert_no_measured_values(out.data)


def test_short_history_is_empty_state_not_a_template() -> None:
    deps = FunctionDeps(yfinance=_FakeYfinance(_ohlcv(150)))
    out = asyncio.run(MLSIGFunction(deps).execute(symbol="EURUSD", asset_class="FX", days=900, live=True))

    assert out.data["status"] == "empty"
    assert "150" in out.data["reason"]
    _assert_no_measured_values(out.data)
