"""An empty Finnhub profile must not become a zero-sized company (DES#2 review)."""
from __future__ import annotations

import asyncio

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity.finnhub_adapter import FinnhubAdapter, _millions


def test_millions_helper():
    assert _millions(2950.5) == 2_950_500_000.0
    assert _millions(None) is None
    assert _millions(0) is None
    assert _millions("") is None


def test_empty_profile_gives_unknown_size_not_zero(monkeypatch):
    adapter = FinnhubAdapter.__new__(FinnhubAdapter)

    async def _empty(*_a, **_k):
        return {}

    monkeypatch.setattr(adapter, "_get", _empty, raising=False)
    monkeypatch.setattr(adapter, "name", "finnhub", raising=False)
    req = DataRequest(kind=DataKind.REFDATA, instrument=Instrument(symbol="XYZQ", asset_class=AssetClass.EQUITY))
    rd = asyncio.run(adapter.fetch(req))
    assert rd.market_cap is None
    assert rd.shares_outstanding is None
