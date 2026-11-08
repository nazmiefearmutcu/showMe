"""FRH#3: a Binance premiumIndex response without ``lastFundingRate`` must yield
a null Binance leg, never 0.0. A substituted zero would enter the venue average
and provider_count and contradict the seed's "missing venues are null" claim.
No network: a URL-routed fake client."""
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
    def __init__(self, premium_body: Any) -> None:
        self.premium_body = premium_body

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _Resp:
        if "premiumIndex" in url:
            return _Resp(200, self.premium_body)
        if "funding/history" in url:
            return _Resp(200, {"result": {"list": [{"fundingRate": "0.00005"}]}})
        if "okx" in url:
            return _Resp(200, {"data": [{"fundingRate": "0.0003", "settFundingRate": "0.0001"}]})
        return _Resp(404, {})


def _row(premium_body: Any) -> dict[str, Any]:
    fn = frh_mod.FRHFunction()
    fn._http_client = _Client(premium_body)
    result = asyncio.run(fn.execute(symbols="BTCUSDT"))
    return result.data["rows"][0]


def test_missing_last_funding_rate_is_null_not_zero():
    row = _row({"symbol": "BTCUSDT", "markPrice": "100"})
    assert row["binance"] is None, row
    assert row["provider_count"] == 2, row


def test_missing_binance_rate_is_excluded_from_average():
    row = _row({"symbol": "BTCUSDT"})
    assert row["avg"] == (0.00005 + 0.0001) / 2, row


def test_empty_last_funding_rate_is_null_not_zero():
    row = _row({"lastFundingRate": ""})
    assert row["binance"] is None, row
    assert row["provider_count"] == 2, row


def test_present_binance_rate_is_still_used():
    row = _row({"lastFundingRate": "0.0002"})
    assert row["binance"] == 0.0002, row
    assert row["provider_count"] == 3, row
