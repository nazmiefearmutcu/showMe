"""FRH#3: the Bybit leg must be a settled funding rate. The v5 tickers
``fundingRate`` is the pending estimate for the upcoming settlement, so the
handler reads the settled history endpoint instead. No network: a URL-routed
fake records every request."""
from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.functions.screen import frh as frh_mod


class _Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        return self._body


class _Client:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _Resp:
        self.urls.append(url)
        if "bybit" in url and "funding/history" in url:
            return _Resp(200, {"retCode": 0, "result": {"category": "linear", "list": [
                {"symbol": "BTCUSDT", "fundingRate": "0.00005", "fundingRateTimestamp": "1700000000000"},
            ]}})
        if "bybit" in url and "tickers" in url:
            # The pending estimate for the next settlement; must not be used.
            return _Resp(200, {"result": {"list": [{"fundingRate": "0.0009", "nextFundingTime": "1700003600000"}]}})
        if "premiumIndex" in url:
            return _Resp(200, {"lastFundingRate": "0.0001"})
        if "okx" in url:
            return _Resp(200, {"data": [{"fundingRate": "0.0003", "settFundingRate": "0.0001"}]})
        return _Resp(404, {})


def _run(client: _Client):
    fn = frh_mod.FRHFunction()
    fn._http_client = client
    return asyncio.run(fn.execute(symbols="BTCUSDT"))


def test_bybit_leg_uses_settled_funding_history_not_pending_ticker_estimate():
    client = _Client()
    result = _run(client)
    row = result.data["rows"][0]
    assert row["bybit"] == 0.00005, row
    assert any("/v5/market/funding/history" in u for u in client.urls), client.urls
    assert not any("/v5/market/tickers" in u for u in client.urls), client.urls


def test_bybit_average_contains_only_settled_rates():
    result = _run(_Client())
    row = result.data["rows"][0]
    assert row["avg"] == (0.0001 + 0.00005 + 0.0001) / 3, row


def test_bybit_unavailable_history_yields_null_not_estimate():
    class _NoBybit(_Client):
        async def get(self, url: str, params: dict[str, Any] | None = None) -> _Resp:
            if "bybit" in url:
                self.urls.append(url)
                return _Resp(404, {})
            return await super().get(url, params)

    row = _run(_NoBybit()).data["rows"][0]
    assert row["bybit"] is None, row
    assert row["provider_count"] == 2, row
