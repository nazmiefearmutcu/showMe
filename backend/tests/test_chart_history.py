from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from showme.chart_history import (
    DeepHistoryResult,
    OhlcvLongestHistoryWrapper,
    _binance_kline_endpoints,
    _dedupe_sort_trim,
    _days_from_request,
    _rows_from_binance_klines,
    _rows_from_stooq_csv,
    _stooq_symbol,
    fetch_longest_history,
    longest_history_rows_to_dataframe,
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


def test_stooq_symbol_routes_by_asset_class() -> None:
    assert _stooq_symbol("AAPL", "EQUITY") == "aapl.us"
    assert _stooq_symbol("BTCUSDT", "CRYPTO") == "btcusd"
    assert _stooq_symbol("ETHUSDC", "CRYPTO") == "ethusd"
    assert _stooq_symbol("EURUSD", "FX") == "eurusd"
    assert _stooq_symbol("EURUSD=X", "FX") == "eurusd"
    assert _stooq_symbol("SPX", "INDEX") == "^spx"
    assert _stooq_symbol("^DJI", "INDEX") == "^dji"
    assert _stooq_symbol("GC=F", "COMMODITY") == "gc.f"
    # asset_class unknown → safe fallback for US equities
    assert _stooq_symbol("MSFT", "") == "msft.us"
    assert _stooq_symbol("", "EQUITY") == ""


def test_rows_from_stooq_csv_parses_eod_payload() -> None:
    csv = "Date,Open,High,Low,Close,Volume\n2020-01-02,100,110,99,108,1500\n2020-01-03,108,112,107,111,2100\n"
    rows = _rows_from_stooq_csv(csv)

    assert len(rows) == 2
    assert rows[0]["close"] == 108.0
    assert rows[1]["close"] == 111.0
    # Date is preserved as ISO with UTC tz and time is unix-seconds.
    assert rows[0]["date"].startswith("2020-01-02")
    assert rows[0]["time"] < rows[1]["time"]


def test_rows_from_stooq_csv_skips_malformed_lines() -> None:
    csv = "Date,Open,High,Low,Close\n2020-01-02,1,2,0,1.5\nN/A,,,,\n2020-bad,,,,\n"
    rows = _rows_from_stooq_csv(csv)

    assert len(rows) == 1
    assert rows[0]["close"] == 1.5
    assert rows[0]["volume"] is None  # no volume column


def test_fetch_longest_history_picks_oldest_first_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    """The orchestrator must prefer the source whose earliest bar is oldest,
    regardless of provider order or asset_class.
    """
    monkeypatch.setenv("STOOQ_API_KEY", "test-key")

    yahoo_result = DeepHistoryResult(
        rows=[
            {"date": "2014-09-17T00:00:00+00:00", "time": 1_410_912_000, "close": 1.0},
            {"date": "2014-09-18T00:00:00+00:00", "time": 1_410_998_400, "close": 2.0},
        ],
        source="yahoo_chart",
        metadata={"bars_returned": 2},
    )
    binance_result = DeepHistoryResult(
        rows=[
            {"date": "2017-08-17T00:00:00+00:00", "time": 1_502_928_000, "close": 4_200.0},
            {"date": "2017-08-18T00:00:00+00:00", "time": 1_503_014_400, "close": 4_300.0},
        ],
        source="binance_spot",
        metadata={"bars_returned": 2},
    )
    stooq_result = DeepHistoryResult(
        rows=[
            {"date": "2010-07-17T00:00:00+00:00", "time": 1_279_324_800, "close": 0.05},
            {"date": "2010-07-18T00:00:00+00:00", "time": 1_279_411_200, "close": 0.06},
        ],
        source="stooq",
        metadata={"bars_returned": 2},
    )

    with patch(
        "showme.chart_history.fetch_yahoo_history",
        new=AsyncMock(return_value=yahoo_result),
    ), patch(
        "showme.chart_history.fetch_binance_history",
        new=AsyncMock(return_value=binance_result),
    ), patch(
        "showme.chart_history.fetch_stooq_history",
        new=AsyncMock(return_value=stooq_result),
    ):
        out = asyncio.run(
            fetch_longest_history(
                symbol="BTCUSDT", asset_class="CRYPTO",
                interval="1d", days=365 * 25, bars=1500,
            )
        )

    assert out.source == "stooq", "Stooq has the oldest first bar (2010) — must win"
    assert out.metadata["selection_reason"] == "oldest_first_bar"
    considered_names = {entry["name"] for entry in out.metadata["sources_considered"]}
    assert considered_names == {"yahoo", "binance", "stooq"}


def test_fetch_longest_history_falls_back_when_some_providers_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider exception must not poison the race — surviving providers
    still compete and the deepest one wins. For non-crypto asset_class,
    Binance is not raced at all (it can only serve crypto pairs).
    """
    monkeypatch.setenv("STOOQ_API_KEY", "test-key")

    yahoo_result = DeepHistoryResult(
        rows=[
            {"date": "1985-04-08T00:00:00+00:00", "time": 481_766_400, "close": 21.0},
        ],
        source="yahoo_chart",
        metadata={},
    )

    with patch(
        "showme.chart_history.fetch_yahoo_history",
        new=AsyncMock(return_value=yahoo_result),
    ), patch(
        "showme.chart_history.fetch_stooq_history",
        new=AsyncMock(side_effect=RuntimeError("stooq 503")),
    ):
        out = asyncio.run(
            fetch_longest_history(
                symbol="AAPL", asset_class="EQUITY",
                interval="1d", days=365 * 50, bars=1500,
            )
        )

    assert out.source == "yahoo_chart"
    considered_names = {entry["name"] for entry in out.metadata["sources_considered"]}
    assert "binance" not in considered_names  # crypto-only provider must be skipped
    error_entries = [
        entry for entry in out.metadata["sources_considered"] if not entry["ok"]
    ]
    assert {entry["name"] for entry in error_entries} == {"stooq"}
    assert any("stooq" in w for w in out.warnings)


def test_fetch_longest_history_raises_when_all_providers_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STOOQ_API_KEY", "test-key")
    with patch(
        "showme.chart_history.fetch_yahoo_history",
        new=AsyncMock(side_effect=RuntimeError("yahoo down")),
    ), patch(
        "showme.chart_history.fetch_stooq_history",
        new=AsyncMock(side_effect=RuntimeError("stooq down")),
    ):
        # EQUITY symbol → Binance is skipped, so only yahoo + stooq are raced.
        with pytest.raises(RuntimeError) as info:
            asyncio.run(
                fetch_longest_history(
                    symbol="ZZZ", asset_class="EQUITY",
                    interval="1d", days=365, bars=300,
                )
            )

    msg = str(info.value)
    assert "yahoo" in msg and "stooq" in msg
    assert "binance" not in msg


def test_fetch_longest_history_skips_binance_for_non_crypto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: Binance must not be raced for EQUITY/ETF/FX/etc.
    Racing it produced ~50k wasted 400 calls during a full MIS scan because
    Binance returns 400 for every (symbol, timeframe) pair when the symbol
    isn't a crypto perpetual.
    """
    monkeypatch.setenv("STOOQ_API_KEY", "test-key")
    yahoo_result = DeepHistoryResult(
        rows=[{"date": "2020-01-01T00:00:00+00:00", "time": 1_577_836_800, "close": 1.0}],
        source="yahoo_chart",
        metadata={},
    )

    binance_mock = AsyncMock(return_value=yahoo_result)
    with patch(
        "showme.chart_history.fetch_yahoo_history",
        new=AsyncMock(return_value=yahoo_result),
    ), patch(
        "showme.chart_history.fetch_binance_history",
        new=binance_mock,
    ), patch(
        "showme.chart_history.fetch_stooq_history",
        new=AsyncMock(side_effect=RuntimeError("stooq down")),
    ):
        for asset in ("EQUITY", "ETF", "FX", "COMMODITY", "BOND"):
            asyncio.run(
                fetch_longest_history(
                    symbol="AAPL", asset_class=asset,
                    interval="1d", days=365, bars=300,
                )
            )
    assert binance_mock.call_count == 0, "Binance must be skipped for non-CRYPTO"


def test_fetch_longest_history_trims_winner_to_user_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``parse_history_bars`` clamps the user's request to ``[10, 20_000]``;
    when the deepest provider has more rows than that ceiling, the winner
    is trimmed to the most-recent ``bars`` and depth is reported in metadata.
    """
    monkeypatch.setenv("STOOQ_API_KEY", "test-key")

    deep_rows = [
        {
            "date": f"{1990 + (i // 12)}-{(i % 12) + 1:02d}-01T00:00:00+00:00",
            "time": 631_152_000 + i * 2_592_000,
            "close": float(i),
        }
        for i in range(25)
    ]
    deep = DeepHistoryResult(rows=deep_rows, source="stooq", metadata={})
    shallow = DeepHistoryResult(
        rows=deep_rows[-1:], source="yahoo_chart", metadata={}
    )

    with patch(
        "showme.chart_history.fetch_yahoo_history",
        new=AsyncMock(return_value=shallow),
    ), patch(
        "showme.chart_history.fetch_binance_history",
        new=AsyncMock(side_effect=RuntimeError("not crypto")),
    ), patch(
        "showme.chart_history.fetch_stooq_history",
        new=AsyncMock(return_value=deep),
    ):
        # bars=3 is clamped up to 10 by parse_history_bars; with 25 deep
        # rows the result must be trimmed to the most recent 10.
        out = asyncio.run(
            fetch_longest_history(
                symbol="AAPL", asset_class="EQUITY",
                interval="1d", days=365 * 50, bars=3,
            )
        )

    assert out.source == "stooq"
    assert len(out.rows) == 10
    # Trimmed rows are the most recent — depth is preserved in metadata.
    assert out.rows[-1]["time"] == deep_rows[-1]["time"]
    assert out.rows[0]["time"] == deep_rows[-10]["time"]
    assert out.metadata["bars_available"] == 25
    assert out.metadata["bars_returned"] == 10


def test_fetch_longest_history_skips_stooq_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When STOOQ_API_KEY is absent the orchestrator must not query Stooq —
    it only attempts Yahoo + Binance and the metadata reflects that.
    """
    monkeypatch.delenv("STOOQ_API_KEY", raising=False)

    yahoo_result = DeepHistoryResult(
        rows=[
            {"date": "1986-09-04T13:30:00+00:00", "time": 526_138_200, "close": 0.5},
        ],
        source="yahoo_chart",
        metadata={},
    )
    stooq_mock = AsyncMock(side_effect=AssertionError("stooq must not be called"))
    binance_mock = AsyncMock(side_effect=AssertionError("binance must not be called"))

    with patch(
        "showme.chart_history.fetch_yahoo_history",
        new=AsyncMock(return_value=yahoo_result),
    ), patch(
        "showme.chart_history.fetch_binance_history",
        new=binance_mock,
    ), patch(
        "showme.chart_history.fetch_stooq_history",
        new=stooq_mock,
    ):
        out = asyncio.run(
            fetch_longest_history(
                symbol="AAPL", asset_class="EQUITY",
                interval="1d", days=365 * 50, bars=1000,
            )
        )

    assert out.source == "yahoo_chart"
    considered_names = {entry["name"] for entry in out.metadata["sources_considered"]}
    assert considered_names == {"yahoo"}  # binance gated to CRYPTO, stooq gated to api_key
    stooq_mock.assert_not_awaited()
    binance_mock.assert_not_awaited()


def test_longest_history_rows_to_dataframe_matches_yfinance_shape() -> None:
    """Downstream functions expect a DataFrame with a DatetimeIndex and
    lowercase OHLCV columns + dividends + splits placeholders. The
    converter must produce exactly that shape so we can swap it in for
    ``YFinanceAdapter._fetch_ohlcv`` transparently.
    """
    import pandas as pd

    df = longest_history_rows_to_dataframe([
        {"date": "2024-01-02T00:00:00+00:00", "time": 1_704_153_600, "open": 1.0, "high": 1.5, "low": 0.5, "close": 1.2, "volume": 100},
        {"date": "2024-01-03T00:00:00+00:00", "time": 1_704_240_000, "open": 1.2, "high": 1.8, "low": 1.1, "close": 1.6, "volume": 200},
    ])

    assert isinstance(df.index, pd.DatetimeIndex)
    assert set(("open", "high", "low", "close", "volume", "dividends", "splits")).issubset(df.columns)
    assert df.iloc[0]["close"] == 1.2
    assert df.iloc[-1]["close"] == 1.6


def test_longest_history_rows_to_dataframe_handles_empty_rows() -> None:
    df = longest_history_rows_to_dataframe([])
    assert df.empty
    assert set(("open", "high", "low", "close", "volume")).issubset(df.columns)


def test_days_from_request_uses_start_then_extra_then_period() -> None:
    """The wrapper must reconstruct ``days`` from whatever the upstream
    DataRequest gave it: an explicit start date, an extra dict, a period
    string. None of them present → conservative default of 365.
    """
    from datetime import datetime, timedelta, timezone

    class FakeReq:
        def __init__(self, start=None, end=None, extra=None):
            self.start = start
            self.end = end
            self.extra = extra or {}

    now = datetime.now(timezone.utc)
    # Start/end provided → derive from delta.
    assert _days_from_request(FakeReq(start=now - timedelta(days=730), end=now)) in {730, 729, 731}
    # Only extra.days provided.
    assert _days_from_request(FakeReq(extra={"days": 90})) == 90
    # Only extra.period (e.g. "2y", "6mo", "30d").
    assert _days_from_request(FakeReq(extra={"period": "2y"})) == 730
    assert _days_from_request(FakeReq(extra={"period": "6mo"})) == 180
    assert _days_from_request(FakeReq(extra={"period": "30d"})) == 30
    # Nothing useful → 365.
    assert _days_from_request(FakeReq()) == 365


def test_ohlcv_wrapper_intercepts_only_ohlcv_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrapper must route ONLY ``DataKind.OHLCV`` requests through
    ``fetch_longest_history``. Other kinds (REFDATA, QUOTE, NEWS) MUST
    delegate to the inner adapter so quote/fundamentals/analyst paths
    keep working.
    """
    from showme.engine.core.base_data_source import DataKind

    monkeypatch.setenv("STOOQ_API_KEY", "k")

    class _AC:
        value = "EQUITY"

    class FakeInst:
        def __init__(self):
            self.symbol = "AAPL"
            self.asset_class = _AC()

    class FakeReq:
        def __init__(self, kind):
            self.kind = kind
            self.instrument = FakeInst()
            self.interval = "1d"
            self.start = None
            self.end = None
            self.limit = 500
            self.extra = {"days": 365}

    inner_called: dict[str, Any] = {"refdata": 0, "ohlcv": 0}

    class FakeInner:
        name = "yfinance"
        async def fetch(self, req):
            if req.kind == DataKind.OHLCV:
                inner_called["ohlcv"] += 1
            else:
                inner_called["refdata"] += 1
            return "inner-result"

    wrapper = OhlcvLongestHistoryWrapper(FakeInner())

    # Non-OHLCV passes through.
    out_refdata = asyncio.run(wrapper.fetch(FakeReq(DataKind.REFDATA)))
    assert out_refdata == "inner-result"
    assert inner_called["refdata"] == 1
    assert inner_called["ohlcv"] == 0

    # OHLCV gets intercepted → fetch_longest_history is invoked. Patch it
    # to return a known result so we can assert the DataFrame conversion.
    sample = DeepHistoryResult(
        rows=[
            {"date": "1980-12-12T14:30:00+00:00", "time": 345_479_400, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
        ],
        source="yahoo_chart",
        metadata={},
    )
    with patch(
        "showme.chart_history.fetch_longest_history",
        new=AsyncMock(return_value=sample),
    ):
        df = asyncio.run(wrapper.fetch(FakeReq(DataKind.OHLCV)))

    # The wrapper must not have delegated to the inner adapter for OHLCV.
    assert inner_called["ohlcv"] == 0
    # And it must return a DataFrame, not the inner sentinel.
    assert df is not None and hasattr(df, "iloc")
    assert df.iloc[0]["close"] == 1.5


def test_ohlcv_wrapper_falls_back_to_inner_on_longest_history_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``fetch_longest_history`` raises (e.g. a network blip during
    boot), the wrapper MUST silently fall back to the wrapped adapter
    so existing behavior is preserved.
    """
    from showme.engine.core.base_data_source import DataKind

    monkeypatch.setenv("STOOQ_API_KEY", "k")

    class _AC:
        value = "EQUITY"

    class FakeInst:
        def __init__(self):
            self.symbol = "AAPL"
            self.asset_class = _AC()

    class FakeReq:
        kind = DataKind.OHLCV
        instrument = FakeInst()
        interval = "1d"
        start = None
        end = None
        limit = 200
        extra: dict[str, Any] = {"days": 90}

    inner_calls = []

    class FakeInner:
        name = "yfinance"
        async def fetch(self, req):
            inner_calls.append(req)
            return "inner-fallback"

    wrapper = OhlcvLongestHistoryWrapper(FakeInner())

    with patch(
        "showme.chart_history.fetch_longest_history",
        new=AsyncMock(side_effect=RuntimeError("network down")),
    ):
        out = asyncio.run(wrapper.fetch(FakeReq()))

    assert out == "inner-fallback"
    assert len(inner_calls) == 1


def test_ohlcv_wrapper_passes_attribute_access_through() -> None:
    """Callers that read ``adapter.name`` or ``adapter.supported_kinds``
    must still see the inner adapter's attributes — the wrapper isn't
    supposed to lose adapter identity.
    """

    class FakeInner:
        name = "yfinance"
        rate_limit_rps = 1.0
        supported_kinds = ("OHLCV",)
        custom_thing = object()

    wrapper = OhlcvLongestHistoryWrapper(FakeInner())
    inner = FakeInner()
    assert wrapper.name == "yfinance"
    assert wrapper.rate_limit_rps == 1.0
    assert wrapper.supported_kinds == ("OHLCV",)
    assert wrapper.custom_thing is FakeInner.custom_thing
    # And the wrapper must not steal attributes the inner has under the
    # same name as a wrapper method — wrappers can shadow ``fetch`` only.
    assert wrapper.name == inner.name
