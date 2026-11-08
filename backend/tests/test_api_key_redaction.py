"""Query-string API keys never reach exception text (audit SEC-2).

Free providers take their key in the query string (FRED ``api_key``, Alpha
Vantage ``apikey``, Finnhub/EODHD ``token``/``api_token``, OWM ``appid``,
EIA ``api_key``). An httpx status error embeds the full URL, so a 401/403
used to put the live key into the exception text, which then reached
``_last_error`` and the callers. These tests use real httpx responses and
no network.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.alt.openweathermap_adapter import OpenWeatherMapAdapter
from showme.engine.data_sources.commodity.eia_adapter import EIAAdapter
from showme.engine.data_sources.equity.alphavantage_adapter import AlphaVantageAdapter
from showme.engine.data_sources.equity.eodhd_adapter import EODHDAdapter
from showme.engine.data_sources.equity.finnhub_adapter import FinnhubAdapter
from showme.engine.data_sources.macro.fred_adapter import FREDAdapter
from showme.engine.data_sources.news.finnhub_news_adapter import FinnhubNewsAdapter
from showme.providers import fred as provider_fred
from showme.providers.base import AdapterError, redact_secrets
from showme.providers.fred import FredAdapter

SECRET = "SECRET-KEY-9f3a71c2"
AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _RejectingClient:
    """Answers every GET with an HTTP error whose body does not echo the key."""

    def __init__(self, status: int = 401) -> None:
        self.status = status

    async def get(self, url: str, params: dict[str, Any] | None = None, **_: Any) -> httpx.Response:
        full = url if url.startswith("http") else f"https://provider.test{url}"
        request = httpx.Request("GET", full, params=params)
        return httpx.Response(self.status, request=request, json={"error": "invalid api key"})


def _assert_clean(exc: BaseException) -> None:
    assert SECRET not in str(exc)
    assert SECRET not in repr(exc)
    for linked in (exc.__cause__, exc.__context__):
        if linked is not None:
            assert SECRET not in str(linked)
            assert SECRET not in repr(linked)


def test_redact_secrets_masks_query_pairs_and_literal_values():
    text = f"Client error for url 'https://x.test/a?series_id=A&api_key={SECRET}&file_type=json' token=abc123 monkey=keep"
    out = redact_secrets(text, SECRET)
    assert SECRET not in out
    assert "api_key=***" in out
    assert "token=***" in out
    assert "monkey=keep" in out


async def test_fred_provider_error_does_not_leak_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FRED_API_KEY", SECRET)

    async def _client():
        return _RejectingClient(401)

    monkeypatch.setattr(provider_fred, "get_client", _client)
    adapter = FredAdapter()
    with pytest.raises(AdapterError) as info:
        await adapter.get_series("DGS10")
    _assert_clean(info.value)
    assert SECRET not in str(adapter._last_error)
    assert adapter.mode().value == "provider_unavailable"


def _engine_cases() -> list[tuple[str, Any, Any]]:
    def fred(a):
        return a.info("DGS10")

    def alpha(a):
        return a._get(function="GLOBAL_QUOTE", symbol="AAPL")

    def finnhub(a):
        return a._get("/quote", symbol="AAPL")

    def finnhub_news(a):
        return a.fetch(DataRequest(kind=DataKind.NEWS, instrument=AAPL))

    def eodhd(a):
        return a._get("/eod/AAPL.US")

    def owm(a):
        return a.onecall(40.7, -74.0)

    def eia(a):
        return a.series_data("petroleum/pri/spt")

    return [
        ("fred", FREDAdapter, fred),
        ("alphavantage", AlphaVantageAdapter, alpha),
        ("finnhub", FinnhubAdapter, finnhub),
        ("finnhub_news", FinnhubNewsAdapter, finnhub_news),
        ("eodhd", EODHDAdapter, eodhd),
        ("openweathermap", OpenWeatherMapAdapter, owm),
        ("eia", EIAAdapter, eia),
    ]


@pytest.mark.parametrize(
    "name,cls,call",
    _engine_cases(),
    ids=[c[0] for c in _engine_cases()],
)
async def test_engine_adapter_http_error_does_not_leak_key(
    monkeypatch: pytest.MonkeyPatch, name: str, cls: Any, call: Any,
):
    # Every adapter reads its key from the environment at construction.
    for var in (
        "FRED_API_KEY", "ALPHAVANTAGE_API_KEY", "FINNHUB_API_KEY",
        "EODHD_API_KEY", "OPENWEATHERMAP_API_KEY", "EIA_API_KEY",
    ):
        monkeypatch.setenv(var, SECRET)
    adapter = cls()
    fake = _RejectingClient(401)

    async def _client_():
        return fake

    monkeypatch.setattr(adapter, "_client_", _client_)
    with pytest.raises(Exception) as info:  # noqa: PT011 — any adapter error type
        await call(adapter)
    _assert_clean(info.value)
    assert "401" in str(info.value) or "Unauthorized" in str(info.value)


async def test_transport_error_message_is_redacted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINNHUB_API_KEY", SECRET)

    class _BrokenClient:
        async def get(self, url: str, params: dict[str, Any] | None = None, **_: Any):
            raise httpx.ConnectError(f"connect failed for {url}?token={SECRET}")

    adapter = FinnhubAdapter()

    async def _client_():
        return _BrokenClient()

    monkeypatch.setattr(adapter, "_client_", _client_)
    with pytest.raises(httpx.ConnectError) as info:
        await adapter._get("/quote", symbol="AAPL")
    _assert_clean(info.value)
    assert "token=***" in str(info.value)


async def test_tradingeconomics_http_error_does_not_leak_key(monkeypatch: pytest.MonkeyPatch):
    """SEC-2: TradingEconomics sends its key as the ``c`` query value; a 401 must not echo it."""
    from showme.engine.data_sources.macro.tradingeconomics_adapter import TradingEconomicsAdapter

    monkeypatch.setenv("TRADINGECONOMICS_API_KEY", SECRET)
    adapter = TradingEconomicsAdapter()
    fake = _RejectingClient(401)

    async def _client_():
        return fake

    monkeypatch.setattr(adapter, "_client_", _client_)
    with pytest.raises(Exception) as info:  # noqa: PT011 — any adapter error type
        await adapter.calendar(country="united states")
    _assert_clean(info.value)
    assert "401" in str(info.value)


async def test_tradingeconomics_econ_series_http_error_does_not_leak_key(monkeypatch: pytest.MonkeyPatch):
    from showme.engine.data_sources.macro.tradingeconomics_adapter import TradingEconomicsAdapter

    monkeypatch.setenv("TRADINGECONOMICS_API_KEY", SECRET)
    adapter = TradingEconomicsAdapter()

    async def _client_():
        return _RejectingClient(403)

    monkeypatch.setattr(adapter, "_client_", _client_)
    with pytest.raises(Exception) as info:  # noqa: PT011
        await adapter.fetch(DataRequest(kind=DataKind.ECON_SERIES, extra={"indicator": "gdp"}))
    _assert_clean(info.value)


async def test_percent_encoded_key_is_masked_in_errors():
    """A key with reserved characters reaches the URL percent-encoded; that form is masked too."""
    from urllib.parse import quote_plus

    key = "user:pass word"
    url = f"https://provider.test/x?c={quote_plus(key)}"
    out = redact_secrets(f"401 for url {url}", key)
    assert quote_plus(key) not in out
    assert key not in out


async def test_httpx_request_log_line_does_not_carry_the_key(caplog: pytest.LogCaptureFixture):
    """httpx logs every request URL at INFO; with root at INFO that line must not show the key."""
    import logging

    caplog.set_level(logging.INFO, logger="httpx")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    try:
        await client.get("https://provider.test/series", params={"series_id": "DGS10", "api_key": SECRET})
        await client.get("https://provider.test/calendar", params={"c": SECRET, "f": "json"})
    finally:
        await client.aclose()
    httpx_records = [r for r in caplog.records if r.name == "httpx"]
    assert httpx_records, "httpx should log its request lines at INFO"
    assert SECRET not in caplog.text
    assert "api_key=***" in caplog.text
    assert "c=***" in caplog.text
    assert "series_id=DGS10" in caplog.text
