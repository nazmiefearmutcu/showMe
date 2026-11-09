"""Local records and computed previews never classify as live market data.

Strict truth audit 2026-11-07: ``_classify_source_state`` defaulted every
unknown source name to ``live``, so a paper-ticket preview (BBGT/EMSX/FXGO/
TSOX), the local portfolio book (TLH) and the margin engine all carried a
LIVE pill.
"""
from __future__ import annotations

import pytest

from showme.server import _classify_source_state


@pytest.mark.parametrize("name", ["PAPER_TICKET", "paper_ticket", "margin_engine", "empty_book",
                                  "black_scholes_model"])
def test_computed_sources_are_model(name):
    assert _classify_source_state(name) == "model"


@pytest.mark.parametrize("name", ["portfolio_state", "order_history"])
def test_local_records_are_reference(name):
    assert _classify_source_state(name) == "reference"


@pytest.mark.parametrize("name", ["yfinance", "yahoo_chart", "fred", "polymarket", "wikipedia"])
def test_real_providers_stay_live(name):
    assert _classify_source_state(name) == "live"


@pytest.mark.parametrize("name", ["heston_formula", "black_scholes_formula", "heston_mc"])
def test_closed_form_and_model_pricers_are_model(name):
    assert _classify_source_state(name) == "model"


# Offline audit T10 (2026-11-08): in-app catalogs/registries and other local
# origins answered "live" with the network cut, because unknown names
# defaulted to live.
@pytest.mark.parametrize("name", [
    "showme_field_catalog", "showme_i18n_registry", "showme_curriculum", "local_notebook_manifest",
    "local_capture_plan", "local fallback", "macos_local_auth_bridge", "showme_fastapi_routes_curated",
    "showme_fastapi_routes_live", "exchange_calendars", "local_tax_lot_ledger",
])
def test_local_and_static_origins_are_reference(name):
    assert _classify_source_state(name) == "reference"


@pytest.mark.parametrize("name, state", [
    ("showme_quotes", "live"),  # the live quote aggregator keeps its live label
    ("local_backtest_model", "model"),  # a model stays a model even when local
    ("showme_chart_model", "model"),
])
def test_marker_precedence(name, state):
    assert _classify_source_state(name) == state


@pytest.mark.parametrize("name, state", [
    ("test_data", "synthetic"), ("testing_feed", "synthetic"), ("demo_prices", "synthetic"),
    ("latest_close", "live"),  # "test" inside a word is not the blocklisted marker
])
def test_blocklist_matches_word_starts_only(name, state):
    assert _classify_source_state(name) == state
