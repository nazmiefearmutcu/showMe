"""DCFS#3/#4: the grid is centred on the effective inputs, grid_width per axis."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import dcfs as dcfs_mod


class _FakeDCF:
    """Records calls; fair value = 100 / (rate - g) so cells are distinct."""
    calls: list[dict[str, Any]] = []

    def __init__(self, deps: Any) -> None:  # noqa: ARG002
        pass

    async def execute(self, instrument: Any, **params: Any) -> FunctionResult:
        _FakeDCF.calls.append(params)
        rate = float(params.get("wacc", 0.10))
        g = float(params.get("growth_terminal", 0.025))
        fv = 100.0 / (rate - g) if rate > g else None
        return FunctionResult(code="DCF", instrument=instrument, data={
            "fair_value_per_share": fv, "equity_value": fv, "discount_rate": rate,
            "g_terminal": g, "starting_fcfe": 1e9, "shares_outstanding": 1e7,
        })


@pytest.fixture(autouse=True)
def fake_dcf(monkeypatch):
    _FakeDCF.calls = []
    monkeypatch.setattr(dcfs_mod, "DCFFunction", _FakeDCF)


def _run(**params):
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(dcfs_mod.DCFSensitivityFunction(None).execute(instrument=inst, **params))


def test_default_grid_is_5x5_centred_on_the_effective_rate() -> None:
    res = _run()
    data = res.data
    assert data["grid_width"] == 5
    assert len(data["grid"]) == 25
    assert data["wacc_range"] == pytest.approx([0.09, 0.095, 0.10, 0.105, 0.11])
    assert data["g_range"] == pytest.approx([0.02, 0.0225, 0.025, 0.0275, 0.03])


def test_user_discount_rate_and_terminal_growth_centre_the_grid() -> None:
    res = _run(discount_rate=0.12, terminal_growth=0.02, grid_width=3)
    data = res.data
    assert data["wacc_range"] == pytest.approx([0.115, 0.12, 0.125])
    assert data["g_range"] == pytest.approx([0.0175, 0.02, 0.0225])
    assert len(data["grid"]) == 9
    assert _FakeDCF.calls[0]["wacc"] == 0.12
    assert _FakeDCF.calls[0]["growth_terminal"] == 0.02


def test_growth_rate_is_the_stage_one_growth() -> None:
    _run(growth_rate=0.05)
    assert all(call["growth_high"] == 0.05 for call in _FakeDCF.calls)


def test_route_no_longer_injects_a_3x2_grid() -> None:
    from showme.server_routes._agent_runtime import _route_function_params

    routed = _route_function_params("DCFS", {"symbol": "AAPL"})
    assert "wacc_range" not in routed and "g_range" not in routed
