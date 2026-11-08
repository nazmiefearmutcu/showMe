"""WACC#1 / WACC#2 regressions.

WACC#1: the pre-tax cost of debt must be a corporate YIELD. The keyless FRED
series BAMLC0A4CBBB is the ICE BofA BBB option-adjusted SPREAD (percent), which
is not a cost of debt. The yield series is BAMLC0A4CBBBEY.

WACC#2: a bank or insurer funds itself with deposits / policy reserves, so a
book-debt capital-structure weight is meaningless. WACC is reported as not
applicable (explicit state) instead of a live 60% debt weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.wacc import WACCFunction


@dataclass
class _RefdataPayload:
    market_cap: float | None = None
    country: str | None = "US"
    extras: dict | None = None


class _FakeYf:
    def __init__(self, *, raw: dict[str, Any]) -> None:
        self._raw = raw

    async def fetch(self, request):
        from showme.engine.core.base_data_source import DataKind
        if request.kind == DataKind.REFDATA:
            return _RefdataPayload(
                market_cap=self._raw.get("marketCap"),
                country=self._raw.get("country", "US"),
                extras={"raw": dict(self._raw)},
            )
        raise NotImplementedError


class _FakeFred:
    api_key = "test-key"  # keyed fake wins over the keyless CSV shim

    def __init__(self, by_series: dict[str, float]) -> None:
        self._by = by_series

    async def series(self, sid: str, frequency: str = "d"):
        value = self._by.get(sid)
        if value is None:
            return pd.DataFrame()
        return pd.DataFrame({"value": [value]})


def _instrument(symbol: str) -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)


@pytest.mark.asyncio
async def test_rd_is_bbb_yield_not_option_adjusted_spread():
    """FRED BAMLC0A4CBBB (spread, 1.16) must not be used; BAMLC0A4CBBBEY (yield, 5.93) is."""
    raw = {"marketCap": 100.0, "totalDebt": 25.0, "sector": "Technology"}
    deps = FunctionDeps(
        yfinance=_FakeYf(raw=raw),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBB": 1.16, "BAMLC0A4CBBBEY": 5.93, "AAA": 4.8}),
    )
    res = await WACCFunction(deps).execute(instrument=_instrument("ACME"), beta=1.1)
    assert res.data["rd"] == pytest.approx(0.0593, abs=1e-9)
    assert res.data["rd_source"] == "fred_bbb_yield"
