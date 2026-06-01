"""Degarbage tests for POLY (Polymarket prediction markets).

POLY must return REAL live prediction-market data from the keyless
Polymarket Gamma API, not the old gated/provider_unavailable stub as
the happy path. These tests:

  * build the handler with EMPTY deps (no injected polymarket adapter),
  * run execute() against the live keyless Gamma endpoint,
  * assert real rows + correct implied_prob math + methodology when the
    network is reachable,
  * and SKIP cleanly to asserting the graceful provider_unavailable
    shape when offline.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc.poly import (
    POLYFunction,
    _expand_outcome_rows,
    _matches_query,
)


def _run(coro):
    return asyncio.run(coro)


def test_poly_live_returns_real_markets_or_graceful_fallback():
    fn = POLYFunction(FunctionDeps())  # no polymarket adapter -> keyless default path
    result = _run(fn.execute(query=None, status="open", limit=10))

    data = result.data
    assert "polymarket" in result.sources
    assert isinstance(data.get("methodology"), str) and data["methodology"]
    assert isinstance(data.get("field_dictionary"), dict)

    status = data.get("status")
    if status == "provider_unavailable":
        # Honest network-outage fallback: NO fabricated rows.
        assert data["rows"] == []
        assert data.get("data_mode") == "not_configured"
        assert any("unavailable" in str(w).lower() for w in result.warnings)
        pytest.skip("Polymarket Gamma unreachable in this environment; verified graceful fallback shape.")

    # Live path: real, non-empty data.
    assert status in {"ok", "empty"}
    rows = data["rows"]
    assert isinstance(rows, list)
    if status == "empty":
        pytest.skip("Gamma reachable but returned zero open markets right now.")

    assert len(rows) > 0
    # Rows are per-outcome and match the manifest table_schema keys.
    sample = rows[0]
    for key in ("market_id", "question", "outcome", "price", "implied_prob", "source"):
        assert key in sample, f"missing column {key!r} in row"

    # Real values, not the old canned constants.
    assert isinstance(sample["question"], str) and sample["question"]
    assert isinstance(sample["price"], (int, float))
    assert 0.0 <= sample["price"] <= 1.0
    # implied_prob == price * 100 (manifest contract).
    assert sample["implied_prob"] == pytest.approx(sample["price"] * 100.0, abs=1e-6)
    assert sample["source"] == "polymarket_gamma"

    # Cards present per manifest card_schema.
    card_keys = {c.get("key") for c in data.get("cards", [])}
    assert {"market_count", "data_mode", "as_of"} <= card_keys


def test_poly_offline_fallback_is_honest(monkeypatch):
    """Force the keyless fetch to fail and assert the labeled fallback."""

    async def _boom(*_args, **_kwargs):
        raise ConnectionError("simulated network outage")

    import showme.engine.functions.misc.poly as poly_mod

    monkeypatch.setattr(poly_mod, "_fetch_gamma_markets", _boom)

    fn = POLYFunction(FunctionDeps())
    result = _run(fn.execute(query="election", status="open", limit=5))
    data = result.data

    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert data.get("data_mode") == "not_configured"
    assert "polymarket" in result.sources
    assert any("unavailable" in str(w).lower() for w in result.warnings)
    assert data.get("next_actions")


def test_expand_outcome_rows_computes_implied_prob():
    markets = [
        {
            "slug": "demo-market",
            "question": "Will X happen?",
            "outcomes": "Yes, No",
            "outcome_prices": "0.62, 0.38",
            "liquidity": 12345.0,
            "volume": 99999.0,
            "end_date": "2099-01-01T00:00:00Z",
        }
    ]
    rows = _expand_outcome_rows(markets)
    assert len(rows) == 2
    yes = next(r for r in rows if r["outcome"] == "Yes")
    assert yes["price"] == pytest.approx(0.62)
    assert yes["implied_prob"] == pytest.approx(62.0, abs=1e-6)
    assert yes["market_id"] == "demo-market"
    assert yes["source"] == "polymarket_gamma"


def test_matches_query_token_and():
    row = {"question": "Will the Fed cut rates in 2026?", "slug": "fed-cuts-2026"}
    assert _matches_query(row, "fed cuts") is True
    assert _matches_query(row, "election") is False
    assert _matches_query(row, None) is True
