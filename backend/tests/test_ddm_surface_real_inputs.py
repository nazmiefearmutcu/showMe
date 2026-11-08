"""DDM sensitivity surface must be a true Gordon grid (DDM#2).

Each surface cell is D1 / (r - g) with D1 = D0 * (1 + g) recomputed for the
cell's own growth column. Holding the base-case D1 fixed across growth columns
understates the growth sensitivity. The provider is faked; no network is used.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DDMFunction

MSFT = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)


class _Yf:
    def __init__(self, raw: dict) -> None:
        self._raw = raw

    async def fetch(self, request):
        return SimpleNamespace(extras={"raw": self._raw}, shares_outstanding=None)


def _run(**params):
    deps = FunctionDeps(yfinance=_Yf({"trailingAnnualDividendRate": 3.71, "dividendRate": 3.92}))
    return asyncio.run(DDMFunction(deps).execute(MSFT, **params))


def test_surface_cells_recompute_d1_for_each_growth_column() -> None:
    res = _run(required_return=0.09, growth_rate=0.03)
    assert res.data["status"] == "ok"
    d0 = res.data["dividend_ttm"]
    cells = {(c["required_return"], c["growth"]): c["value"] for c in res.data["surface"]}
    for (req, grow), value in cells.items():
        if req <= grow:
            assert value is None
            continue
        expected = d0 * (1 + grow) / (req - grow)
        # Red before the fix: the g-column cells reuse the base-case D1.
        assert value == expected_approx(expected), (req, grow, value, expected)


def expected_approx(x: float):
    import pytest

    return pytest.approx(x, rel=1e-9)
