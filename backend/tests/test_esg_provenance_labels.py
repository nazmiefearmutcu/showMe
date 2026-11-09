"""ESG#5: provenance labels in the returned payload must match what was fetched.

Yahoo sustainability rows are a delayed reference, not a live feed, so they must
not carry a live_* label. The SEC EDGAR text proxy is a live fetch of filings, so
its data_mode must not claim a cached snapshot. No network: Yahoo is a fake
module injected into sys.modules and the EDGAR counts are monkeypatched."""
from __future__ import annotations

import asyncio
import json
import sys
import types

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
import showme.engine.functions.equity.esg as esg_mod
from showme.engine.functions.equity.esg import ESGFunction

_SUSTAINABILITY = {
    "totalEsg": 16.84,
    "environmentScore": 0.61,
    "socialScore": 7.42,
    "governanceScore": 8.81,
    "highestControversy": 3,
}


def _instrument(symbol: str = "AAPL") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)


def _fake_yfinance(monkeypatch) -> None:
    class _Ticker:
        def __init__(self, symbol: str) -> None:
            self.sustainability = dict(_SUSTAINABILITY)

    module = types.ModuleType("yfinance")
    module.Ticker = _Ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", module)


def test_yahoo_rows_are_labelled_delayed_reference_not_live(monkeypatch):
    _fake_yfinance(monkeypatch)
    result = asyncio.run(ESGFunction(FunctionDeps(yfinance=object())).execute(instrument=_instrument()))
    data = result.data
    assert data["status"] == "ok", data
    assert data["data_mode"] == "delayed_reference", data["data_mode"]
    assert data["rows"], data
    assert {row["source_mode"] for row in data["rows"]} == {"delayed_reference"}, data["rows"]
    assert "live_yfinance" not in json.dumps(data)


def test_edgar_proxy_is_labelled_live_official_not_cached_snapshot(monkeypatch):
    async def fake_counts(symbol: str) -> dict[str, int]:
        return {"environment": 3, "social": 5, "governance": 7}

    monkeypatch.setattr(esg_mod, "_fetch_proxy_counts", fake_counts)
    result = asyncio.run(ESGFunction(FunctionDeps()).execute(instrument=_instrument("ZZZZ")))
    data = result.data
    assert data["status"] == "ok", data
    assert data["data_mode"] == "live_official", data["data_mode"]
    assert {row["source_mode"] for row in data["rows"]} == {"sec_text_proxy"}
    assert "cached_snapshot" not in json.dumps(data)
    assert "not risk scores" in data["warnings"][0]
