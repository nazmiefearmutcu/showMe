"""WACC#3 (wc1-g34): the Damodaran ERP is looked up for the issuer's own country.

An issuer whose country cannot be resolved must not be priced with the US
premium, and a failed country lookup must be reported, not swallowed. The
adapter must not default a missing country to "US" either, and a country
given by its full name (as yfinance reports it) must match the table.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import wacc as wacc_mod
from showme.engine.functions.equity.wacc import WACCFunction


class _StubBeta:
    def __init__(self, deps=None) -> None:
        self.deps = deps

    async def execute(self, instrument, **params):
        return FunctionResult(
            code="BETA", instrument=instrument,
            data={"status": "ok", "betas": {"5Y": {"beta": 1.2}}},
            sources=["yfinance"],
        )


class _RefdataPayload:
    def __init__(self, country: str | None) -> None:
        self.country = country
        self.market_cap = None
        self.extras = {"raw": {"marketCap": 300.0, "totalDebt": 100.0, "sector": "Consumer Cyclical"}}


class _FakeYf:
    """REFDATA returns the given country; REFDATA can be made to fail."""

    def __init__(self, country: str | None, refdata_error: Exception | None = None) -> None:
        self._country = country
        self._refdata_error = refdata_error

    async def fetch(self, request):
        from showme.engine.core.base_data_source import DataKind
        if request.kind == DataKind.REFDATA:
            if self._refdata_error is not None:
                raise self._refdata_error
            return _RefdataPayload(self._country)
        if request.kind == DataKind.FUNDAMENTALS:
            raise RuntimeError("no statements")
        raise NotImplementedError


class _FakeFred:
    api_key = "test-key"

    async def series(self, sid: str, frequency: str = "d"):
        table = {"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}
        if sid not in table:
            return pd.DataFrame()
        return pd.DataFrame({"value": [table[sid]]})


class _RecordingDamodaran:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def get_erp_with_source(self, country):
        self.calls.append(country)
        return 0.039, "damodaran_cache"


def _instrument() -> Instrument:
    return Instrument(symbol="ISSUER", asset_class=AssetClass.EQUITY)


def _run(country: str | None, damo: Any, refdata_error: Exception | None = None):
    deps = FunctionDeps(
        yfinance=_FakeYf(country, refdata_error),
        fred=_FakeFred(),
        damodaran=damo,
    )
    return asyncio.run(WACCFunction(deps).execute(_instrument()))


@pytest.fixture(autouse=True)
def _stub_beta(monkeypatch):
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBeta)


def test_unknown_issuer_country_is_not_priced_with_the_us_premium() -> None:
    damo = _RecordingDamodaran()
    res = _run(country=None, damo=damo)
    assert damo.calls == []
    assert res.data["erp_source"] == "assumption_default_5pct"
    assert any("country" in w.lower() for w in res.warnings)


def test_failed_country_lookup_is_reported_and_not_defaulted_to_us() -> None:
    damo = _RecordingDamodaran()
    res = _run(country=None, damo=damo, refdata_error=RuntimeError("refdata down"))
    assert damo.calls == []
    assert res.data["erp_source"] == "assumption_default_5pct"
    assert any("refdata down" in w for w in res.warnings)


def test_known_issuer_country_is_the_one_looked_up() -> None:
    damo = _RecordingDamodaran()
    res = _run(country="Germany", damo=damo)
    assert damo.calls == ["Germany"]
    assert res.data["erp_source"] == "damodaran_cache"
    assert res.data["erp"] == pytest.approx(0.039)


def test_adapter_requires_a_country_and_never_defaults_to_us(tmp_path, monkeypatch) -> None:
    from showme.engine.data_sources.macro import damodaran_adapter as dm

    monkeypatch.setattr(dm, "_cache_path", lambda: tmp_path / "damodaran_erp.json")
    adapter = dm.DamodaranAdapter()
    for missing in ("", None):
        with pytest.raises(ValueError):
            asyncio.run(adapter.get_erp_with_source(missing))


def test_adapter_matches_full_country_names_from_a_live_table(tmp_path, monkeypatch) -> None:
    from showme.engine.data_sources.macro import damodaran_adapter as dm

    monkeypatch.setattr(dm, "_cache_path", lambda: tmp_path / "damodaran_erp.json")
    (tmp_path / "damodaran_erp.json").write_text(json.dumps({
        "ts": int(time.time()),
        "payload": {"United States": 4.2, "Germany": 3.9, "_global": 4.6},
    }))
    adapter = dm.DamodaranAdapter()
    erp, source = asyncio.run(adapter.get_erp_with_source("Germany"))
    assert erp == pytest.approx(0.039)
    assert source == "damodaran_cache"
    erp, source = asyncio.run(adapter.get_erp_with_source("United States"))
    assert erp == pytest.approx(0.042)
    assert source == "damodaran_cache"


def test_adapter_treats_us_and_united_states_as_the_same_country(tmp_path, monkeypatch) -> None:
    from showme.engine.data_sources.macro import damodaran_adapter as dm

    monkeypatch.setattr(dm, "_cache_path", lambda: tmp_path / "damodaran_erp.json")
    (tmp_path / "damodaran_erp.json").write_text(json.dumps({
        "ts": int(time.time()),
        "payload": {"United States": 4.2, "_global": 4.6},
    }))
    adapter = dm.DamodaranAdapter()
    erp, source = asyncio.run(adapter.get_erp_with_source("US"))
    assert erp == pytest.approx(0.042)
    assert not source.endswith("_country_unmatched")


def test_erp_country_names_the_country_whose_premium_is_used() -> None:
    res = _run(country="Germany", damo=_RecordingDamodaran())
    assert res.data["erp_country"] == "Germany"


def test_erp_country_is_null_when_no_country_premium_is_used() -> None:
    res = _run(country=None, damo=_RecordingDamodaran())
    assert res.data["erp_country"] is None


def test_erp_country_is_null_for_an_unmatched_country() -> None:
    class _UnmatchedDamo(_RecordingDamodaran):
        async def get_erp_with_source(self, country):
            self.calls.append(country)
            return 0.046, "damodaran_snapshot_2025_01_country_unmatched"

    res = _run(country="Zz", damo=_UnmatchedDamo())
    assert res.data["erp_country"] is None
    assert res.data["erp_source"].endswith("_country_unmatched")
