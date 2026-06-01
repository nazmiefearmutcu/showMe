"""Degarbage tests for ICX — Index / Industry Constituents Explorer.

ICX previously scraped Wikipedia HTML (brittle/blocked) and on failure returned
a hardcoded ``_template_constituents`` constant. It now resolves a GICS sector
to REAL curated member companies from a bundled classification table (the same
legitimacy class as SECT's SPDR ETF map) and attaches best-effort live keyless
quotes.

Network calls are guarded: when the quote provider is unreachable the status
stays ``ok`` with null prices and an honest warning — never fabricated numbers.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen.icx import ICXFunction


def _run(coro):
    return asyncio.run(coro)


def _make() -> ICXFunction:
    return ICXFunction(FunctionDeps())


def test_icx_returns_real_constituents():
    fn = _make()
    result = _run(fn.execute(sector="Information Technology"))
    data = result.data

    assert data["status"] == "ok"

    # Real curated rows (not the old _template_constituents list and not raw
    # Wikipedia HTML fragments).
    rows = data["rows"]
    assert rows, "expected constituent rows"
    symbols = {r["symbol"] for r in rows}
    assert {"AAPL", "MSFT", "NVDA", "AVGO"} <= symbols

    for r in rows:
        assert set(r) == {
            "symbol",
            "company",
            "sub_industry",
            "sector",
            "last",
            "change_pct",
        }
        assert isinstance(r["symbol"], str) and r["symbol"]
        assert isinstance(r["company"], str) and r["company"]
        # Real GICS sub-industry classification, not a placeholder.
        assert r["sub_industry"]
        assert r["sector"] == "Information Technology"

    # No Wikipedia provenance / old garbage artefacts.
    assert "wikipedia" not in [s.lower() for s in result.sources]
    assert "Wikipedia" not in data["methodology"]
    assert data["methodology"]
    assert "showme_gics_reference" in result.sources

    summary = data["summary"]
    assert summary["sector"] == "Information Technology"
    assert summary["constituent_count"] == len(rows)
    assert "source" in summary

    fd = data["field_dictionary"]
    assert {"symbol", "company", "sub_industry"} <= set(fd)


def test_icx_sector_alias_resolves():
    fn = _make()
    result = _run(fn.execute(sector="tech"))
    data = result.data
    assert data["status"] == "ok"
    assert data["rows"]
    assert all(r["sector"] == "Information Technology" for r in data["rows"])


def test_icx_other_sectors_populated():
    fn = _make()
    for sector in ("Financials", "Health Care", "Energy"):
        result = _run(fn.execute(sector=sector))
        data = result.data
        assert data["status"] == "ok", sector
        assert data["rows"], sector
        assert all(r["sector"] == sector for r in data["rows"])


def test_icx_unknown_sector_is_honest_empty():
    fn = _make()
    result = _run(fn.execute(sector="Totally Made Up Sector"))
    data = result.data
    assert data["status"] == "empty"
    assert data["rows"] == []
    assert data["methodology"]
    assert "available_sectors" in data
    assert "Information Technology" in data["available_sectors"]


def test_icx_quotes_attached_or_gracefully_null():
    """Live quote attachment is best-effort.

    When the quote provider answers we should see numeric ``last`` and
    ``yfinance`` in sources. When the network is unavailable the status stays
    ``ok`` with null prices and an honest warning — NEVER fabricated.
    """
    fn = _make()
    result = _run(fn.execute(sector="Information Technology"))
    data = result.data
    assert data["status"] == "ok"

    has_live_price = any(
        isinstance(r.get("last"), (int, float)) for r in data["rows"]
    )
    if has_live_price:
        # At least one real price attached → provenance must name yfinance.
        assert "yfinance" in result.sources
    else:
        # Fully offline / blocked: rows are still real constituents with null
        # prices and an honest warning — never fabricated numbers.
        assert all(r.get("last") is None for r in data["rows"])
        assert all(r["symbol"] for r in data["rows"])
        assert any("unavailable" in w.lower() for w in result.warnings)
    # Constituents are real regardless of quote availability.
    assert all(r["company"] and r["sub_industry"] for r in data["rows"])


def test_icx_quotes_disabled_leaves_prices_null():
    fn = _make()
    result = _run(fn.execute(sector="Information Technology", quotes="0"))
    data = result.data
    assert data["status"] == "ok"
    assert data["rows"]
    assert all(
        r["last"] is None and r["change_pct"] is None for r in data["rows"]
    )
    assert "yfinance" not in result.sources
    assert any("disabled" in w.lower() for w in result.warnings)
