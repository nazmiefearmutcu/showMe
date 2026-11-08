"""DES must not present all-time high/low as a 52-week range (DES#1).

CoinGecko /coins/{id} market_data has no 52-week fields, and the mapper used to
substitute ATH/ATL into fiftyTwoWeekHigh/Low, so the pane showed a 2013 low as a
current '52w low'. A crypto 52-week range is not provided here, so it stays
missing (None) while the true all-time values remain under all_time_high/low.
"""
from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.des import DESFunction, _coingecko_to_des


def _run(coro):
    return asyncio.run(coro)


def _btc_payload() -> dict[str, Any]:
    return {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "categories": ["Cryptocurrency"],
        "market_data": {
            "current_price": {"usd": 75_737.0},
            "ath": {"usd": 126_080.0},
            "ath_date": {"usd": "2025-10-06T00:00:00.000Z"},
            "atl": {"usd": 67.81},
            "atl_date": {"usd": "2013-07-05T00:00:00.000Z"},
        },
    }


def test_mapper_does_not_substitute_ath_atl_for_52w_range() -> None:
    out = _coingecko_to_des(_btc_payload(), "BTCUSDT")
    assert out["fiftyTwoWeekHigh"] is None  # was 126080.0 (the ATH)
    assert out["fiftyTwoWeekLow"] is None   # was 67.81 (the 2013 ATL)
    # the real all-time values are still reported under their own names
    assert out["all_time_high"] == 126_080.0
    assert out["all_time_low"] == 67.81


class _FakeCoinGecko:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        return self.payload


def test_des_execute_crypto_leaves_52w_missing_not_all_time_extremes() -> None:
    fn = DESFunction()
    fn.deps = FunctionDeps(coingecko=_FakeCoinGecko(_btc_payload()))
    inst = Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO, exchange="BINANCE",
                      currency="USDT", name="Bitcoin")
    result = _run(fn.execute(inst))
    assert result.data["fiftyTwoWeekHigh"] is None
    assert result.data["fiftyTwoWeekLow"] is None
    assert result.data["all_time_high"] == 126_080.0
