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


# ─────────────────────────────────────────────────────────────────────────
# EREV#2 — missing coverage and a single period must not read as a real zero
# EREV#1/#3 — methodology is recommendation buckets, not EPS estimates
# ─────────────────────────────────────────────────────────────────────────


class _FinnhubFake:
    def __init__(self, recs: list[dict[str, Any]]):
        self.recs = recs

    async def recommendations(self, symbol: str) -> list[dict[str, Any]]:
        return self.recs


def _bucket(period: str, sb=0, b=0, h=0, s=0, ss=0) -> dict[str, Any]:
    return {"period": period, "strongBuy": sb, "buy": b, "hold": h, "sell": s, "strongSell": ss}


def _erev(recs):
    from showme.engine.functions.equity.erev import EREVFunction

    aapl = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(
        EREVFunction(FunctionDeps(finnhub=_FinnhubFake(recs))).execute(instrument=aapl)
    )


def test_erev_single_period_velocity_is_null_not_zero() -> None:
    res = _erev([_bucket("2026-09-01", sb=5, b=3, h=2)])
    assert res.data["status"] == "ok"
    assert res.data["velocity_avg"] is None
    assert res.data["revisions"] == []


def test_erev_zero_analyst_period_has_null_average() -> None:
    res = _erev([
        _bucket("2026-08-01", sb=4, b=2, h=1, s=0, ss=0),
        _bucket("2026-09-01"),  # no analysts this month
    ])
    latest = res.data["trend"][-1]
    assert latest["n"] == 0
    assert latest["avg"] is None, "zero coverage must not be a neutral 0.0 consensus"
    assert res.data["velocity_avg"] is None
    assert res.data["revisions"][0]["delta_avg"] is None


def test_erev_all_zero_feed_is_empty_not_ok() -> None:
    res = _erev([_bucket("2026-08-01"), _bucket("2026-09-01")])
    assert res.data["status"] == "empty"
    assert res.data["velocity_avg"] is None
    assert res.data["current_score"]["avg"] is None


def test_erev_methodology_describes_recommendations_not_eps() -> None:
    res = _erev([_bucket("2026-08-01", sb=1), _bucket("2026-09-01", sb=2)])
    text = res.data["methodology"]
    assert "recommendation" in text.lower()
    # The disclaimer may name EPS, but the methodology must not claim EPS data.
    assert "eps estimate" not in text.lower()
    assert "eps revision" not in text.lower()
    from showme.engine.functions.equity import erev as erev_mod

    doc = erev_mod.__doc__ or ""
    for claim in ("EPS/revenue revisions", "EPS estimate trend", "EPS estimate revisions"):
        assert claim not in doc
        assert claim not in erev_mod.EREVFunction.description
