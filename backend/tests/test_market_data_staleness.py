"""Regression tests for the WS-cache staleness TTL (campaign A3, F7).

The WS-fed cache/store paths must not serve frozen-but-plausible candles or a
frozen funding mark price: when the newest data point is older than
``WS_STALENESS_TTL_MULTIPLE × timeframe`` the provider falls through to REST.
With ``use_ws_cache=False`` (the default) behaviour is unchanged.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from showme.engine.data.market_data import (  # noqa: E402
    WS_STALENESS_TTL_MULTIPLE,
    MarketDataProvider,
    _timeframe_ms,
)


class _Cache:
    def __init__(self, df: pd.DataFrame | None, funding: dict | None = None) -> None:
        self.df = df
        self.funding = funding

    def get_ohlcv(self, symbol, timeframe, n=500):
        return self.df

    def get_funding(self, symbol):
        return self.funding


class _Rest:
    def __init__(self) -> None:
        self.kline_calls = 0
        self.ticker_calls = 0

    def get_klines(self, symbol, interval, limit):
        self.kline_calls += 1
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return [
            [now_ms - (5 - i) * 3_600_000, "1", "1", "1", "1", "1",
             now_ms - (5 - i) * 3_600_000 + 3_599_999, "1", 1, "1", "1", "0"]
            for i in range(5)
        ]

    def get_ticker_price(self, symbol):
        self.ticker_calls += 1
        return 123.0


def _cfg() -> dict:
    return {"timeframe": "1h", "candle_limit": 200,
            "data_pipeline": {"use_ws_cache": True}}


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def test_timeframe_ms_parsing():
    assert _timeframe_ms("1m") == 60_000
    assert _timeframe_ms("4h") == 4 * 3_600_000
    assert _timeframe_ms("1d") == 86_400_000
    assert _timeframe_ms("bogus") is None


def _frame(last_open_ms: int, rows: int = 150) -> pd.DataFrame:
    """A frame that passes the legacy >=100-row gate; only the newest
    candle's open_time decides staleness."""
    times = [last_open_ms - (rows - 1 - i) * 3_600_000 for i in range(rows)]
    times[-1] = last_open_ms
    return pd.DataFrame({"open_time": pd.to_datetime(times, unit="ms"),
                         "close": [1.0] * rows})


def test_fresh_cache_is_served(tmp_path):
    df = _frame(_now_ms())
    rest = _Rest()
    mdp = MarketDataProvider(rest, _cfg(), cache=_Cache(df), store=None)
    out = mdp.get_ohlcv("BTCUSDT")
    assert out is not None
    assert rest.kline_calls == 0, "fresh cache must be served without REST"


def test_stale_cache_falls_through_to_rest(tmp_path):
    stale_age = (WS_STALENESS_TTL_MULTIPLE + 1) * 3_600_000
    df = _frame(_now_ms() - stale_age)  # passes the row gate, fails the TTL
    rest = _Rest()
    mdp = MarketDataProvider(rest, _cfg(), cache=_Cache(df), store=None)
    out = mdp.get_ohlcv("BTCUSDT")
    assert rest.kline_calls == 1, "stale cache must fall through to REST"
    assert out is not None and len(out) == 5


def test_funding_mark_price_ttl():
    cfg = _cfg()
    fresh = _Cache(None, funding={"mark_price": 99.0, "time": _now_ms() - 1_000})
    mdp = MarketDataProvider(_Rest(), cfg, cache=fresh, store=None)
    assert mdp.get_current_price("BTCUSDT") == pytest.approx(99.0)

    stale = _Cache(None, funding={"mark_price": 99.0,
                                  "time": _now_ms() - (WS_STALENESS_TTL_MULTIPLE + 1) * 3_600_000})
    rest = _Rest()
    mdp2 = MarketDataProvider(rest, cfg, cache=stale, store=None)
    assert mdp2.get_current_price("BTCUSDT") == pytest.approx(123.0)
    assert rest.ticker_calls == 1


def test_legacy_rest_only_path_unchanged_without_ws_cache():
    stale = _frame(_now_ms() - 86_400_000)
    rest = _Rest()
    mdp = MarketDataProvider(rest, {"timeframe": "1h", "candle_limit": 200},
                             cache=_Cache(stale), store=None)
    out = mdp.get_ohlcv("BTCUSDT")
    assert out is not None and len(out) == 5
