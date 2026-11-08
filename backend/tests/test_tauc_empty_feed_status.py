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
