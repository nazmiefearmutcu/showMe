"""SRSK must not invent a spread or PD for a country with no live macro data.

When World Bank returns nothing for a sovereign, the old code substituted a
flat 3.25% fallback spread and computed a numeric PD from it. That is a
placeholder posing as data. The honest row keeps the country, unranked, with
null risk score, spread and PD, and a visible reason.

No network: the World Bank adapter seam is faked and the direct HTTP client
is replaced by one that fails, so unscored countries stay unscored.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.bond.srsk import SRSKFunction


class _PartialWorldBank:
    """Serves real macro values for TUR and USA only; XX has no data at all."""

    _BY_ISO3: dict[str, dict[str, float]] = {
        "TUR": {
            "GC.DOD.TOTL.GD.ZS": 34.0,
            "FI.RES.TOTL.MO": 3.5,
            "BN.CAB.XOKA.GD.ZS": -4.5,
            "FP.CPI.TOTL.ZG": 53.0,
        },
        "USA": {
            "GC.DOD.TOTL.GD.ZS": 121.0,
            "FI.RES.TOTL.MO": 0.6,
            "BN.CAB.XOKA.GD.ZS": -3.0,
            "FP.CPI.TOTL.ZG": 3.4,
        },
    }

    async def indicator(self, iso3: str, indicator: str) -> Any:
        value = self._BY_ISO3.get(iso3, {}).get(indicator)
        return [{"page": 1, "total": 1}, [{"value": value, "date": "2024"}]]


class _DeadHttpClient:
    def get(self, *args: Any, **kwargs: Any) -> Any:
        raise OSError("network disabled in tests")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import showme.providers._http as http_mod

    monkeypatch.setattr(http_mod, "get_client", lambda: _DeadHttpClient(), raising=False)


def _run(countries: str) -> Any:
    fn = SRSKFunction(FunctionDeps(worldbank=_PartialWorldBank()))
    return asyncio.run(fn.execute(countries=countries))


def test_unscored_country_has_no_spread_or_pd(no_network: None) -> None:
    out = _run("TR,XX,US")
    assert out.data["status"] == "ok"
    by_country = {row["country"]: row for row in out.data["rows"]}

    xx = by_country["XX"]
    assert xx["risk_score"] is None
    # Pre-fix: 3.25 flat fallback spread and a numeric PD computed from it.
    assert xx["proxy_spread_pct"] is None, xx
    assert xx["pd_1y_proxy"] is None, xx
    assert xx["pd_1y_pct"] is None, xx
    assert xx["source_mode"] == "unavailable"
    assert "no live World Bank macro for XX" in (xx["note"] or "")


def test_scored_countries_keep_their_real_spread_and_pd(no_network: None) -> None:
    out = _run("TR,XX,US")
    by_country = {row["country"]: row for row in out.data["rows"]}
    for code in ("TR", "US"):
        row = by_country[code]
        assert row["risk_score"] is not None
        assert row["proxy_spread_pct"] is not None
        assert row["pd_1y_pct"] == pytest.approx(
            row["proxy_spread_pct"] / 100 / (1 - row["recovery"]) * 100, rel=1e-9
        )


def test_unscored_country_never_drives_the_highest_pd_card(no_network: None) -> None:
    out = _run("XX,TR,US")
    cards = out.data["cards"]
    assert cards["highest_pd_country"] in {"TR", "US"}
    assert cards["highest_pd"] is not None


def test_summary_counts_unscored_rows_honestly(no_network: None) -> None:
    out = _run("TR,XX,US")
    assert out.data["summary"]["unscored_countries"] == 1
    assert "fallback_countries" not in out.data["summary"]


def test_fallback_spread_param_no_longer_substitutes_a_value(no_network: None) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_PartialWorldBank()))
    out = asyncio.run(fn.execute(countries="XX,TR", proxy_spread_pct=5.0))
    by_country = {row["country"]: row for row in out.data["rows"]}
    assert by_country["XX"]["proxy_spread_pct"] is None


def _fred_frame(series_id: str, value: float):
    """A FRED-shaped frame: DGS10 daily over a month, IRLTLT01 sovereigns monthly."""
    import pandas as pd

    if series_id == "DGS10":
        idx = pd.date_range("2026-09-01", "2026-09-30", freq="B")
    else:
        idx = pd.DatetimeIndex(["2026-09-01"])
    return pd.DataFrame({"value": [float(value)] * len(idx)}, index=idx)


class _Col:
    """Minimal stand-in for a pandas column: only ``.iloc[-1]`` is used."""

    def __init__(self, value: float) -> None:
        self.iloc = [value]


class _FakeFred:
    """Serves a fixed UST 10Y and per-country 10Y yields; no network."""

    _SERIES: dict[str, float] = {
        "DGS10": 2.0,  # UST 10Y
        "IRLTLT01DEM156N": 3.5,  # Germany 10Y -> spread 1.5
        "IRLTLT01TRM156N": 9.0,  # Turkey 10Y -> spread 7.0
    }

    api_key = "test-key"  # a keyed adapter, so the keyless CSV shim is not used

    async def series(self, series_id: str) -> Any:
        return _fred_frame(series_id, self._SERIES[series_id])


class _NoWorldBank:
    """World Bank returns no observation for any country (outage-like)."""

    async def indicator(self, iso3: str, indicator: str) -> Any:
        return [{"page": 1, "total": 0}, None]


def _run_fred(countries: str, worldbank: Any = None) -> Any:
    deps = FunctionDeps(worldbank=worldbank or _PartialWorldBank(), fred=_FakeFred())
    fn = SRSKFunction(deps)
    return asyncio.run(fn.execute(countries=countries))


def test_fred_refined_unscored_row_note_is_not_the_no_spread_note(no_network: None) -> None:
    # DE has a FRED 10Y yield but no World Bank macro: spread/PD come from FRED.
    out = _run_fred("DE,TR,US")
    de = {row["country"]: row for row in out.data["rows"]}["DE"]
    assert de["risk_score"] is None
    assert de["proxy_spread_pct"] == pytest.approx(1.5)
    assert de["source_mode"] == "fred"
    note = de["note"] or ""
    # The row carries a numeric spread, so its note must not say none was computed.
    assert "no risk score, spread or PD computed" not in note
    assert "no risk score computed" in note
    assert "FRED" in note


def test_fred_priced_unscored_row_never_leads_the_cards(no_network: None) -> None:
    # No World Bank macro for any country: TR is priced by FRED but has no score.
    out = _run_fred("TR,XX", worldbank=_NoWorldBank())
    by_country = {row["country"]: row for row in out.data["rows"]}
    assert by_country["TR"]["risk_score"] is None
    assert by_country["TR"]["pd_1y_pct"] is not None
    assert out.data["cards"]["highest_pd_country"] is None
    assert out.data["cards"]["highest_pd"] is None
    assert out.data["summary"]["highest_risk_country"] is None


def test_fred_scored_leader_still_drives_the_cards(no_network: None) -> None:
    out = _run_fred("DE,TR,US")
    cards = out.data["cards"]
    assert cards["highest_pd_country"] in {"TR", "US"}
    assert out.data["summary"]["highest_risk_country"] in {"TR", "US"}


def test_unscored_count_includes_fred_priced_rows(no_network: None) -> None:
    # DE is FRED-priced but unscored; XX is unscored and unpriced.
    out = _run_fred("DE,XX,US")
    assert out.data["summary"]["unscored_countries"] == 2


class _EmptyHttpResponse:
    def json(self) -> Any:
        return [{"page": 1, "total": 0}, None]


class _EmptyHttpClient:
    """World Bank answers, but with no observations for any indicator."""

    def get(self, *args: Any, **kwargs: Any) -> Any:
        return _EmptyHttpResponse()


def test_fred_key_with_no_priced_country_is_not_status_ok(no_network: None) -> None:
    # XX has no World Bank macro and no FRED sovereign series: nothing is priced.
    # Pre-fix this returned status 'ok' with sources ['sovereign_risk_model'] and
    # data_mode 'modeled', although no modeled value exists.
    out = _run_fred("XX", worldbank=_NoWorldBank())
    assert out.data["status"] in {"empty", "provider_unavailable"}, out.data
    assert out.data["rows"] == []
    assert out.data.get("reason")
    assert out.data.get("next_actions")
    assert "sovereign_risk_model" not in out.sources
    assert out.data.get("data_mode") != "modeled"
    assert out.data.get("cards") is None


def test_fred_key_empty_worldbank_without_errors_is_status_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import showme.providers._http as http_mod

    monkeypatch.setattr(http_mod, "get_client", lambda: _EmptyHttpClient(), raising=False)
    out = _run_fred("XX", worldbank=_NoWorldBank())
    assert out.data["status"] == "empty", out.data
    assert out.data["rows"] == []
    assert out.data.get("reason")
    assert out.data.get("next_actions")
    assert out.sources == []
    assert "sovereign_risk_model" not in out.sources


def test_fred_only_result_labels_fred_provenance_not_modeled(no_network: None) -> None:
    # DE is priced by a real FRED 10Y differential; there is no World Bank macro.
    out = _run_fred("DE,XX,US", worldbank=_NoWorldBank())
    assert out.data["status"] == "ok"
    assert "fred" in out.sources
    assert "worldbank" not in out.sources
    assert "sovereign_risk_model" not in out.sources
    assert out.data["data_mode"] == "live"
    assert out.data["cards"]["data_mode"] == "live"
