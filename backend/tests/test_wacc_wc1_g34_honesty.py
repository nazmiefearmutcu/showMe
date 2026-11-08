"""WACC honesty regressions (wc1-g34): T10, WACC#3, WACC#4, WACC#6.

No input may be a silent constant. A missing market input (beta, risk-free
rate, cost of debt, capital-structure weights) makes WACC an explicit
provider_unavailable state with reason and next_actions; the components
that are real stay reported. Labelled model assumptions (ERP default, the
statutory tax rate) keep status ok but set data_state to "partial".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import wacc as wacc_mod
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
    api_key = "test-key"

    def __init__(self, by_series: dict[str, float]) -> None:
        self._by = by_series

    async def series(self, sid: str, frequency: str = "d"):
        value = self._by.get(sid)
        if value is None:
            return pd.DataFrame()
        return pd.DataFrame({"value": [value]})


class _FakeDamodaran:
    """Stands in for DamodaranAdapter; returns (erp, source) like get_erp_with_source."""

    def __init__(self, erp: float = 0.046, source: str = "damodaran_cache") -> None:
        self._erp, self._source = erp, source

    async def get_erp_with_source(self, country: str = "US"):
        return self._erp, self._source


class _StubBeta:
    def __init__(self, deps=None) -> None:
        self.deps = deps

    async def execute(self, instrument, **params):
        from showme.engine.core.base_function import FunctionResult
        return FunctionResult(
            code="BETA",
            instrument=instrument,
            data={"status": "ok", "betas": {"5Y": {"beta": 1.2}}},
            sources=["yfinance"],
        )


class _BrokenBeta:
    def __init__(self, deps=None) -> None:
        self.deps = deps

    async def execute(self, instrument, **params):
        raise RuntimeError("yfinance offline")


_FULL_RAW = {"marketCap": 300.0, "totalDebt": 100.0, "sector": "Consumer Cyclical"}


def _instrument(symbol: str = "AAPL") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)


def _deps(*, raw: dict[str, Any] | None = None, fred: dict[str, float] | None = None,
          damodaran: Any = None) -> FunctionDeps:
    fred_table = {"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93} if fred is None else fred
    return FunctionDeps(
        yfinance=_FakeYf(raw=_FULL_RAW if raw is None else raw),
        fred=_FakeFred(fred_table),
        damodaran=damodaran,
    )


def _run(deps: FunctionDeps, **params: Any):
    return asyncio.run(WACCFunction(deps).execute(_instrument(), **params))


# ---- T10: beta outage must not become a synthetic ok result --------------


def test_t10_beta_outage_is_provider_unavailable_not_synthetic_ok(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _BrokenBeta)
    res = _run(_deps(damodaran=_FakeDamodaran()))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["wacc"] is None
    assert res.data["beta"] is None
    assert "synthetic_beta" not in res.sources
    assert res.data["reason"]
    assert res.data["next_actions"]


def test_t10_no_beta_substitute_of_one(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _BrokenBeta)
    res = _run(_deps(damodaran=_FakeDamodaran()))
    assert res.data["beta"] != 1.0
    assert res.data["re_capm"] is None


def test_user_beta_still_computes_wacc(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _BrokenBeta)
    res = _run(_deps(damodaran=_FakeDamodaran()), beta=1.1)
    assert res.data["status"] == "ok"
    assert res.data["beta"] == pytest.approx(1.1)
    assert res.data["wacc"] is not None


def test_missing_risk_free_rate_is_not_replaced_by_four_percent(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBeta)
    res = _run(_deps(fred={"BAMLC0A4CBBBEY": 5.93}, damodaran=_FakeDamodaran()))
    assert res.data["rf"] is None
    assert res.data["status"] == "provider_unavailable"
    assert res.data["wacc"] is None
    assert "fred" not in res.sources


def test_missing_cost_of_debt_is_not_replaced_by_five_point_five(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBeta)
    res = _run(_deps(fred={"DGS10": 4.0}, damodaran=_FakeDamodaran()))
    assert res.data["rd"] is None
    assert res.data["status"] == "provider_unavailable"
    assert res.data["wacc"] is None


def test_missing_capital_structure_is_not_a_70_30_default(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBeta)
    res = _run(_deps(raw={"sector": "Consumer Cyclical"}, damodaran=_FakeDamodaran()))
    assert res.data["equity_weight"] is None
    assert res.data["debt_weight"] is None
    assert res.data["status"] == "provider_unavailable"
    assert res.data["wacc"] is None


# ---- WACC#3: the ERP is never a silent constant --------------------------


def test_wacc3_router_does_not_inject_a_constant_erp() -> None:
    """The agent router used to inject erp=0.05, which bypassed Damodaran and
    was reported with no source. The routed WACC request must leave ERP to the
    function, which resolves it from Damodaran and labels the source."""
    from showme.manifest import load_seeds
    from showme.server_routes._agent_runtime import _route_function_params

    load_seeds()
    routed = _route_function_params("WACC", {"symbol": "AAPL"})
    assert "erp" not in routed


def test_wacc3_damodaran_erp_is_labelled_with_its_source(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_deps(damodaran=_FakeDamodaran(0.046, "damodaran_cache")))
    assert res.data["erp"] == pytest.approx(0.046)
    assert res.data["erp_source"] == "damodaran_cache"
    assert "damodaran" in res.sources


def test_wacc3_snapshot_erp_is_flagged_as_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_deps(damodaran=_FakeDamodaran(0.046, "damodaran_snapshot_2025_01")))
    assert res.data["erp_source"] == "damodaran_snapshot_2025_01"
    assert any("snapshot" in w.lower() for w in res.warnings)


def test_wacc3_missing_damodaran_is_a_labelled_assumption(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_deps())
    assert res.data["erp"] == pytest.approx(0.05)
    assert res.data["erp_source"] == "assumption_default_5pct"
    assert any("erp" in w.lower() for w in res.warnings)


def test_wacc3_damodaran_error_is_warned_and_labelled(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)

    class _BrokenDamo:
        async def get_erp_with_source(self, country: str = "US"):
            raise RuntimeError("damodaran down")

    res = _run(_deps(damodaran=_BrokenDamo()))
    assert res.data["erp_source"] == "assumption_default_5pct"
    assert any("damodaran" in w.lower() for w in res.warnings)


def test_wacc3_market_premium_input_is_honoured(monkeypatch) -> None:
    """The manifest input is named market_premium; it used to be ignored."""
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_deps(damodaran=_FakeDamodaran()), market_premium=0.06)
    assert res.data["erp"] == pytest.approx(0.06)
    assert res.data["erp_source"] == "user_input"
    assert "damodaran" not in res.sources


def test_wacc3_erp_param_is_user_input(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_deps(damodaran=_FakeDamodaran()), erp=0.055)
    assert res.data["erp"] == pytest.approx(0.055)
    assert res.data["erp_source"] == "user_input"


def _adapter_with_tmp_cache(tmp_path, monkeypatch):
    from showme.engine.data_sources.macro import damodaran_adapter as dm

    monkeypatch.setattr(dm, "_cache_path", lambda: tmp_path / "damodaran_erp.json")
    return dm, dm.DamodaranAdapter()


def test_wacc3_adapter_reports_snapshot_when_scrape_fails(tmp_path, monkeypatch) -> None:
    dm, adapter = _adapter_with_tmp_cache(tmp_path, monkeypatch)

    async def _offline():
        raise RuntimeError("offline")

    monkeypatch.setattr(adapter, "_client_", _offline)
    erp, source = asyncio.run(adapter.get_erp_with_source("US"))
    assert erp == pytest.approx(0.046)
    assert source == "damodaran_snapshot_2025_01"


def test_wacc3_adapter_reports_cache_source(tmp_path, monkeypatch) -> None:
    import json
    import time

    dm, adapter = _adapter_with_tmp_cache(tmp_path, monkeypatch)
    (tmp_path / "damodaran_erp.json").write_text(
        json.dumps({"ts": int(time.time()), "payload": {"US": 4.2, "_global": 4.2}})
    )
    erp, source = asyncio.run(adapter.get_erp_with_source("US"))
    assert erp == pytest.approx(0.042)
    assert source == "damodaran_cache"


def test_wacc3_adapter_flags_unmatched_country(tmp_path, monkeypatch) -> None:
    dm, adapter = _adapter_with_tmp_cache(tmp_path, monkeypatch)

    async def _offline():
        raise RuntimeError("offline")

    monkeypatch.setattr(adapter, "_client_", _offline)
    erp, source = asyncio.run(adapter.get_erp_with_source("ZZ"))
    assert erp == pytest.approx(0.046)
    assert source.endswith("_country_unmatched")


class _StubBetaOk:
    """BETA stub with a live 5Y window so only the ERP path varies."""

    def __init__(self, deps=None) -> None:
        self.deps = deps

    async def execute(self, instrument, **params):
        from showme.engine.core.base_function import FunctionResult
        return FunctionResult(
            code="BETA", instrument=instrument,
            data={"status": "ok", "betas": {"5Y": {"beta": 1.2}}},
            sources=["yfinance"],
        )


class _FakeDamodaran:
    """Stands in for DamodaranAdapter; returns (erp, source) like get_erp_with_source."""

    def __init__(self, erp: float = 0.046, source: str = "damodaran_cache") -> None:
        self._erp, self._source = erp, source

    async def get_erp_with_source(self, country: str = "US"):
        return self._erp, self._source


# ---- WACC#4: the tax rate is labelled with its source ---------------------


def _deps_with_raw(raw: dict[str, Any]) -> FunctionDeps:
    return FunctionDeps(
        yfinance=_FakeYf(raw=raw),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}),
        damodaran=_FakeDamodaran(),
    )


def test_wacc4_default_tax_is_a_labelled_statutory_rate(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_deps())
    assert res.data["tax_rate"] == pytest.approx(0.21)
    assert res.data["tax_source"] == "statutory_us_21pct"
    assert any("21%" in w for w in res.warnings)


def test_wacc4_tax_rate_override_alias_is_user_input(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_deps(), tax_rate_override=0.15)
    assert res.data["tax_rate"] == pytest.approx(0.15)
    assert res.data["tax_source"] == "user_input"


def test_wacc4_tax_rate_param_is_user_input(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_deps(), tax_rate=0.18)
    assert res.data["tax_rate"] == pytest.approx(0.18)
    assert res.data["tax_source"] == "user_input"


def test_wacc4_issuer_effective_tax_is_used_when_the_provider_gives_it(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    raw = {"marketCap": 300.0, "totalDebt": 100.0, "sector": "Consumer Cyclical",
           "incomeTaxExpense": 30.0, "pretaxIncome": 150.0}
    res = _run(_deps_with_raw(raw))
    assert res.data["tax_rate"] == pytest.approx(0.20)
    assert res.data["tax_source"] == "issuer_effective"


# ---- WACC#6: status and data_state reflect every input --------------------


def _live_deps(**overrides: Any) -> FunctionDeps:
    raw = {"marketCap": 300.0, "totalDebt": 100.0, "sector": "Consumer Cyclical",
           "incomeTaxExpense": 30.0, "pretaxIncome": 150.0}
    raw.update(overrides.pop("raw", {}))
    fred = overrides.pop("fred", {"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93})
    damo = overrides.pop("damodaran", _FakeDamodaran(0.046, "damodaran_cache"))
    return FunctionDeps(yfinance=_FakeYf(raw=raw), fred=_FakeFred(fred), damodaran=damo)


def test_wacc6_every_input_live_is_live(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_live_deps())
    assert res.data["status"] == "ok"
    assert res.data["data_state"] == "live"
    assert res.data["partial_inputs"] == []
    assert res.data["wacc"] is not None


def test_wacc6_default_erp_and_tax_make_the_state_partial(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_deps())
    assert res.data["status"] == "ok"
    assert res.data["data_state"] == "partial"
    assert res.data["partial_inputs"] == ["erp", "tax"]


def test_wacc6_snapshot_erp_makes_the_state_partial(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_live_deps(damodaran=_FakeDamodaran(0.046, "damodaran_snapshot_2025_01")))
    assert res.data["data_state"] == "partial"
    assert "erp" in res.data["partial_inputs"]


def test_wacc6_aaa_cost_of_debt_makes_the_state_partial(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_live_deps(fred={"DGS10": 4.0, "AAA": 4.8}))
    assert res.data["rd_source"] == "fred_aaa"
    assert res.data["data_state"] == "partial"
    assert "rd" in res.data["partial_inputs"]


def test_wacc6_sector_default_capital_structure_makes_the_state_partial(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_live_deps(raw={"marketCap": 0.0, "totalDebt": 0.0, "sector": "Technology"}))
    assert res.data["capital_structure_data_state"] == "sector_default"
    assert res.data["data_state"] == "partial"
    assert "capital_structure" in res.data["partial_inputs"]


def test_wacc6_user_supplied_beta_is_user_input(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_live_deps(), beta=1.1)
    assert res.data["data_state"] == "user_input"
    assert "beta" in res.data["user_inputs"]


def test_wacc6_missing_input_is_provider_unavailable_state(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaOk)
    res = _run(_live_deps(fred={"BAMLC0A4CBBBEY": 5.93}))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["data_state"] == "provider_unavailable"
