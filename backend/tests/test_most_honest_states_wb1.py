"""wb1-g17 — MOST must not overstate freshness, crypto basis, FX volume or thin movers.

* MOST#3 — rows quoted while the session is closed are ``last_close`` (never
  ``live``) and the payload ``as_of`` is the provider quote time, not the request time.
* MOST#4 — crypto ``prev_close`` is not the 24h open; the abs-change board
  ranks liquid movers ahead of thin ones.
* MOST#5 — spot FX rows report null volume and null dollar volume, not zero.

Network is never touched: Binance and the quote service are patched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import showme.engine.functions.screen._funcs as funcs
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen._funcs import (
    MOSTFunction,
    _most_active_crypto_row_from_ticker,
    _rank_most_active_rows,
)

SUNDAY_UTC = datetime(2026, 11, 8, 0, 30, tzinfo=timezone.utc)  # Saturday 19:30 ET
MONDAY_OPEN_UTC = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)  # Monday 10:00 ET
FRIDAY_CLOSE_UTC = datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc)  # Friday 16:00 ET


class _YFinanceLikeProvider:
    name = "yfinance"


def _snapshot(regular_market_time: float | None) -> dict[str, Any]:
    return {
        "symbol": "AAA",
        "last": 186.64,
        "price": 186.64,
        "previous_close": 185.0,
        "change_pct": 0.9,
        "volume": 1_000_000.0,
        "source": "yahoo_chart",
        "raw": {"regular_market_time": regular_market_time},
    }


def _patch_clock_and_quotes(monkeypatch, now: datetime, quote_epoch: float | None) -> None:
    from showme import quotes

    quotes.quote_cache_clear()
    monkeypatch.setattr(funcs, "_most_utc_now", lambda: now)

    async def _fake_fetch(symbol: str) -> dict[str, Any]:
        return _snapshot(quote_epoch)

    monkeypatch.setattr(quotes, "fetch_quote_snapshot", _fake_fetch)


async def test_closed_session_quotes_are_last_close_not_live(monkeypatch) -> None:
    _patch_clock_and_quotes(monkeypatch, SUNDAY_UTC, FRIDAY_CLOSE_UTC.timestamp())
    fn = MOSTFunction(deps=FunctionDeps(yfinance=_YFinanceLikeProvider()))
    result = await fn.execute(asset_class="equities", live_screen=True, limit=10)
    rows = result.data["rows"]
    assert rows
    live_rows = [row for row in rows if row["quote_state"] != "unavailable"]
    assert live_rows, "the closed-session fixture must resolve rows"
    assert all(row["quote_state"] == "last_close" for row in live_rows), (
        "a Saturday quote is the last close; labelling it live is the defect"
    )
    assert result.data["market_session"]["equity"] == "closed"


async def test_payload_as_of_is_provider_quote_time_not_request_time(monkeypatch) -> None:
    _patch_clock_and_quotes(monkeypatch, SUNDAY_UTC, FRIDAY_CLOSE_UTC.timestamp())
    fn = MOSTFunction(deps=FunctionDeps(yfinance=_YFinanceLikeProvider()))
    result = await fn.execute(asset_class="equities", live_screen=True, limit=10)
    assert result.data["as_of"] == FRIDAY_CLOSE_UTC.isoformat()
    assert result.data["requested_at"] == SUNDAY_UTC.isoformat()
    assert result.data["as_of"] != result.data["requested_at"]


async def test_open_session_fresh_quote_stays_live(monkeypatch) -> None:
    quote_epoch = MONDAY_OPEN_UTC.timestamp() - 60
    _patch_clock_and_quotes(monkeypatch, MONDAY_OPEN_UTC, quote_epoch)
    fn = MOSTFunction(deps=FunctionDeps(yfinance=_YFinanceLikeProvider()))
    result = await fn.execute(asset_class="equities", live_screen=True, limit=10)
    live_rows = [row for row in result.data["rows"] if row["quote_state"] != "unavailable"]
    assert live_rows and all(row["quote_state"] == "live" for row in live_rows)
    assert result.data["market_session"]["equity"] == "open"


async def test_open_session_quote_older_than_window_is_stale(monkeypatch) -> None:
    quote_epoch = MONDAY_OPEN_UTC.timestamp() - 3 * 3600
    _patch_clock_and_quotes(monkeypatch, MONDAY_OPEN_UTC, quote_epoch)
    fn = MOSTFunction(deps=FunctionDeps(yfinance=_YFinanceLikeProvider()))
    result = await fn.execute(asset_class="equities", live_screen=True, limit=10)
    live_rows = [row for row in result.data["rows"] if row["quote_state"] != "unavailable"]
    assert live_rows and all(row["quote_state"] == "stale" for row in live_rows)


async def test_reference_payload_never_claims_request_time_as_as_of() -> None:
    result = await MOSTFunction(deps=FunctionDeps()).execute(reference=True, asset_class="equities")
    assert result.data["status"] == "reference"
    assert result.data["as_of"] is None


async def test_fx_reference_rows_report_null_volume_not_zero() -> None:
    result = await MOSTFunction(deps=FunctionDeps()).execute(reference=True, asset_class="fx")
    rows = result.data["rows"]
    assert rows
    for row in rows:
        assert row["volume"] is None, f"{row['symbol']} volume must be unreported, not 0"
        assert row["dollar_volume"] is None, f"{row['symbol']} dollar_volume must be null"


def test_crypto_row_prev_close_is_not_the_24h_open() -> None:
    row = _most_active_crypto_row_from_ticker({
        "symbol": "NFPUSDT",
        "lastPrice": "0.00181",
        "openPrice": "0.0053",
        "volume": "1000000",
        "quoteVolume": "3834192",
        "priceChangePercent": "-65.849",
        "highPrice": "0.0054",
        "lowPrice": "0.0017",
        "closeTime": 1_762_560_000_000,
    })
    assert row is not None
    assert row["prev_close"] is None, "the 24h open must not be published as previous close"
    assert row["open_24h"] == pytest.approx(0.0053)
    assert row["change_basis"] == "24h_open"
    assert row["change_pct"] == pytest.approx(-65.849)
    assert row["quote_time"] is not None


def test_abs_change_board_ranks_liquid_movers_before_thin_ones() -> None:
    rows = [
        {"symbol": "THIN", "asset_class": "crypto", "last": 0.0018, "volume": 1.0,
         "dollar_volume": 3_834_192.0, "change_pct": -65.8, "quote_state": "live"},
        {"symbol": "LIQ", "asset_class": "crypto", "last": 1.0, "volume": 1.0,
         "dollar_volume": 45_000_000.0, "change_pct": 4.0, "quote_state": "live"},
        {"symbol": "EURUSD=X", "asset_class": "fx", "last": 1.08, "volume": 0,
         "change_pct": 0.5, "quote_state": "live"},
    ]
    ranked = _rank_most_active_rows(rows, "abs_change")
    assert [row["symbol"] for row in ranked] == ["LIQ", "EURUSD=X", "THIN"]
    assert ranked[-1]["symbol"] == "THIN", "a sub-floor mover is demoted, not dropped"
    assert len(ranked) == 3


def test_abs_change_board_never_ranks_unavailable_rows_above_thin_movers() -> None:
    """Missing data is not liquidity: an all-null unavailable row sorts below a thin mover."""
    rows = [
        {"symbol": "THIN", "asset_class": "crypto", "last": 0.0018, "volume": 1.0,
         "dollar_volume": 3_834_192.0, "change_pct": 30.0, "quote_state": "live"},
        {"symbol": "LIQ", "asset_class": "crypto", "last": 1.0, "volume": 1.0,
         "dollar_volume": 45_000_000.0, "change_pct": 2.0, "quote_state": "live"},
        {"symbol": "UNAVAIL", "asset_class": "crypto", "last": None, "volume": None,
         "dollar_volume": None, "change_pct": None, "quote_state": "unavailable"},
        {"symbol": "FXP", "asset_class": "fx", "last": 1.08, "volume": None,
         "change_pct": 0.5, "quote_state": "live"},
    ]
    ranked = _rank_most_active_rows(rows, "abs_change")
    assert [row["symbol"] for row in ranked] == ["LIQ", "FXP", "THIN", "UNAVAIL"]


def test_abs_change_board_ranks_unknown_notional_below_known_thin_movers() -> None:
    rows = [
        {"symbol": "UNKNOWN", "asset_class": "crypto", "last": 2.0, "volume": None,
         "dollar_volume": None, "change_pct": 9.0, "quote_state": "live"},
        {"symbol": "THIN", "asset_class": "crypto", "last": 0.0018, "volume": 1.0,
         "dollar_volume": 3_834_192.0, "change_pct": -5.0, "quote_state": "live"},
    ]
    ranked = _rank_most_active_rows(rows, "abs_change")
    assert [row["symbol"] for row in ranked] == ["THIN", "UNKNOWN"]


def test_fx_rows_never_report_zero_dollar_volume_in_ranking() -> None:
    ranked = _rank_most_active_rows(
        [{"symbol": "USDJPY=X", "asset_class": "fx", "last": 153.0, "volume": 0,
          "change_pct": 0.2, "quote_state": "live"}],
        "dollar_volume",
    )
    assert ranked[0]["volume"] is None
    assert ranked[0]["dollar_volume"] is None
