"""POLY — liquidity is a per-market quantity, counted once.

The backend repeats each market's liquidity on every outcome row (the
manifest table_schema is one row per outcome). The payload-level totals must
therefore be computed once per market, and the top-level payload must carry
them so the pane never has to re-sum the outcome rows (which double-counts
every binary market).
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc.poly import POLYFunction


def _gamma_binary_markets():
    return [
        {
            "slug": "fed-cut-sept",
            "question": "Will the Fed cut rates in September?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.72", "0.28"]',
            "liquidity": "250000",
            "volume": "900000",
            "endDate": "2099-09-16T00:00:00Z",
            "active": True,
            "closed": False,
        },
        {
            "slug": "btc-150k-2026",
            "question": "Bitcoin above $150k in 2026?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.31", "0.69"]',
            "liquidity": "90000",
            "volume": "50000",
            "endDate": "2099-12-31T00:00:00Z",
            "active": True,
            "closed": False,
        },
    ]


def test_top_level_liquidity_total_counts_each_market_once(monkeypatch):
    import showme.engine.functions.misc.poly as poly_mod

    async def _fake_fetch(*_args, **_kwargs):
        return _gamma_binary_markets()

    monkeypatch.setattr(poly_mod, "_fetch_gamma_markets", _fake_fetch)

    result = asyncio.run(
        POLYFunction(FunctionDeps()).execute(status="open", min_liquidity_usd=10_000, limit=25)
    )
    data = result.data

    # Two binary markets: 250k + 90k once each, not per outcome row.
    assert data["total_liquidity_usd"] == 340000.0
    assert data["market_count"] == 2
    card_total = next(c for c in data["cards"] if c["key"] == "total_liquidity_usd")
    assert card_total["value"] == data["total_liquidity_usd"]
    # Outcome rows still carry the market-level liquidity (table schema).
    assert len(data["rows"]) == 4
