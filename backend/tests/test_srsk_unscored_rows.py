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
