"""P2A-G12 findings: TAUC / EREV / DDM / PCAS honesty and contract fixes.

All tests are offline: every provider is an injected fake.
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument


# ─────────────────────────────────────────────────────────────────────────
# TAUC#3 — security_type filter must run before the row limit
# ─────────────────────────────────────────────────────────────────────────


class _AuctionsFake:
    """Mimics the adapter: honours ``limit`` by truncating the raw list."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.limits_seen: list[Any] = []

    async def upcoming(self, *, horizon_days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        self.limits_seen.append(limit)
        return self.rows if limit is None else self.rows[:limit]

    async def recent(self, *, days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        self.limits_seen.append(limit)
        return self.rows if limit is None else self.rows[:limit]


_MIXED_ROWS = [
    {"security_type": "Bill", "term": "13-Week", "auction_date": "2026-11-10", "offering_amount": 70e9},
    {"security_type": "Bill", "term": "26-Week", "auction_date": "2026-11-10", "offering_amount": 75e9},
    {"security_type": "Note", "term": "2-Year", "auction_date": "2026-11-12", "offering_amount": 69e9},
    {"security_type": "Note", "term": "5-Year", "auction_date": "2026-11-13", "offering_amount": 70e9},
    {"security_type": "Bond", "term": "30-Year", "auction_date": "2026-11-15", "offering_amount": 25e9},
]


def test_tauc_security_filter_applied_before_limit() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    adapter = _AuctionsFake(_MIXED_ROWS)
    result = asyncio.run(
        TAUCFunction(FunctionDeps(treasury_auctions=adapter)).execute(
            security_type="Note", limit=2
        )
    )
    types = [row["security_type"] for row in result.data["rows"]]
    # Two Notes exist in the window, so a limit of 2 must return both.
    assert types == ["Note", "Note"]
    assert result.data["n"] == 2


def test_tauc_template_security_filter_applied_before_limit() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    result = asyncio.run(
        TAUCFunction(FunctionDeps()).execute(live_auctions=False, security_type="Bond", limit=1)
    )
    assert [row["security_type"] for row in result.data["rows"]] == ["Bond"]


# ─────────────────────────────────────────────────────────────────────────
# TAUC#4 — manifest default for live_auctions must match the handler
# ─────────────────────────────────────────────────────────────────────────


def _manifest(code: str):
    from showme.manifest.registry import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    return REGISTRY.get(code)


def test_tauc_manifest_default_live_matches_handler() -> None:
    from showme.engine.functions.bond.tauc import TAUCFunction

    adapter = _AuctionsFake(_MIXED_ROWS)
    # No live flag supplied: the handler goes live (it is the keyless default).
    result = asyncio.run(TAUCFunction(FunctionDeps(treasury_auctions=adapter)).execute())
    assert result.sources == ["treasurydirect"]

    tauc = _manifest("TAUC")
    assert tauc.defaults["live_auctions"] is True, (
        "manifest says live_auctions defaults to False but the handler goes live when it is absent"
    )
    assert "opt-in" not in tauc.methodology.lower()
