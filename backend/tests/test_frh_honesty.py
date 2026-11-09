"""FRH#2 / FRH#3: universe basis is labelled, OKX uses the settled rate, and
single-venue rows never carry a cross-venue signal. No network: the HTTP client
is a URL-routed fake."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.functions.screen import frh as frh_mod


class _Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        return self._body


class _RoutedClient:
    def __init__(self, *, bybit: bool = True, okx_missing: bool = False, ticker: list | None = None) -> None:
        self.bybit = bybit
        self.okx_missing = okx_missing
        self.okx = {"fundingRate": "0.0002", "settFundingRate": "0.0001",
                    "method": "current_period", "settState": "settled"}
        self.ticker = ticker
        self.ticker_calls = 0

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _Resp:
        if "ticker/24hr" in url:
            self.ticker_calls += 1
            return _Resp(200, self.ticker) if self.ticker is not None else _Resp(404, {})
        if "premiumIndex" in url:
            return _Resp(200, {"lastFundingRate": "0.0001"})
        if "bybit" in url:
            if not self.bybit:
                return _Resp(404, {})
            return _Resp(200, {"result": {"list": [{"fundingRate": "0.00005"}]}})
        if "okx" in url:
            if self.okx_missing:
                return _Resp(404, {})
            return _Resp(200, {"data": [self.okx]})
        return _Resp(404, {})


@pytest.fixture(autouse=True)
def _reset_ranking(monkeypatch):
    monkeypatch.setattr(frh_mod, "_ranking_cache", None)


def test_okx_uses_settled_rate_not_current_period_estimate():
    client = _RoutedClient()
    fn = frh_mod.FRHFunction()
    fn._http_client = client
    result = asyncio.run(fn.execute(symbols="BTCUSDT"))
    row = result.data["rows"][0]
    # Binance and OKX are both last-settled rates; OKX fundingRate (0.0002) is an estimate.
    assert row["okx"] == pytest.approx(0.0001), row
    assert row["avg"] == pytest.approx((0.0001 + 0.00005 + 0.0001) / 3)


def test_single_venue_row_suppresses_cross_venue_signal():
    client = _RoutedClient(bybit=False, okx_missing=True)
    fn = frh_mod.FRHFunction()
    fn._http_client = client
    result = asyncio.run(fn.execute(symbols="BTCUSDT"))
    row = result.data["rows"][0]
    assert row["provider_count"] == 1
    assert row["signal_suppressed"] is True, row
    assert row["interpretation"] == "insufficient venues (fewer than 2)", row


def test_multi_venue_row_keeps_its_signal():
    client = _RoutedClient()
    fn = frh_mod.FRHFunction()
    fn._http_client = client
    result = asyncio.run(fn.execute(symbols="BTCUSDT"))
    row = result.data["rows"][0]
    assert row["signal_suppressed"] is False
    assert row["interpretation"] != "insufficient venues (fewer than 2)"


def test_universe_basis_is_labelled_for_each_selection_path():
    ticker = [{"symbol": f"COIN{i:03d}USDT", "quoteVolume": str(1_000_000 - i)} for i in range(60)]
    fn = frh_mod.FRHFunction()
    fn._http_client = _RoutedClient(ticker=ticker)
    ranked = asyncio.run(fn.execute(limit=30))
    assert ranked.data["universe_basis"] == "binance_24h_quote_volume"
    default = asyncio.run(_default_run())
    assert default.data["universe_basis"] == "default_list"
    explicit = asyncio.run(_explicit_run())
    assert explicit.data["universe_basis"] == "explicit_symbols"


async def _default_run():
    fn = frh_mod.FRHFunction()
    fn._http_client = _RoutedClient()
    return await fn.execute(limit=5)


async def _explicit_run():
    fn = frh_mod.FRHFunction()
    fn._http_client = _RoutedClient()
    return await fn.execute(symbols="BTCUSDT,ETHUSDT")
