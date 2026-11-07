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
