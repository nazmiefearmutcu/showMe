"""BTUNE#1 regression: the non-live and unavailable paths never report metrics.

Network is never touched; the yfinance adapter is replaced by an in-memory fake.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.btune import BTUNEFunction


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def equity() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _FakeYF:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    async def fetch(self, request):  # noqa: ARG002 - mirrors the adapter signature
        return self.frame


class _EmptyYF:
    async def fetch(self, request):  # noqa: ARG002
        return pd.DataFrame()


# ── BTUNE#1: no invented metrics on the non-live / unavailable paths ─────


def test_btune_non_live_reports_no_metrics(equity):
    """Default (live off) must not present reference metrics as results."""
    res = _run(BTUNEFunction(FunctionDeps()).execute(instrument=equity))
    assert res.data["status"] == "needs_input"
    assert res.data["combos_tested"] == 0
    assert res.data["best_params"] is None
    assert res.warnings, "non-live path must explain why no metrics exist"
    for row in res.data["rows"]:
        assert row["sharpe"] is None
        assert row["total_return"] is None
        assert row["calmar"] is None


def test_btune_live_without_ohlcv_never_substitutes_synthetic_history(equity):
    """When live OHLCV is unavailable the sweep must not run on a generated
    sine/trend series and report its metrics."""
    deps = FunctionDeps(yfinance=_EmptyYF())
    res = _run(BTUNEFunction(deps).execute(instrument=equity, live_backtest=True, days=120))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["best_params"] is None
    assert res.sources == []
    assert res.metadata.get("live") is False
    assert all(row["sharpe"] is None for row in res.data["rows"])
    assert any("live OHLCV" in w or "yfinance" in w for w in res.warnings)




def test_btune_explicit_model_toggle_wins_over_generic_live(equity):
    """BTUNE#2: live_backtest=false (the pane's MODEL toggle) must not be
    overruled by a generic live=true."""
    res = _run(BTUNEFunction(FunctionDeps()).execute(instrument=equity, live_backtest=False, live=True))
    assert res.data["status"] == "needs_input"
    assert res.data["combos_tested"] == 0
