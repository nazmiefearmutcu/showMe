"""WACC follow-ups (wc3-g07): WACC#5 assumptions and beta_window, WACC#3-RQ
ERP is never a constant and full country names reach the snapshot, WACC#6-RQ
the FRED BBB index is a labelled proxy. No network: every provider is faked.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.macro import damodaran_adapter as dmod
from showme.engine.functions.equity import wacc as wacc_mod
from showme.engine.functions.equity.wacc import WACCFunction


class _Refdata:
    def __init__(self) -> None:
        self.country = "US"
        self.market_cap = None
        self.extras = {"raw": {"marketCap": 300.0, "totalDebt": 100.0,
                               "sector": "Consumer Cyclical", "interestExpense": 5.0}}


class _FakeYf:
    def __init__(self, income: pd.DataFrame | None = None) -> None:
        self._income = income

    async def fetch(self, request):
        from showme.engine.core.base_data_source import DataKind
        if request.kind == DataKind.REFDATA:
            return _Refdata()
        if request.kind == DataKind.FUNDAMENTALS:
            if self._income is None:
                raise RuntimeError("no statements")
            return {"income": self._income}
        raise NotImplementedError


class _FakeFred:
    api_key = "test-key"

    def __init__(self, table: dict[str, float]) -> None:
        self._table = table

    async def series(self, sid: str, frequency: str = "d"):
        if sid not in self._table:
            return pd.DataFrame()
        return pd.DataFrame({"value": [self._table[sid]]})


class _Damo:
    def __init__(self, erp: float = 0.046, source: str = "damodaran_cache") -> None:
        self._erp, self._source = erp, source

    async def get_erp_with_source(self, country: str = "US"):
        return self._erp, self._source


class _RecordingBeta:
    """Records the windows asked for; answers only the first window requested."""
    calls: list[list[str]] = []

    def __init__(self, deps=None) -> None:
        self.deps = deps

    async def execute(self, instrument, **params):
        windows = list(params.get("windows") or [])
        _RecordingBeta.calls.append(windows)
        first = windows[0]
        return FunctionResult(
            code="BETA", instrument=instrument,
            data={"status": "ok", "betas": {first: {"beta": 1.3}}},
            sources=["yfinance"],
        )


def _deps(damodaran: Any = None) -> FunctionDeps:
    return FunctionDeps(
        yfinance=_FakeYf(),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}),
        damodaran=damodaran,
    )


def _run(deps: FunctionDeps, **params: Any):
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(WACCFunction(deps).execute(inst, **params))


@pytest.fixture(autouse=True)
def _beta(monkeypatch):
    _RecordingBeta.calls = []
    monkeypatch.setattr(wacc_mod, "BetaFunction", _RecordingBeta)


# ---- WACC#6-RQ: the FRED BBB index is a labelled proxy, not live ----------

def test_fred_bbb_index_cost_of_debt_is_partial_not_live() -> None:
    class _NoInterest(_Refdata):
        def __init__(self) -> None:
            super().__init__()
            self.extras = {"raw": {"marketCap": 300.0, "totalDebt": 100.0,
                                   "sector": "Consumer Cyclical"}}

    class _Yf(_FakeYf):
        async def fetch(self, request):
            from showme.engine.core.base_data_source import DataKind
            if request.kind == DataKind.REFDATA:
                return _NoInterest()
            return await super().fetch(request)

    deps = FunctionDeps(yfinance=_Yf(), fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}),
                        damodaran=_Damo())
    res = _run(deps)
    assert res.data["rd_source"] == "fred_bbb_yield"
    assert res.data["input_quality"]["rd"] == "partial"
    assert "rd" in res.data["partial_inputs"]
    assert res.data["data_state"] == "partial"


# ---- WACC#3-RQ: no ERP constant; full country names reach the snapshot ----

def test_erp_is_not_substituted_when_no_damodaran() -> None:
    res = _run(_deps(None))
    assert res.data["erp"] is None
    assert res.data["erp_source"] == "unavailable"
    assert res.data["status"] == "provider_unavailable"
    assert res.data["input_quality"]["erp"] == "missing"
    assert "equity risk premium" in res.data["reason"]


def test_user_market_premium_still_used_without_damodaran() -> None:
    res = _run(_deps(None), market_premium=0.06)
    assert res.data["erp"] == pytest.approx(0.06)
    assert res.data["erp_source"] == "user_input"
    assert res.data["status"] == "ok"


def test_snapshot_full_country_name_resolves_to_its_own_premium(monkeypatch) -> None:
    adapter = dmod.DamodaranAdapter()

    async def _snapshot():
        return dict(dmod._ERP_FALLBACK), dmod.SNAPSHOT_SOURCE

    monkeypatch.setattr(adapter, "_erp_table", _snapshot)
    erp, source = asyncio.run(adapter.get_erp_with_source("Spain"))
    assert erp == pytest.approx(0.0555)
    assert source == dmod.SNAPSHOT_SOURCE
    erp_tr, source_tr = asyncio.run(adapter.get_erp_with_source("Turkey"))
    assert erp_tr == pytest.approx(0.1412)
    assert source_tr == dmod.SNAPSHOT_SOURCE


def test_snapshot_unknown_country_is_labelled_unmatched_by_the_adapter(monkeypatch) -> None:
    # The adapter labels a country missing from its table; it is WACC that must
    # refuse the mature-market value under that label (see the WACC tests below).
    adapter = dmod.DamodaranAdapter()

    async def _snapshot():
        return dict(dmod._ERP_FALLBACK), dmod.SNAPSHOT_SOURCE

    monkeypatch.setattr(adapter, "_erp_table", _snapshot)
    _erp, source = asyncio.run(adapter.get_erp_with_source("Atlantis"))
    assert source == f"{dmod.SNAPSHOT_SOURCE}_country_unmatched"


# ---- WACC#3-RQ: a mature-market premium is never another country's ERP -----

class _UnmatchedDamo:
    """Returns the adapter's unmatched-country answer: the mature-market value."""

    async def get_erp_with_source(self, country: str = "US"):
        return 0.046, f"{dmod.SNAPSHOT_SOURCE}_country_unmatched"


