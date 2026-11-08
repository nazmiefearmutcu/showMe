"""P2a-g15 regression tests for ONCH (On-Chain Metrics) and MICRO (Market Microstructure).

All network access is replaced by in-test fakes so the suite runs offline.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.instrument import AssetClass, Instrument

# --------------------------------------------------------------------------
# Shared fakes
# --------------------------------------------------------------------------


class _Resp:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _depth_payload(levels: int = 20) -> dict[str, Any]:
    bids = [[f"{100.0 - i * 0.5:.2f}", f"{1.0 + i * 0.1:.4f}"] for i in range(levels)]
    asks = [[f"{100.5 + i * 0.5:.2f}", f"{1.5 + i * 0.1:.4f}"] for i in range(levels)]
    return {"lastUpdateId": 1, "bids": bids, "asks": asks}


def _kline_rows(n: int = 200) -> list[list[Any]]:
    """Binance kline rows: [openTime, o, h, l, close, volume, closeTime, quoteVol,
    trades, takerBuyBase, takerBuyQuote, ignore]."""
    rows: list[list[Any]] = []
    price = 100.0
    for i in range(n):
        drift = 0.001 if i % 3 else -0.002
        price = price * (1.0 + drift)
        vol = 1.0 + (i % 7) * 0.3
        taker_buy = vol * (0.6 if i % 2 else 0.4)
        rows.append(
            [i, f"{price:.4f}", f"{price:.4f}", f"{price:.4f}", f"{price:.4f}",
             f"{vol:.5f}", i, "0", 10, f"{taker_buy:.5f}", "0", "0"]
        )
    return rows


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient; routes by URL and records send times."""

    depth_delay = 0.0
    sent_at: list[datetime] = []
    received_at: list[datetime] = []
    depth_levels = 20
    klines: list[list[Any]] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, params: dict[str, Any] | None = None, **_: Any) -> _Resp:
        now = datetime.now(timezone.utc)
        if "depth" in url:
            self.__class__.sent_at.append(now)
            if self.__class__.depth_delay:
                await asyncio.sleep(self.__class__.depth_delay)
            self.__class__.received_at.append(datetime.now(timezone.utc))
            return _Resp(_depth_payload(self.__class__.depth_levels))
        rows = self.__class__.klines if self.__class__.klines is not None else _kline_rows()
        return _Resp(rows)


def _reset_fake(depth_delay: float = 0.0) -> None:
    _FakeAsyncClient.depth_delay = depth_delay
    _FakeAsyncClient.sent_at = []
    _FakeAsyncClient.received_at = []
    _FakeAsyncClient.depth_levels = 20
    _FakeAsyncClient.klines = None


def _patch_micro_http(monkeypatch: Any) -> None:
    from showme.engine.functions.screen import micro as micro_mod

    monkeypatch.setattr(micro_mod.httpx, "AsyncClient", _FakeAsyncClient)


def _btc() -> Instrument:
    return Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO)


# --------------------------------------------------------------------------
# MICRO#2 — as_of must be the request/snapshot time, not the response time
# --------------------------------------------------------------------------


def test_micro_as_of_is_request_time_not_response_time(monkeypatch: Any) -> None:
    from showme.engine.functions.screen.micro import MICROFunction

    _patch_micro_http(monkeypatch)
    _reset_fake(depth_delay=0.3)

    result = asyncio.run(MICROFunction(deps=None).execute(instrument=_btc(), depth_levels=20))
    data = result.data
    assert data["status"] == "ok"

    as_of = datetime.fromisoformat(data["as_of"])
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    sent = _FakeAsyncClient.sent_at[0]
    received = _FakeAsyncClient.received_at[0]

    # The response arrived ~0.3 s after the request was sent; as_of must be
    # the send time (snapshot is taken no earlier than the request), not the
    # moment the handler finished parsing the response.
    assert (received - sent).total_seconds() >= 0.25
    assert abs((as_of - sent).total_seconds()) < 0.05, (
        f"as_of {as_of.isoformat()} should match request send {sent.isoformat()}, "
        f"not response parse time"
    )
    assert "request" in data["field_dictionary"]["as_of"].lower()


# --------------------------------------------------------------------------
# ONCH — fake keyless provider client (mempool.space / CoinGecko / DefiLlama / Blockscout)
# --------------------------------------------------------------------------

_ONCH_MEMPOOL_COUNT = 59_204  # what /api/mempool reports (the true backlog)
_ONCH_BLOCK_TXS = [994, 1961, 1500, 1200, 900, 800, 700, 600]  # projected window sum = 8655


