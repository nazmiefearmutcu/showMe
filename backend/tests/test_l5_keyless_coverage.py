"""L5 keyless coverage + default-polarity flips (2026-09-11 campaign).

Covers the survey-4 coverage gaps closed by the backend lane:

* WETR defaults to the keyless Open-Meteo adapter (registered in
  ``FunctionFactory``) instead of the ``seasonal_weather_model`` token.
* TAUC defaults to the keyless TreasuryDirect adapter instead of the
  hand-written auction template.
* FRH defaults to the in-file keyless Binance/Bybit/OKX funding feeds
  (previously gated behind ``live=1``).
* ALLQ anchors US tenors on the keyless Treasury par-yield curve when the
  ``ustreasury`` adapter is wired (per-tenor, no FiscalData type-average).
* CSRC/SECF/SRCH screen universes default to live keyless sources and
  keep per-source honest labels (worst-case reference, never over-claim).

All tests are offline: every network adapter is an injected fake.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest

from showme import server
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.quote import Quote

# ─────────────────────────────────────────────────────────────────────────
# Shared fakes
# ─────────────────────────────────────────────────────────────────────────


def _quote(symbol: str, last: float, close_prev: float, volume: float = 1_000_000.0) -> Quote:
    return Quote(
        symbol=symbol,
        timestamp=datetime.now(tz=timezone.utc),
        last=last,
        close_prev=close_prev,
        volume_24h=volume,
        high_24h=last * 1.01,
        low_24h=last * 0.99,
    )


class _FakeQuoteProvider:
    """yfinance-shaped QUOTE provider; ``None`` for unknown symbols."""

    def __init__(self, quotes: dict[str, Quote]):
        self.quotes = {k.upper(): v for k, v in quotes.items()}
        self.calls = 0

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", "")).upper()
        return self.quotes.get(symbol)


class _FakeTreasuryCurve:
    """ustreasury-shaped adapter returning a date-indexed par-yield frame."""

    def __init__(self, columns: dict[str, float], boom: bool = False):
        self._columns = columns
        self._boom = boom
        self.calls = 0

    async def yield_curve(self) -> pd.DataFrame:
        self.calls += 1
        if self._boom:
            raise RuntimeError("treasury csv down")
        return pd.DataFrame([self._columns], index=pd.to_datetime(["2026-09-10"]))


class _FakeOpenMeteo:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    async def onecall(self, lat: float, lon: float, days: int = 10) -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("open-meteo down")
        return {
            "daily": [
                {
                    "dt": datetime(2026, 9, 11, tzinfo=timezone.utc).timestamp(),
                    "temp": {"day": 20.0, "min": 17.0, "max": 23.0},
                    "precipitation": 1.2,
                }
            ]
        }


def _body(result: Any) -> dict[str, Any]:
    return server.enforce_live_or_label_synthetic(result.code, {}, result.to_dict())


# ─────────────────────────────────────────────────────────────────────────
# WETR — keyless Open-Meteo default
# ─────────────────────────────────────────────────────────────────────────


def test_open_meteo_to_onecall_translation() -> None:
    from showme.engine.data_sources.alt.open_meteo_adapter import open_meteo_to_onecall

    payload = {
        "daily": {
            "time": ["2026-09-11", "2026-09-12"],
            "temperature_2m_max": [22.0, 21.0],
            "temperature_2m_min": [14.0, 13.0],
            "precipitation_sum": [0.0, 2.5],
        }
    }
    out = open_meteo_to_onecall(payload)
    assert out["daily"][0]["temp"]["day"] == 18.0
    assert out["daily"][1]["temp"]["min"] == 13.0
    assert out["daily"][1]["precipitation"] == 2.5


def test_open_meteo_to_onecall_rejects_unusable_payload() -> None:
    from showme.engine.core.base_data_source import DataSourceError
    from showme.engine.data_sources.alt.open_meteo_adapter import open_meteo_to_onecall

    with pytest.raises(DataSourceError):
        open_meteo_to_onecall({"daily": {}})
    with pytest.raises(DataSourceError):
        open_meteo_to_onecall("nope")


def test_function_factory_registers_open_meteo() -> None:
    from showme.engine.data_sources.alt.open_meteo_adapter import OpenMeteoAdapter
    from showme.engine.services.function_factory import FunctionFactory

    factory = FunctionFactory()
    assert isinstance(factory.deps.open_meteo, OpenMeteoAdapter)
    assert factory.adapter("open_meteo") is factory.deps.open_meteo


def test_wetr_defaults_to_live_open_meteo() -> None:
    from showme.engine.functions.commodity._funcs import WETRFunction

    fake = _FakeOpenMeteo()
    result = asyncio.run(WETRFunction(FunctionDeps(open_meteo=fake)).execute())
    assert result.data["status"] == "ok"
    assert result.data["source_mode"] == "live_open_meteo"
    assert result.sources == ["open_meteo"]
    assert result.data["rows"], "live path must return real provider rows"
    assert result.data["rows"][0]["source_mode"] == "live_open_meteo"
    sanitized = _body(result)
    assert sanitized["data_state"] == "live"


def test_wetr_reference_true_skips_provider_and_serves_labelled_model() -> None:
    from showme.engine.functions.commodity._funcs import WETRFunction

    fake = _FakeOpenMeteo()
    result = asyncio.run(
        WETRFunction(FunctionDeps(open_meteo=fake)).execute(reference=True)
    )
    assert fake.calls == 0, "reference=true must not hit the live provider"
    assert result.data["source_mode"] == "seasonal_model"
    assert result.sources == ["seasonal_weather_model"]
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("data_mode") == "modeled"
    assert _body(result)["data_state"] != "live"


def test_wetr_provider_outage_is_labelled_not_live() -> None:
    from showme.engine.functions.commodity._funcs import WETRFunction

    result = asyncio.run(
        WETRFunction(FunctionDeps(open_meteo=_FakeOpenMeteo(fail=True))).execute()
    )
    assert result.data["status"] == "provider_unavailable"
    assert result.data["source_mode"] == "seasonal_model"
    assert result.metadata.get("fallback") is True
    sanitized = _body(result)
    assert sanitized["data_state"] != "live"


def test_wetr_prefers_keyed_openweather_when_configured() -> None:
    from showme.engine.functions.commodity._funcs import WETRFunction

    class _KeyedOpenWeather:
        api_key = "test-key"

        def __init__(self) -> None:
            self.calls = 0

        async def onecall(self, lat: float, lon: float) -> dict[str, Any]:
            self.calls += 1
            return {
                "daily": [
                    {
                        "dt": datetime(2026, 9, 11, tzinfo=timezone.utc).timestamp(),
                        "temp": {"day": 19.0, "min": 16.0, "max": 22.0},
                        "precipitation": 0.0,
                    }
                ]
            }

    openweather = _KeyedOpenWeather()
    open_meteo = _FakeOpenMeteo()
    result = asyncio.run(
        WETRFunction(FunctionDeps(openweather=openweather, open_meteo=open_meteo)).execute()
    )
    assert result.sources == ["openweathermap"]
    assert result.data["source_mode"] == "live_openweathermap"
    assert openweather.calls == 1
    assert open_meteo.calls == 0


# ─────────────────────────────────────────────────────────────────────────
# TAUC — keyless TreasuryDirect default
# ─────────────────────────────────────────────────────────────────────────


class _FakeTreasuryAuctions:
    def __init__(self, rows: list[dict[str, Any]] | None = None, boom: bool = False):
        self.rows = rows or [
            {
                "security_type": "Bill",
                "term": "13-Week",
                "auction_date": "2026-09-15",
                "offering_amount": 70_000_000_000,
            }
        ]
        self.boom = boom
        self.calls = 0

    async def upcoming(self, *, horizon_days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        self.calls += 1
        if self.boom:
            raise RuntimeError("treasurydirect timeout")
        return self.rows if limit is None else self.rows[:limit]

    async def recent(self, *, days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        self.calls += 1
        if self.boom:
            raise RuntimeError("treasurydirect timeout")
        return self.rows if limit is None else self.rows[:limit]


def test_tauc_defaults_to_keyless_treasury_direct() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    adapter = _FakeTreasuryAuctions()
    result = asyncio.run(TAUCFunction(FunctionDeps(treasury_auctions=adapter)).execute())
    assert adapter.calls == 1
    assert result.sources == ["treasurydirect"]
    assert result.metadata.get("live") is True
    assert result.metadata.get("data_mode") == "live_official"
    sanitized = _body(result)
    assert sanitized["data_state"] == "live"


def test_tauc_explicit_live_false_keeps_labelled_template() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    adapter = _FakeTreasuryAuctions()
    result = asyncio.run(
        TAUCFunction(FunctionDeps(treasury_auctions=adapter)).execute(live_auctions=False)
    )
    assert adapter.calls == 0
    assert result.data["summary"]["source_mode"] == "treasury_auction_model"
    assert result.metadata.get("fallback") is True
    assert _body(result)["data_state"] != "live"


def test_tauc_reference_true_keeps_labelled_template() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    adapter = _FakeTreasuryAuctions()
    result = asyncio.run(
        TAUCFunction(FunctionDeps(treasury_auctions=adapter)).execute(reference=True)
    )
    assert adapter.calls == 0
    assert result.sources == ["treasury_auction_model"]


def test_tauc_provider_failure_is_labelled_fallback() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    result = asyncio.run(
        TAUCFunction(FunctionDeps(treasury_auctions=_FakeTreasuryAuctions(boom=True))).execute()
    )
    assert result.data["summary"]["source_mode"] == "treasury_auction_fallback"
    assert result.sources == ["treasury_auction_fallback"]
    assert result.metadata.get("fallback") is True
    assert result.warnings
    sanitized = _body(result)
    assert sanitized["data_state"] != "live"
    assert sanitized["status"] == "provider_unavailable"


def test_tauc_without_adapter_stays_labelled_model() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    result = asyncio.run(TAUCFunction(FunctionDeps()).execute())
    assert result.sources == ["treasury_auction_model"]
    assert result.metadata.get("fallback") is True
    assert result.data["summary"]["source_mode"] == "treasury_auction_model"
    assert _body(result)["data_state"] != "live"


# ─────────────────────────────────────────────────────────────────────────
# FRH — keyless exchange endpoints by default
# ─────────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeFundingClient:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        self.calls += 1
        if self.fail:
            raise RuntimeError("exchange down")
        if "premiumIndex" in url:
            return _FakeResponse(200, {"lastFundingRate": 0.0001})
        if "bybit" in url:
            return _FakeResponse(200, {"result": {"list": [{"fundingRate": 0.00005}]}})
        if "okx" in url:
            return _FakeResponse(200, {"data": [{"fundingRate": 0.0002}]})
        return _FakeResponse(404, {})


def test_frh_defaults_to_live_keyless_exchanges() -> None:
    from showme.engine.functions.screen.frh import FRHFunction

    client = _FakeFundingClient()
    fn = FRHFunction()
    fn._http_client = client
    result = asyncio.run(fn.execute(symbols="BTCUSDT,ETHUSDT"))
    assert client.calls > 0
    assert result.sources == ["binance", "bybit", "okx"]
    assert result.metadata.get("live") is True
    assert result.metadata.get("data_mode") == "live_exchange"
    assert all(row["avg"] is not None for row in result.data["rows"])
    sanitized = _body(result)
    assert sanitized["data_state"] == "live"


def test_frh_provider_exhausted_envelope_cannot_earn_live() -> None:
    from showme.engine.functions.screen.frh import FRHFunction

    fn = FRHFunction()
    fn._http_client = _FakeFundingClient(fail=True)
    result = asyncio.run(fn.execute(symbols="BTCUSDT"))
    # Real provider names stay visible for diagnostics...
    assert result.sources == ["binance", "bybit", "okx"]
    assert result.data["status"] == "provider_unavailable"
    # ...but the failure semantics must veto LIVE.
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False
    sanitized = _body(result)
    assert sanitized["data_state"] == "provider_unavailable"
    assert sanitized["data_state"] != "live"
    assert sanitized["status"] == "provider_unavailable"


def test_frh_reference_true_serves_model_without_network() -> None:
    from showme.engine.functions.screen.frh import FRHFunction

    client = _FakeFundingClient()
    fn = FRHFunction()
    fn._http_client = client
    result = asyncio.run(fn.execute(symbols="BTCUSDT", reference=True))
    assert client.calls == 0
    assert result.sources == ["funding_rate_model"]
    assert _body(result)["data_state"] != "live"


# ─────────────────────────────────────────────────────────────────────────
# ALLQ — per-tenor keyless treasury curve anchor
# ─────────────────────────────────────────────────────────────────────────


def test_allq_prefers_per_tenor_curve_anchor_when_wired() -> None:
    from showme.engine.functions.bond._stubs import ALLQFunction

    curve = _FakeTreasuryCurve({"3 Mo": 4.9, "2 Yr": 4.4, "5 Yr": 4.3, "10 Yr": 4.5, "30 Yr": 4.6})
    fn = ALLQFunction(FunctionDeps(ustreasury=curve))
    result = asyncio.run(
        fn.execute(instrument=Instrument(symbol="US10Y", asset_class=AssetClass.BOND))
    )
    assert result.data["status"] == "ok"
    assert result.sources[0] == "ustreasury"
    assert "per-tenor" in result.data["summary"]["reference"]
    assert curve.calls == 1


def test_allq_curve_failure_returns_none_without_fallback_claim() -> None:
    from showme.engine.functions.bond._stubs import ALLQFunction

    fn = ALLQFunction(FunctionDeps(ustreasury=_FakeTreasuryCurve({}, boom=True)))
    got = asyncio.run(fn._ustreasury_curve_anchor("US10Y"))
    assert got is None


def test_allq_unknown_tenor_skips_curve() -> None:
    from showme.engine.functions.bond._stubs import ALLQFunction

    curve = _FakeTreasuryCurve({"10 Yr": 4.5})
    fn = ALLQFunction(FunctionDeps(ustreasury=curve))
    got = asyncio.run(fn._ustreasury_curve_anchor("DE10Y"))
    assert got is None
    assert curve.calls == 0


# ─────────────────────────────────────────────────────────────────────────
# CSRC — commodity screener defaults to live yfinance quotes
# ─────────────────────────────────────────────────────────────────────────


def test_csrc_default_attempts_live_quotes() -> None:
    from showme.engine.functions.screen._funcs import CSRCFunction

    quotes = {
        "CL=F": _quote("CL=F", 78.5, 77.9),
        "BZ=F": _quote("BZ=F", 82.4, 81.8),
        "NG=F": _quote("NG=F", 3.31, 3.28),
    }
    provider = _FakeQuoteProvider(quotes)
    result = asyncio.run(
        CSRCFunction(FunctionDeps(yfinance=provider)).execute(query='sector = "Energy"')
    )
    assert provider.calls > 0
    assert "yfinance" in result.sources
    energy_rows = {row["symbol"]: row for row in result.data["rows"]}
    assert energy_rows["CL=F"]["quote_state"] == "live"
    assert energy_rows["CL=F"]["last"] == 78.5
    # Worst-case honest label: curated reference universe + live quotes.
    sanitized = _body(result)
    assert sanitized["data_state"] == "reference"
    assert sanitized["data_state"] != "live"


def test_csrc_reference_true_skips_quotes() -> None:
    from showme.engine.functions.screen._funcs import CSRCFunction

    provider = _FakeQuoteProvider({})
    result = asyncio.run(
        CSRCFunction(FunctionDeps(yfinance=provider)).execute(
            query='sector = "Energy"', reference=True
        )
    )
    assert provider.calls == 0
    assert result.sources == ["showme_commodity_reference_universe"]
    assert all(row.get("quote_state") is None for row in result.data["rows"])


# ─────────────────────────────────────────────────────────────────────────
# SECF — security finder defaults to live quotes with reference identity
# ─────────────────────────────────────────────────────────────────────────


def test_secf_default_attaches_live_quotes_with_reference_identity() -> None:
    from showme.engine.functions.screen._funcs import SECFFunction

    provider = _FakeQuoteProvider({
        "AAPL": _quote("AAPL", 210.0, 208.0),
        "MSFT": _quote("MSFT", 510.0, 508.0),
    })
    result = asyncio.run(
        SECFFunction(FunctionDeps(yfinance=provider)).execute(query="technology")
    )
    assert "yfinance" in result.sources
    assert "showme_security_master_reference" in result.sources
    by_symbol = {row["symbol"]: row for row in result.data["rows"]}
    assert by_symbol["AAPL"]["quote_state"] == "live"
    assert by_symbol["AAPL"]["last"] == 210.0
    # NVDA had no quote → row stays reference-labelled.
    assert by_symbol["NVDA"]["quote_state"] == "reference"
    sanitized = _body(result)
    # Worst-case honest label: the curated master keeps the payload off LIVE.
    assert sanitized["data_state"] == "reference"
    assert sanitized["data_state"] != "live"


def test_secf_reference_true_serves_master_only() -> None:
    from showme.engine.functions.screen._funcs import SECFFunction

    provider = _FakeQuoteProvider({})
    result = asyncio.run(
        SECFFunction(FunctionDeps(yfinance=provider)).execute(
            query="technology", reference=True
        )
    )
    assert provider.calls == 0
    assert result.sources == ["showme_security_master_reference"]


# ─────────────────────────────────────────────────────────────────────────
# SRCH — bond screener defaults to the keyless treasury curve yields
# ─────────────────────────────────────────────────────────────────────────


def test_srch_default_refreshes_us_yields_from_keyless_curve() -> None:
    from showme.engine.functions.screen._funcs import SRCHFunction

    curve = _FakeTreasuryCurve({"3 Mo": 4.95, "2 Yr": 4.42, "5 Yr": 4.31, "10 Yr": 4.36, "30 Yr": 4.61})
    result = asyncio.run(
        SRCHFunction(FunctionDeps(ustreasury=curve)).execute(
            query="duration >= 0"
        )
    )
    assert "ustreasury" in result.sources
    by_symbol = {row["symbol"]: row for row in result.data["rows"]}
    assert by_symbol["US10Y"]["yield"] == 4.36
    assert by_symbol["US10Y"]["yield_state"] == "live"
    # Non-US rows keep their curated reference yield.
    assert by_symbol["DE10Y"]["yield_state"] == "reference"
    # Worst-case honest label: the curated bond universe stays reference.
    sanitized = _body(result)
    assert sanitized["data_state"] == "reference"
    assert sanitized["data_state"] != "live"


def test_srch_reference_true_keeps_static_yields() -> None:
    from showme.engine.functions.screen._funcs import SRCHFunction

    curve = _FakeTreasuryCurve({"10 Yr": 4.36})
    result = asyncio.run(
        SRCHFunction(FunctionDeps(ustreasury=curve)).execute(
            query="yield >= 4", reference=True
        )
    )
    assert curve.calls == 0
    assert result.sources == ["showme_bond_reference_universe"]
    by_symbol = {row["symbol"]: row for row in result.data["rows"]}
    assert by_symbol["US10Y"]["yield"] == 4.45  # bundled static value


def test_srch_curve_unavailable_keeps_static_with_warning() -> None:
    from showme.engine.functions.screen._funcs import SRCHFunction

    result = asyncio.run(
        SRCHFunction(FunctionDeps(ustreasury=_FakeTreasuryCurve({}, boom=True))).execute(
            query="yield >= 4"
        )
    )
    assert result.sources == ["showme_bond_reference_universe"]
    assert any("curve unavailable" in warning.lower() for warning in result.warnings)
    assert _body(result)["data_state"] == "reference"
