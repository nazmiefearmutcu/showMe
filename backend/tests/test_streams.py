"""Round 29 — Stream hub + Binance ticker parser."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest

from showme.streams import (
    PollingSource,
    Source,
    StreamHub,
    Tick,
    fetch_binance_24h_ticker,
    is_crypto_symbol,
    parse_binance_ticker,
)


def test_is_crypto_symbol_recognizes_usdt_pairs() -> None:
    assert is_crypto_symbol("BTCUSDT")
    assert is_crypto_symbol("ETHUSD")
    assert is_crypto_symbol("SUSDT")
    assert is_crypto_symbol("4USDT")
    assert not is_crypto_symbol("AAPL")


def test_parse_binance_ticker_extracts_canonical_fields() -> None:
    payload = {
        "e": "24hrTicker",
        "E": 1714508400000,
        "s": "BTCUSDT",
        "c": "60000.50",
        "P": "1.234",
        "v": "12345",
        "b": "59999.10",
        "a": "60000.55",
    }
    tick = parse_binance_ticker(payload)
    assert tick.symbol == "BTCUSDT"
    assert tick.price == pytest.approx(60000.50)
    assert tick.change_pct == pytest.approx(1.234)
    assert tick.volume == pytest.approx(12345)
    assert tick.bid == pytest.approx(59999.10)
    assert tick.ask == pytest.approx(60000.55)
    assert tick.source == "binance"
    assert tick.ts == pytest.approx(1714508400.0)


def test_parse_binance_ticker_handles_missing_optional_fields() -> None:
    tick = parse_binance_ticker({"s": "ethusdt", "c": "3000"})
    assert tick.symbol == "ETHUSDT"
    assert tick.price == 3000
    assert tick.bid is None
    assert tick.ask is None


def test_fetch_binance_24h_ticker_raises_on_spot_failure(monkeypatch) -> None:
    """FUNC-01 P0: spot ticker must NOT silently fall back to futures.

    Per the audit, the previous behavior swapped venues mid-stream when spot
    failed, which yielded futures pricing under a spot ``Tick.symbol``. Callers
    that want futures must opt in via ``fetch_binance_futures_24h_ticker``.
    """

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def fake_spot_get(url: str, *_args, **_kwargs) -> FakeResponse:
        # Spot endpoint returns the Binance "invalid symbol" envelope.
        return FakeResponse({"code": -1121, "msg": "Invalid symbol."})

    monkeypatch.setattr("showme.streams.requests.get", fake_spot_get)

    with pytest.raises(RuntimeError):
        fetch_binance_24h_ticker("4USDT")


def test_fetch_binance_futures_24h_ticker_explicit_opt_in(monkeypatch) -> None:
    """Caller must explicitly request futures; tick source is ``binance_futures``."""
    from showme.streams import fetch_binance_futures_24h_ticker

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def fake_get(url: str, *_args, **_kwargs) -> FakeResponse:
        # Only the futures endpoint should ever be hit on this opt-in path.
        assert "fapi.binance.com" in url, f"unexpected URL hit: {url}"
        return FakeResponse({
            "symbol": "4USDT",
            "lastPrice": "0.01231",
            "priceChangePercent": "-5.482",
            "volume": "518439928",
            "closeTime": 1714508400000,
        })

    monkeypatch.setattr("showme.streams.requests.get", fake_get)

    tick = fetch_binance_futures_24h_ticker("4USDT")
    assert tick.symbol == "4USDT"
    assert tick.price == pytest.approx(0.01231)
    assert tick.change_pct == pytest.approx(-5.482)
    assert tick.source == "binance_futures"


# ── StreamHub tests with a fake source ────────────────────────────────────


class FakeSource(Source):
    def __init__(self, symbol: str, ticks: list[Tick]) -> None:
        super().__init__(symbol)
        self._ticks = ticks

    async def run(self) -> AsyncIterator[Tick]:
        for tick in self._ticks:
            if self.stopping:
                return
            await asyncio.sleep(0)
            yield tick
        # Keep the source alive until the hub asks us to stop.
        while not self.stopping:
            await asyncio.sleep(0.01)


def test_stream_hub_replays_last_tick_to_new_subscriber() -> None:
    async def _run() -> None:
        ticks_btc = [Tick(symbol="BTCUSDT", price=60_000.0, source="fake")]
        hub = StreamHub(crypto_factory=lambda s: FakeSource(s, ticks_btc))
        sub_a = await hub.subscribe("BTCUSDT")
        async with sub_a as queue:
            tick = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert tick.price == 60_000.0
            # Second subscriber should see the same last tick replayed.
            sub_b = await hub.subscribe("BTCUSDT")
            async with sub_b as q2:
                replay = await asyncio.wait_for(q2.get(), timeout=0.5)
                assert replay.price == 60_000.0

    asyncio.run(_run())


def test_stream_hub_tears_down_source_on_last_unsubscribe() -> None:
    async def _run() -> None:
        ticks: list[Tick] = []
        hub = StreamHub(crypto_factory=lambda s: FakeSource(s, ticks))
        sub = await hub.subscribe("ETHUSDT")
        async with sub:
            assert "ETHUSDT" in hub._channels
        # Allow the hub to drain its release lock.
        await asyncio.sleep(0)
        assert "ETHUSDT" not in hub._channels

    asyncio.run(_run())


def test_stream_hub_multiple_subscribers_get_each_tick() -> None:
    async def _run() -> None:
        ticks = [
            Tick(symbol="BTCUSDT", price=1.0, source="fake"),
            Tick(symbol="BTCUSDT", price=2.0, source="fake"),
        ]
        hub = StreamHub(crypto_factory=lambda s: FakeSource(s, ticks))
        sub_a = await hub.subscribe("BTCUSDT")
        sub_b = await hub.subscribe("BTCUSDT")

        async def drain(queue: asyncio.Queue[Tick], target: int) -> list[float]:
            out: list[float] = []
            while len(out) < target:
                tick = await asyncio.wait_for(queue.get(), timeout=1.0)
                out.append(tick.price)
            return out

        async with sub_a as qa, sub_b as qb:
            seen_a, seen_b = await asyncio.gather(drain(qa, 2), drain(qb, 1))
        assert 2.0 in seen_a
        assert seen_b  # at least one tick reached the second subscriber

    asyncio.run(_run())


def test_polling_source_emits_until_stopped() -> None:
    async def _run() -> None:
        async def fake_fetch(symbol: str) -> dict:
            return {"data": {"regularMarketPrice": 200.0, "previousClose": 195.0}}

        src = PollingSource("AAPL", fetch=fake_fetch, interval=0.05)
        seen: list[Tick] = []

        async def consume() -> None:
            async for tick in src.run():
                seen.append(tick)
                if len(seen) >= 2:
                    src.stop()
                    return

        await asyncio.wait_for(consume(), timeout=2.0)
        assert len(seen) == 2
        assert seen[0].source == "polling"
        assert seen[0].change_pct == pytest.approx(((200 / 195) - 1) * 100)

    asyncio.run(_run())


def test_polling_source_reads_des_extras_raw_quote() -> None:
    async def _run() -> None:
        async def fake_fetch(symbol: str) -> dict:
            return {
                "data": {
                    "symbol": symbol,
                    "extras": {
                        "raw": {
                            "currentPrice": 282.62,
                            "regularMarketChangePercent": 4.15,
                            "regularMarketVolume": 50_000_000,
                            "bid": 282.5,
                            "ask": 282.7,
                        },
                    },
                },
            }

        src = PollingSource("AAPL", fetch=fake_fetch, interval=0.05)
        async for tick in src.run():
            src.stop()
            assert tick.price == pytest.approx(282.62)
            assert tick.change_pct == pytest.approx(4.15)
            assert tick.volume == pytest.approx(50_000_000)
            assert tick.bid == pytest.approx(282.5)
            assert tick.ask == pytest.approx(282.7)
            return
        raise AssertionError("no tick emitted")

    asyncio.run(_run())


def test_stream_hub_raises_when_polling_factory_missing_for_equity() -> None:
    async def _run() -> None:
        hub = StreamHub()
        with pytest.raises(RuntimeError):
            await hub.subscribe("AAPL")

    asyncio.run(_run())