class _OnchClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.urls: list[str] = []

    async def get(self, url: str, headers: Any = None, timeout: Any = None, **_: Any) -> _Resp:
        self.urls.append(url)
        if self.fail:
            raise ConnectionError("simulated outage")
        if url.endswith("/v1/fees/recommended"):
            return _Resp({"fastestFee": 3, "halfHourFee": 2, "hourFee": 2,
                          "economyFee": 1, "minimumFee": 1})
        if url.endswith("/v1/fees/mempool-blocks"):
            return _Resp([{"nTx": n, "blockVSize": 990000.0} for n in _ONCH_BLOCK_TXS])
        if url.endswith("/v1/difficulty-adjustment"):
            return _Resp({"difficultyChange": 1.5, "progressPercent": 40.0, "remainingBlocks": 1200})
        if url.endswith("/v1/mining/hashrate/3d"):
            return _Resp({"currentHashrate": 9.5e20, "currentDifficulty": 1.2e14})
        if url.endswith("/blocks/tip/height"):
            return _Resp(900_000)
        if url.endswith("/api/mempool"):
            return _Resp({"count": _ONCH_MEMPOOL_COUNT, "vsize": 1, "total_fee": 1, "fee_histogram": []})
        if "coingecko" in url:
            return _Resp({"data": {"market_cap_percentage": {"btc": 55.0},
                                   "total_market_cap": {"usd": 2.5e12},
                                   "total_volume": {"usd": 9.0e10}}})
        if "defillama" in url:
            return _Resp([{"name": "Ethereum", "tvl": 6.0e10}])
        if "blockscout" in url:
            return _Resp({"gas_prices": {"average": 3.2}, "coin_price": "3000.5"})
        return _Resp({}, status_code=404)


def _patch_onch_client(monkeypatch: Any, client: _OnchClient) -> None:
    import showme.providers._http as http_mod

    async def _get_client() -> _OnchClient:
        return client

    monkeypatch.setattr(http_mod, "get_client", _get_client)


def _run_onch(monkeypatch: Any, client: _OnchClient) -> Any:
    from showme.engine.functions.misc.onch import ONCHFunction

    _patch_onch_client(monkeypatch, client)
    return asyncio.run(ONCHFunction().execute())


# --------------------------------------------------------------------------
# ONCH#2 — data_mode must not claim "delayed" for rows that are live
# --------------------------------------------------------------------------


def test_onch_live_payload_data_mode_matches_live_rows(monkeypatch: Any) -> None:
    result = _run_onch(monkeypatch, _OnchClient())
    data = result.data
    assert data["status"] == "ok"
    assert all(r["source"] in {"mempool", "coingecko", "defillama", "blockscout"} for r in data["rows"])
    # Every row was fetched live in this call, so the mode must say live.
    assert data["data_mode"] == "live", data["data_mode"]


def test_onch_outage_data_mode_is_provider_unavailable_not_not_configured(monkeypatch: Any) -> None:
    # The key is configured (keyless API); the upstream is down. The mode must
    # say so instead of claiming the provider is not configured.
    result = _run_onch(monkeypatch, _OnchClient(fail=True))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["data_mode"] == "provider_unavailable"
    assert data["rows"] == []


def test_onch_mempool_backlog_is_the_mempool_count_not_the_projected_sum(monkeypatch: Any) -> None:
    result = _run_onch(monkeypatch, _OnchClient())
    data = result.data
    assert data["status"] == "ok"
    rows = {r["metric"]: r for r in data["rows"]}

    # The label says mempool backlog: it must be the mempool-wide count that
    # /api/mempool reports, not the sum over the 8 projected blocks.
    assert rows["Mempool Backlog"]["value"] == f"{_ONCH_MEMPOOL_COUNT:,}"
    assert "projected" not in rows["Mempool Backlog"]["context"].lower()

    # The projected-window sum stays available, honestly labelled as such.
    projected = rows["Projected Block Txs"]
    assert projected["value"] == f"{sum(_ONCH_BLOCK_TXS):,}"
    assert "projected" in projected["context"].lower()
    assert data["cards"][1]["value"] == f"{_ONCH_MEMPOOL_COUNT:,} tx"
    assert f"{_ONCH_MEMPOOL_COUNT:,} txs in the mempool" in data["summary"]


def test_onch_unsupported_chain_is_explicit_input_error(monkeypatch: Any) -> None:
    # The pane's chain control offers BTC/ETH. Only Bitcoin is served by the
    # keyless vitals, so ETH must be an explicit input error, never a silently
    # Bitcoin payload returned under an Ethereum request.
    from showme.engine.functions.misc.onch import ONCHFunction

    client = _OnchClient()
    _patch_onch_client(monkeypatch, client)
    result = asyncio.run(ONCHFunction().execute(chain="ETH"))
    data = result.data
    assert data["status"] == "input_error"
    assert data["rows"] == []
    assert data.get("next_actions")
    assert client.urls == [], "no upstream call for an unsupported chain"


def test_onch_payload_carries_as_of_request_time(monkeypatch: Any) -> None:
    before = datetime.now(timezone.utc)
    result = _run_onch(monkeypatch, _OnchClient())
    after = datetime.now(timezone.utc)
    as_of = datetime.fromisoformat(result.data["as_of"])
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    assert before <= as_of <= after
