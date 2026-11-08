"""P2A-G06 FXH#6 regression: portfolio mode with a foreign position whose spot fails.

When the portfolio holds a non-home-currency position but the spot provider
fails, the honest answer is data_unavailable with the spot-provider reason.
It must NOT be reported as an empty book ("no non-home-currency positions").

All tests run offline: yfinance is a stub and PortfolioState is patched.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.fx.fxh import FXHFunction
from showme.engine.portfolio.state import PortfolioPosition


def _run(coro):
    return asyncio.run(coro)


class _FakePortfolio:
    def __init__(self, positions):
        self.positions = positions

    def import_legacy_crypto(self):
        return 0


def _patch_portfolio(monkeypatch, positions) -> None:
    import showme.engine.portfolio.state as state_mod

    monkeypatch.setattr(state_mod, "PortfolioState", lambda *a, **k: _FakePortfolio(positions))


def _eur_position() -> PortfolioPosition:
    return PortfolioPosition(
        instrument=Instrument(symbol="SAP.DE", asset_class=AssetClass.EQUITY),
        quantity=10, avg_cost=150.0, currency="EUR",
    )


class _RaisingYF:
    async def fetch(self, req):
        raise RuntimeError("provider down")


class _ZeroYF:
    class _Quote:
        last = 0.0

    async def fetch(self, req):
        return self._Quote()


@pytest.mark.parametrize("yf", [_RaisingYF(), _ZeroYF()], ids=["raises", "zero_last"])
def test_fxh6_foreign_position_with_failed_spot_is_data_unavailable(monkeypatch, yf) -> None:
    _patch_portfolio(monkeypatch, [_eur_position()])
    result = _run(FXHFunction(deps=FunctionDeps(yfinance=yf)).execute(
        action="calc", pair="EURUSD", use_portfolio=True,
    ))

    assert result.data["status"] == "data_unavailable"
    assert result.data["rows"] == []
    reason = result.data["reason"].lower()
    assert "spot" in reason
    assert "non-home" not in reason
    assert any("EUR" in w for w in result.warnings)


def test_fxh6_foreign_position_with_failed_spot_not_reported_as_empty(monkeypatch) -> None:
    _patch_portfolio(monkeypatch, [_eur_position()])
    result = _run(FXHFunction(deps=FunctionDeps(yfinance=_RaisingYF())).execute(
        action="calc", pair="EURUSD", use_portfolio=True,
    ))
    assert result.data["status"] != "empty"
