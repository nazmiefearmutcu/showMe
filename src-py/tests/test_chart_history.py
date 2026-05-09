from __future__ import annotations

from showme.chart_history import (
    _binance_kline_endpoints,
    _dedupe_sort_trim,
    _rows_from_binance_klines,
    normalize_history_interval,
    parse_history_bars,
)


def test_parse_history_bars_clamps_terminal_depth() -> None:
    assert parse_history_bars("3000") == 3000
    assert parse_history_bars("999999") == 20000
    assert parse_history_bars("bad", default=1500) == 1500


def test_normalize_history_interval_accepts_terminal_aliases() -> None:
    assert normalize_history_interval("60m") == "1h"
    assert normalize_history_interval("1wk") == "1w"
    assert normalize_history_interval("wat") == "1d"


def test_rows_from_binance_klines_shape_ohlcv() -> None:
    rows = _rows_from_binance_klines([
        [1_700_000_000_000, "100", "110", "90", "105", "12.5"],
    ])

    assert rows == [{
        "date": "2023-11-14T22:13:20+00:00",
        "time": 1_700_000_000,
        "open": 100.0,
        "high": 110.0,
        "low": 90.0,
        "close": 105.0,
        "volume": 12.5,
    }]


def test_binance_kline_endpoints_use_spot_and_futures_paths() -> None:
    assert _binance_kline_endpoints() == (
        ("https://api.binance.com/api/v3/klines", "binance_spot"),
        ("https://fapi.binance.com/fapi/v1/klines", "binance_futures"),
    )


def test_dedupe_sort_trim_keeps_latest_rows() -> None:
    rows = [
        {"time": 3, "close": 3},
        {"time": 1, "close": 1},
        {"time": 2, "close": 2},
        {"time": 2, "close": 22},
    ]

    assert _dedupe_sort_trim(rows, 2) == [
        {"time": 2, "close": 22},
        {"time": 3, "close": 3},
    ]
