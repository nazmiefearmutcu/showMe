"""RPAR must not serve invented weights (RPAR#4 follow-up, data policy).

Pre-fix, the default no-yfinance path returned a hard-coded per-class volatility
template (0.58 / 0.28 / 0.11 / 0.32) and ignored the declared risk_target and
covariance_model. The live path with too little history also built weights from
a synthetic cosine return series. Both must now return an explicit state that
echoes the requested controls and carries no weights.

No network: the Yahoo fallback is patched and yfinance is a fake.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio import rpar as rpar_mod
from showme.engine.functions.portfolio.rpar import RPARFunction


_TEMPLATE_VOLS = (0.58, 0.28, 0.32)


def _assert_explicit_no_weights(data: dict[str, Any]) -> None:
    assert data["status"] in {"provider_unavailable", "needs_input"}
    assert data["reason"]
    assert data["next_actions"]
    assert data["weights"] == {}
    assert data["rows"] == []
    assert data["portfolio_vol"] is None
    assert data["gross_exposure"] is None
    flat = repr(data)
    for vol in _TEMPLATE_VOLS:
        assert repr(vol) not in flat, vol


def test_default_without_yfinance_echoes_controls_and_invents_nothing() -> None:
    out = asyncio.run(
        RPARFunction().execute(symbols="AAPL,MSFT,BTCUSDT", risk_target=0.10, covariance_model="ledoit_wolf")
    )

    _assert_explicit_no_weights(out.data)
    assert out.data["status"] == "provider_unavailable"
    assert out.data["risk_target"] == pytest.approx(0.10)
    assert out.data["covariance_model_requested"] == "ledoit_wolf"
    assert out.data["symbols"] == ["AAPL", "MSFT", "BTCUSDT"]
    assert out.sources == []
    assert out.metadata["fallback"] is True


def test_model_true_is_explicit_and_never_reads_yfinance() -> None:
    class _NeverCalled:
        async def fetch(self, *_a: Any, **_kw: Any) -> pd.DataFrame:  # pragma: no cover
            raise AssertionError("yfinance must not be read when model=true")

    out = asyncio.run(
        RPARFunction(FunctionDeps(yfinance=_NeverCalled())).execute(symbols="AAPL,MSFT", model=True, risk_target=0.08)
    )

    _assert_explicit_no_weights(out.data)
    assert out.data["status"] == "needs_input"
    assert out.data["risk_target"] == pytest.approx(0.08)
    assert out.metadata["fallback_reason"] == "model_requested"


def test_insufficient_history_is_explicit_not_a_synthetic_return_series(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ShortHistory:
        async def fetch(self, request: Any, *_a: Any, **_kw: Any) -> pd.DataFrame:
            idx = pd.bdate_range(end="2026-10-30", periods=5)
            return pd.DataFrame({"close": np.linspace(100.0, 101.0, 5)}, index=idx)

    async def _no_yahoo(*_a: Any, **_kw: Any) -> pd.Series:
        return pd.Series(dtype=float)

    monkeypatch.setattr(rpar_mod, "_yahoo_daily_returns", _no_yahoo)
    out = asyncio.run(
        RPARFunction(FunctionDeps(yfinance=_ShortHistory())).execute(
            symbols="AAA,BBB", method="erc", live_risk=True, risk_target=0.10
        )
    )

    _assert_explicit_no_weights(out.data)
    assert out.data["status"] == "provider_unavailable"
    assert "insufficient" in out.data["reason"]
    assert out.sources == []
