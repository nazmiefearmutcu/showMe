"""TAUC#1 follow-up: a live TreasuryDirect feed with zero usable rows must not read as ok.

When the live adapter answers but yields no rows inside the window (for example
because no row carries a usable auction day), the function must say the feed
was empty and give a reason. It must not return a bare ``ok`` envelope with
zero rows, which reads as "the calendar is empty".

No network: the adapter is a fake that serves fixed answers.
"""
from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.bond.tauc import TAUCFunction


class _EmptyLiveFeed:
    """Live-shaped adapter whose feed yields zero rows for every window."""

    def __init__(self) -> None:
        self.calls = 0

    async def upcoming(self, *, horizon_days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        self.calls += 1
        return []

    async def recent(self, *, days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        self.calls += 1
        return []


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_live_upcoming_with_zero_rows_is_an_explicit_empty_state() -> None:
    adapter = _EmptyLiveFeed()
    result = _run(TAUCFunction(FunctionDeps(treasury_auctions=adapter)).execute(action="upcoming"))

    assert adapter.calls == 1
    assert result.sources == ["treasurydirect"]
    assert result.data["rows"] == []
    assert result.data["summary"]["source_mode"] == "treasurydirect"
    assert result.data.get("status") == "empty", result.data
    reason = str(result.data.get("reason") or "")
    assert "treasurydirect" in reason.lower(), reason
    assert "30-day" in reason, reason


def test_live_recent_with_zero_rows_is_an_explicit_empty_state() -> None:
    adapter = _EmptyLiveFeed()
    result = _run(TAUCFunction(FunctionDeps(treasury_auctions=adapter)).execute(action="recent", horizon_days=14))

    assert result.data.get("status") == "empty", result.data
    assert "14-day" in str(result.data.get("reason") or ""), result.data.get("reason")
    assert result.data["summary"]["source_mode"] == "treasurydirect"


def test_live_with_rows_has_no_empty_status() -> None:
    class _OneRow(_EmptyLiveFeed):
        async def upcoming(self, *, horizon_days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
            self.calls += 1
            return [{"security_type": "Bill", "term": "13-Week", "auction_date": "2026-11-09", "offering_amount": "70000000000"}]

    result = _run(TAUCFunction(FunctionDeps(treasury_auctions=_OneRow())).execute(action="upcoming"))
    assert result.data["summary"]["auctions"] == 1
    assert result.data.get("status") != "empty"


# ---- TAUC#1 follow-up: the reason must match what happened -----------------


class _NoteOnlyFeed:
    """Live feed with one in-window Note row; the requested filter is Bill."""

    async def upcoming(self, *, horizon_days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        return [{"security_type": "Note", "term": "10-Year", "auction_date": "2026-11-12", "offering_amount": 39e9}]

    async def recent(self, *, days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        return [{"security_type": "Note", "term": "10-Year", "auction_date": "2026-11-05", "offering_amount": 39e9}]


def test_filter_that_removes_all_rows_says_the_feed_had_rows() -> None:
    result = _run(
        TAUCFunction(FunctionDeps(treasury_auctions=_NoteOnlyFeed())).execute(
            action="upcoming", security_type="bill"
        )
    )
    assert result.data["status"] == "empty", result.data
    assert result.data["rows"] == []
    reason = str(result.data.get("reason") or "")
    # The feed answered with one row; the filter removed it. The reason must not
    # claim that TreasuryDirect returned no rows at all.
    assert "returned no" not in reason.lower(), reason
    assert "1" in reason and "upcoming" in reason, reason
    assert "bill" in reason.lower(), reason
    assert result.data["summary"]["source_mode"] == "treasurydirect"


def test_feed_with_no_rows_in_window_still_says_so() -> None:
    result = _run(TAUCFunction(FunctionDeps(treasury_auctions=_EmptyLiveFeed())).execute(action="upcoming"))
    assert "returned no upcoming auction rows" in str(result.data.get("reason") or "")


# ---- DATA POLICY: no invented auction rows on unavailable paths ------------


def test_no_adapter_returns_no_invented_rows() -> None:
    result = _run(TAUCFunction(FunctionDeps()).execute(action="upcoming"))
    assert result.data["rows"] == [], result.data
    assert result.data["status"] == "provider_unavailable", result.data
    assert result.data.get("reason"), result.data
    assert result.data.get("next_actions"), result.data
    assert "treasury_auction_model" not in result.sources
    assert "treasury_auction_fallback" not in result.sources


class _BoomFeed:
    async def upcoming(self, *, horizon_days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        raise RuntimeError("treasurydirect timeout")

    async def recent(self, *, days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        raise RuntimeError("treasurydirect timeout")


def test_live_error_returns_no_invented_rows() -> None:
    result = _run(TAUCFunction(FunctionDeps(treasury_auctions=_BoomFeed())).execute(action="recent"))
    assert result.data["rows"] == [], result.data
    assert result.data["status"] == "provider_unavailable", result.data
    assert "timeout" in str(result.data.get("reason") or "").lower(), result.data
    assert result.warnings, result.warnings
    assert result.metadata.get("live") is False


def test_explicit_reference_still_serves_the_labelled_model() -> None:
    result = _run(TAUCFunction(FunctionDeps(treasury_auctions=_EmptyLiveFeed())).execute(reference=True))
    assert result.sources == ["treasury_auction_model"]
    assert result.data["summary"]["source_mode"] == "treasury_auction_model"
    assert result.data["rows"], "explicit opt-in keeps the labelled model rows"
