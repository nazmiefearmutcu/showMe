"""2026-09-17: CCXTFailoverAdapter must reuse ccxt exchange instances.

A fresh ccxt instance pays ``load_markets`` on its first OHLCV call —
measured 2.6-3.2 s on this machine vs 0.26 s once warm — and MIS issues one
fetch per (symbol, timeframe), so per-call construction made a Crypto sweep
crawl at ~1 fetch/s. These tests pin: the pool is bounded, fetches reuse
pooled instances (no per-fetch construction), and the failover chain still
advances when an exchange errors.
"""
from __future__ import annotations

from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.crypto.ccxt_failover_adapter import (
    CCXTFailoverAdapter,
    _EXCHANGE_POOL_SIZE,
)

_BARS = [[1, 1.0, 1.5, 0.5, 1.2, 10.0]] * 60


class _FakeExchange:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.calls = 0

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        self.calls += 1
        return list(_BARS)


class _FakeBinance(_FakeExchange):
    created = 0

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        super().__init__(cfg)
        _FakeBinance.created += 1


class _FakeCcxtModule:
    binance = _FakeBinance


def _req() -> DataRequest:
    return DataRequest(
        kind=DataKind.OHLCV,
        instrument=Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO),
        interval="1h",
        limit=60,
    )


async def test_pool_is_bounded_and_reused() -> None:
    _FakeBinance.created = 0
    ad = CCXTFailoverAdapter()
    ad._ccxt = _FakeCcxtModule  # type: ignore[assignment]

    first = ad._exchange("binance")
    second = ad._exchange("binance")
    assert first is not second                       # round-robin advances
    assert _FakeBinance.created == _EXCHANGE_POOL_SIZE
    seen = [first, second]
    for _ in range(_EXCHANGE_POOL_SIZE - 2):
        seen.append(ad._exchange("binance"))
    assert ad._exchange("binance") is first          # ...and wraps around
    assert len({id(x) for x in seen}) == _EXCHANGE_POOL_SIZE

    for _ in range(5):
        df = await ad.fetch(_req())
        assert len(df) == 60
    # Five fetches must not construct a single extra exchange instance.
    assert _FakeBinance.created == _EXCHANGE_POOL_SIZE


async def test_failover_chain_advances_on_error() -> None:
    class _BoomBinance(_FakeExchange):
        def fetch_ohlcv(self, *a, **k):
            raise RuntimeError("binance down")

    class _OkBybit(_FakeExchange):
        pass

    class _Mod:
        binance = _BoomBinance
        bybit = _OkBybit

    ad = CCXTFailoverAdapter()
    ad._ccxt = _Mod  # type: ignore[assignment]
    df = await ad.fetch(_req())
    assert len(df) == 60