def test_unmatched_country_erp_is_not_used_and_wacc_is_not_computed() -> None:
    deps = FunctionDeps(yfinance=_FakeYf(), fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}),
                        damodaran=_UnmatchedDamo())
    res = _run(deps)
    assert res.data["erp"] is None
    assert res.data["erp_source"] == "unavailable"
    assert res.data["erp_country"] is None
    assert res.data["input_quality"]["erp"] == "missing"
    assert "erp" not in {k for k, v in res.data["input_quality"].items() if v == "partial"}
    assert res.data["status"] == "provider_unavailable"
    assert res.data["data_state"] == "provider_unavailable"
    assert res.data["wacc"] is None
    assert res.data["re_capm"] is None
    assert any("mature-market" in w and "not used" in w for w in res.warnings)


def test_unmatched_country_erp_field_dictionary_no_longer_describes_a_constant() -> None:
    deps = FunctionDeps(yfinance=_FakeYf(), fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}),
                        damodaran=_UnmatchedDamo())
    res = _run(deps)
    dictionary = res.data["field_dictionary"]
    assert "5.0%" not in dictionary["erp_country"]
    assert "5.0%" not in dictionary["erp_source"]
    assert "5.0%" not in dictionary["erp"]
    assert "no mature-market value is substituted" in dictionary["erp_source"]


# ---- WACC#5: assumptions are echoed; beta_window is honoured ---------------

def test_assumptions_are_echoed_in_output() -> None:
    res = _run(_deps(_Damo()), market_premium=0.06, tax_rate_override=0.25)
    assumptions = res.data["assumptions"]
    assert assumptions["market_premium"] == pytest.approx(0.06)
    assert assumptions["tax_rate_override"] == pytest.approx(0.25)
    assert assumptions["beta_window"] is None
    assert assumptions["beta_window_applied"] == "5Y"


def test_beta_window_252d_is_asked_first_and_echoed() -> None:
    res = _run(_deps(_Damo()), beta_window="252d")
    assert _RecordingBeta.calls and _RecordingBeta.calls[0][0] == "1Y"
    assert res.data["beta_window"] == "1Y"
    assert res.data["assumptions"]["beta_window"] == "252d"
    assert res.data["assumptions"]["beta_window_applied"] == "1Y"


def test_unsupported_beta_window_is_warned_not_silently_dropped() -> None:
    res = _run(_deps(_Damo()), beta_window="60d")
    assert res.data["assumptions"]["beta_window"] == "60d"
    assert any("60d" in w for w in res.warnings)


def test_default_beta_window_keeps_long_window_preference() -> None:
    res = _run(_deps(_Damo()))
    assert _RecordingBeta.calls[0] == ["5Y", "2Y", "1Y"]
    assert res.data["beta_window"] == "5Y"
