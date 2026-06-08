"""P3 — MOST rows must be self-describing about their data origin.

Every MOST row should carry a row-level ``quote_state``:

* deterministic (non-live) reference rows ⇒ ``"reference"``;
* merged live rows ⇒ ``"live"`` (stamped by ``_merge_live_most_rows`` and
  preserved through ``_rank_most_active_rows``).

The reference contract is honest by construction (``MOSTFunction`` returns
an empty ``provider_unavailable`` payload on a live-provider miss and only
serves the reference universe when ``live=False``); these tests pin the
row-level annotation without touching that contract.
"""
from __future__ import annotations

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen._funcs import (
    MOSTFunction,
    _merge_live_most_rows,
    _most_active_reference_rows,
    _rank_most_active_rows,
)


async def test_reference_rows_carry_quote_state_reference():
    """live_screen=False ⇒ every served row is labelled "reference"."""
    fn = MOSTFunction(deps=FunctionDeps(yfinance=None))
    result = await fn.execute(live_screen=False, sort="volume")
    rows = result.data["rows"]
    assert rows, "reference path must serve the deterministic universe"
    assert result.data["status"] == "reference"
    assert result.data["live"] is False
    assert all(row.get("quote_state") == "reference" for row in rows)


async def test_rank_does_not_clobber_live_quote_state():
    """Live rows merged before ranking keep quote_state="live"."""
    reference = _most_active_reference_rows()[:3]
    quotes = [
        {"symbol": ref["symbol"], "last": ref["last"], "volume": ref["volume"]}
        for ref in reference
    ]
    live_rows = _merge_live_most_rows(reference, quotes)
    assert live_rows and all(r["quote_state"] == "live" for r in live_rows)
    # Ranking is the shared step between the live and reference paths; it must
    # NOT downgrade an already-live row to "reference".
    ranked = _rank_most_active_rows(live_rows, "volume")
    assert all(r["quote_state"] == "live" for r in ranked)


def test_rank_defaults_missing_quote_state_to_reference():
    """A bare reference row gains quote_state="reference" via ranking."""
    bare = [{"symbol": "AAA", "last": 10.0, "volume": 100, "change_pct": 1.0}]
    ranked = _rank_most_active_rows(bare, "volume")
    assert ranked[0]["quote_state"] == "reference"
