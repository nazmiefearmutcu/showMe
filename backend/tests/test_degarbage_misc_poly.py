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


# ── Regression: routed browse path (2026-09-15) ──────────────────────────
# The /api/fn route used to inject the generic crypto-news query
# ("bitcoin cryptocurrency") into POLY's `query`; POLY treats `query` as a
# strict AND-token filter, so a browse request came back with 0 markets and
# data_mode='cached_snapshot'. These tests pin the browse parse with a
# stubbed provider and the honest empty-filter reason.


def _gamma_fixture():
    return [
        {
            "slug": "fed-cut-sept",
            "question": "Will the Fed cut rates in September?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.72", "0.28"]',
            "liquidity": "250000",
            "volume": "900000",
            "endDate": "2099-09-16T00:00:00Z",
        },
        {
            "slug": "btc-150k-2026",
            "question": "Bitcoin above $150k in 2026?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.31", "0.69"]',
            "liquidity": "90000",
            "volume": "50000",
            "endDate": "2099-12-31T00:00:00Z",
        },
    ]


def test_poly_stubbed_provider_parses_browse_rows_without_query(monkeypatch):
    import showme.engine.functions.misc.poly as poly_mod

    async def _fake_fetch(*_args, **_kwargs):
        return _gamma_fixture()

    monkeypatch.setattr(poly_mod, "_fetch_gamma_markets", _fake_fetch)

    fn = POLYFunction(FunctionDeps())
    result = _run(fn.execute(status="open", min_liquidity_usd=10_000, limit=25))
    data = result.data

    assert data["status"] == "ok"
    assert data["data_mode"] == "delayed_reference"
    assert len(data["markets"]) == 2
    assert len(data["rows"]) == 4
    yes = next(
        r for r in data["rows"]
        if r["outcome"] == "Yes" and r["market_id"] == "fed-cut-sept"
    )
    assert yes["implied_prob"] == pytest.approx(72.0, abs=1e-6)
    assert yes["liquidity_usd"] == pytest.approx(250000.0)


def test_poly_stubbed_provider_keeps_rows_when_caller_passes_no_query():
    """The /api/fn route default must not inject a news query (root cause)."""
    from showme import server

    routed = server._route_function_params(
        "POLY", {"status": "open", "min_liquidity_usd": 10_000}
    )
    assert not routed.get("query"), (
        "POLY browse must not receive the generic news query — it is a strict "
        "AND-token topic filter that zeroed every market list"
    )


def test_poly_empty_topic_filter_reports_reason(monkeypatch):
    import showme.engine.functions.misc.poly as poly_mod

    async def _fake_fetch(*_args, **_kwargs):
        return _gamma_fixture()

    monkeypatch.setattr(poly_mod, "_fetch_gamma_markets", _fake_fetch)

    fn = POLYFunction(FunctionDeps())
    result = _run(
        fn.execute(query="bitcoin cryptocurrency", status="open", min_liquidity_usd=0)
    )
    data = result.data

    assert data["status"] == "empty"
    assert data["data_mode"] == "cached_snapshot"
    assert data["rows"] == []
    assert any("bitcoin cryptocurrency" in w for w in result.warnings)
