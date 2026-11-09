"""ASOF-3: quote and yield as_of must be the provider observation time, not retrieval time.

``normalized_snapshot`` stamps ``fetched_at`` with the request clock. The Yahoo
chart provider reports its own observation time as ``regularMarketTime``; that
time must reach the snapshot as ``as_of`` and drive the yield index date. On a
Sunday, a Friday close must come back dated Friday with cadence ``last_close``,
never dated Sunday as ``intraday``.

Network is patched: ``requests.get`` and ``fetch_quote_snapshot`` are fakes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from showme import quotes
from showme.engine.functions.screen import _funcs as screen_funcs
from showme.engine.functions.screen._funcs import SRCHFunction
from tests.test_map_prior_session_change import _CLOSES, _MARKET_TIME_11_06, _TS, _chart_payload, _patch_chart


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def test_chart_snapshot_as_of_is_the_provider_observation_time(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_chart(monkeypatch, _chart_payload())
    snap = quotes._fetch_yahoo_chart_quote("SPY")
    # The last price is stamped with the provider's regularMarketTime, not the request clock.
    assert snap["as_of"] == _iso(_MARKET_TIME_11_06)
    assert snap["as_of"] != snap["fetched_at"]
    assert snap["raw"]["regular_market_time"] == _MARKET_TIME_11_06


def test_chart_snapshot_without_provider_time_has_no_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    # No regularMarketTime published: the observation time is unknown, so as_of stays empty.
    _patch_chart(monkeypatch, _chart_payload(market_time=None))
    snap = quotes._fetch_yahoo_chart_quote("SPY")
    assert snap.get("as_of") is None


def test_yield_index_on_sunday_is_dated_by_the_friday_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    # Retrieved Sunday 2026-11-08 12:00 UTC, the last price is Friday 2026-11-06's close.
    async def quote(ticker: str) -> dict[str, Any]:
        return {
            "last": 3.96,
            "source": "yahoo_chart",
            "as_of": "2026-11-06T21:00:00+00:00",
            "fetched_at": "2026-11-08T12:00:00+00:00",
        }

    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", quote)
    values = asyncio.run(screen_funcs._yahoo_yield_values({"US3M": "^IRX"}))
    entry = values["US3M"]
    assert entry["as_of"] == "2026-11-06"
    assert entry["cadence"] == "last_close"


def test_yield_index_during_session_is_intraday(monkeypatch: pytest.MonkeyPatch) -> None:
    async def quote(ticker: str) -> dict[str, Any]:
        return {
            "last": 3.96,
            "source": "yahoo_chart",
            "as_of": "2026-11-09T15:00:00+00:00",
            "fetched_at": "2026-11-09T15:00:30+00:00",
        }

    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", quote)
    values = asyncio.run(screen_funcs._yahoo_yield_values({"US3M": "^IRX"}))
    assert values["US3M"]["as_of"] == "2026-11-09"
    assert values["US3M"]["cadence"] == "intraday"


def test_yield_index_without_observation_time_has_no_date_or_intraday_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only a retrieval time is known: no observation date and no intraday claim.
    async def quote(ticker: str) -> dict[str, Any]:
        return {"last": 3.96, "source": "stooq", "fetched_at": "2026-11-08T12:00:00+00:00"}

    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", quote)
    values = asyncio.run(screen_funcs._yahoo_yield_values({"US3M": "^IRX"}))
    assert "as_of" not in values["US3M"]
    assert values["US3M"]["cadence"] == "unknown"


def test_srch_row_reports_the_observation_date_not_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_srch_live_bonds import _fred_fake

    monkeypatch.setattr(screen_funcs, "fetch_fred_csv_series", _fred_fake({"DGS10": 4.97}))

    async def quote(ticker: str) -> dict[str, Any]:
        return {
            "last": 3.96,
            "source": "yahoo_chart",
            "as_of": "2026-11-06T21:00:00+00:00",
            "fetched_at": "2026-11-08T12:00:00+00:00",
        }

    monkeypatch.setattr(screen_funcs, "fetch_quote_snapshot", quote)
    result = asyncio.run(SRCHFunction().execute(query="yield >= 0", limit=50))
    rows = {row["symbol"]: row for row in result.data["rows"]}
    assert rows["US3M"]["yield_as_of"] == "2026-11-06"
    assert rows["US3M"]["yield_cadence"] == "last_close"
