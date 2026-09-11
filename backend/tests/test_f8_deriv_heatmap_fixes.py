"""F8 fix-lane regression pins (derivatives + heatmap).

Covers the SHOWME FUNCTION AUDIT 2026-09-11 lane F8 fixes:

* GREEKS empty-book envelope ships ``positions`` as a LIST (the scalar
  ``positions: 0`` wire shape crashed the pane on ``[...0]``).
* The SECT / MAP manifest seeds describe the shipped handlers (sector /
  country ETF heatmaps) instead of the phantom market-cap treemap and
  sector-rotation-metric contracts they had drifted to.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.manifest import REGISTRY, load_seeds


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    load_seeds()


class _Deps:
    yfinance = None
    sec_edgar = None
    sec_13f = None


def test_greeks_empty_book_always_ships_a_positions_list() -> None:
    """The empty-book envelope must never ship a scalar ``positions``."""
    from showme.engine.functions.portfolio.greeks import GREEKSFunction

    fn = GREEKSFunction(_Deps())
    res = asyncio.run(fn.execute(positions=[]))
    assert res.data["status"] == "input_required"
    assert isinstance(res.data["positions"], list)
    assert res.data["positions"] == []
    assert res.data["n"] == 0


def test_sect_seed_matches_shipped_sector_heatmap_contract() -> None:
    entry = REGISTRY.get("SECT")
    assert entry.name == "Sector Heatmap"
    input_names = {i.name for i in entry.inputs}
    assert {"period", "live"} <= input_names
    column_keys = {c.key for c in entry.table_schema.columns}
    assert {"sector", "etf", "last", "change_pct", "change_pct_period", "quote_type"} <= column_keys
    test_names = {t.name for t in entry.semantic_tests}
    assert "sect_live_period_mismatch_is_disclosed" in test_names
    assert "sect_missing_change_is_null_not_zero" in test_names


def test_map_seed_matches_shipped_country_heatmap_contract() -> None:
    entry = REGISTRY.get("MAP")
    assert entry.name == "World Market Heatmap"
    input_names = {i.name for i in entry.inputs}
    assert "live" in input_names
    column_keys = {c.key for c in entry.table_schema.columns}
    assert {"country", "etf", "last", "change_pct", "quote_type"} <= column_keys
    # The phantom market-cap sizing contract must not come back.
    assert "size_metric" not in input_names
    assert "size_value" not in column_keys
