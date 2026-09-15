"""Session-17 screener-universe campaign regression guards.

Reported bug: the EQS pane said "MATCHED 0 of 11 scanned" while the universe
chip claimed "custom (503 symbols)", and the FSRC/SRCH/ICX universes were
absurdly short. Verified root causes pinned here:

* EQS filtered ``dividendYield`` against a ``dividend_yield`` column with no
  alias fold → every predicate on it matched zero rows.
* EQS live ``dividend_yield`` is percent-form on newer yfinance (MMM 1.93)
  while the presets compare fraction-form (``> 0.04``) → unit mismatch.
* EQS only completed ~11 of 503 symbols per call because every symbol went
  through the provider's shared 2 rps token bucket; the batched Yahoo quote
  endpoint now fills the whole universe in a few calls.
* FSRC shipped 10 funds, SRCH 8 bonds, ICX 12–15-name index stubs.

These tests pin the fixes (alias map, unit convention, full-universe batch
scan, expanded reference universes) without touching the Session-05 universe
label contract.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.equity import eqs as eqs_mod  # noqa: E402
from showme.engine.functions.screen import _funcs as screen_funcs  # noqa: E402
from showme.engine.functions.screen import icx as icx_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """The live caches are module state; isolate every test from its peers."""
    eqs_mod._EQS_BATCH_CACHE.clear()
    eqs_mod._EQS_REFDATA_CACHE.clear()
    eqs_mod._SECURITY_MASTER_INDEX = None
    icx_mod._INDEX_MEMBERS_CACHE.clear()
    yield
    eqs_mod._EQS_BATCH_CACHE.clear()
    eqs_mod._EQS_REFDATA_CACHE.clear()
    icx_mod._INDEX_MEMBERS_CACHE.clear()


# ── EQS: alias fold + unit normalisation ─────────────────────────────────────


def test_eqs_dividend_yield_alias_matches_same_rows_as_real_column():
    df = pd.DataFrame([
        {"symbol": "AAA", "dividend_yield": 0.062},
        {"symbol": "BBB", "dividend_yield": 0.0193},
        {"symbol": "CCC", "dividend_yield": 0.0},
    ])
    camel = eqs_mod.filter_dataframe(df, "dividendYield > 0.04")
    snake = eqs_mod.filter_dataframe(df, "dividend_yield > 0.04")
    assert list(camel["symbol"]) == ["AAA"]
    assert list(camel["symbol"]) == list(snake["symbol"])


def test_eqs_alias_normalisation_map_folds_known_spellings():
    rewritten = eqs_mod.normalize_query_aliases(
        "dividendYield > 0.04 AND market_cap > 1e9 AND pe_ratio < 15 AND price_to_book < 3"
    )
    assert rewritten == "dividend_yield > 0.04 AND marketCap > 1e9 AND pe < 15 AND pb < 3"


def test_eqs_live_dividend_yield_is_decimal_fraction():
    """Percent-form provider values (MMM 1.93) become 0.0193; decimal stays."""
    assert eqs_mod._normalize_raw_fields({"dividendYield": 1.93})["dividend_yield"] == pytest.approx(0.0193)
    assert eqs_mod._normalize_raw_fields({"dividendYield": 0.0193})["dividend_yield"] == pytest.approx(0.0193)
    assert eqs_mod._normalize_raw_fields({"dividendYield": None})["dividend_yield"] is None


def test_eqs_live_row_query_units_are_consistent():
    """A percent-form 6.2% yield must match ``dividendYield > 0.04`` exactly once."""
    row = eqs_mod._compose_live_row(
        "DIVCO",
        {"dividendYield": 6.2, "marketCap": 5.0e10},
        None,
        None,
    )
    df = pd.DataFrame([row])
    assert list(eqs_mod.filter_dataframe(df, "dividendYield > 0.04")["symbol"]) == ["DIVCO"]
    assert list(eqs_mod.filter_dataframe(df, "dividend_yield > 0.04")["symbol"]) == ["DIVCO"]
    # And a sub-threshold 1.93% yield must match neither spelling.
    low = eqs_mod._compose_live_row("LOWCO", {"dividendYield": 1.93, "marketCap": 5.0e10}, None, None)
    low_df = pd.DataFrame([low])
    assert eqs_mod.filter_dataframe(low_df, "dividendYield > 0.04").empty
    assert eqs_mod.filter_dataframe(low_df, "dividend_yield > 0.04").empty


def test_eqs_master_sector_vocabulary_folds_to_yahoo_names():
    assert eqs_mod._normalize_sector_name("Information Technology") == "Technology"
    assert eqs_mod._normalize_sector_name("Health Care") == "Healthcare"
    assert eqs_mod._normalize_sector_name("Energy") == "Energy"
    assert eqs_mod._normalize_sector_name(None) is None


def test_eqs_live_row_sector_from_master_is_queryable():
    """The master's GICS naming must not break the pane's Yahoo-vocab presets."""
    row = eqs_mod._compose_live_row(
        "AAPL",
        {"marketCap": 3.0e12},
        None,
        {"sector": "Information Technology", "country": "US"},
    )
    df = pd.DataFrame([row])
    assert list(eqs_mod.filter_dataframe(df, 'sector = "Technology"')["symbol"]) == ["AAPL"]


# ── EQS: batched live scan coverage ──────────────────────────────────────────


class _BatchYF:
    """Provider double exposing only the batched quote endpoint."""

    def __init__(self, payload: dict[str, dict]) -> None:
        self.payload = payload
        self.batch_calls: list[list[str]] = []

    async def fetch_refdata_batch(self, symbols, **_kwargs):
        self.batch_calls.append([str(s).upper() for s in symbols])
        return {str(s).upper(): self.payload[str(s).upper()] for s in symbols if str(s).upper() in self.payload}


def _batch_payload() -> dict[str, dict]:
    return {
        "AAPL": {"marketCap": 3.0e12, "trailingPE": 28.0, "priceToBook": 41.0, "dividendYield": 0.5},
        "MSFT": {"marketCap": 3.2e12, "trailingPE": 34.0, "priceToBook": 11.8, "dividendYield": 0.8},
        "NVDA": {"marketCap": 2.9e12, "trailingPE": 40.0, "priceToBook": 30.0, "dividendYield": 0.03},
    }


def test_eqs_live_batch_scans_whole_requested_universe():
    provider = _BatchYF(_batch_payload())
    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=provider))
    result = asyncio.run(fn.execute(
        instrument=None,
        query="marketCap > 1000000000000",
        live_screen=True,
        universe=["AAPL", "MSFT", "NVDA"],
    ))
    df = result.data
    assert isinstance(df, pd.DataFrame)
    assert result.metadata["scanned"] == 3
    assert result.metadata["universe_size"] == 3
    assert result.metadata["live"] is True
    assert set(df["symbol"]) == {"AAPL", "MSFT", "NVDA"}
    # Sector/industry/beta are unknown on the batch path — never fabricated 0.
    aapl = df[df["symbol"] == "AAPL"].iloc[0]
    assert aapl["dividend_yield"] == pytest.approx(0.005)
    assert aapl["beta"] is None or pd.isna(aapl["beta"])


def test_eqs_live_batch_gap_is_dropped_not_stubbed():
    """Symbols the provider has no row for are honest gaps, not fake rows."""
    provider = _BatchYF(_batch_payload())
    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=provider))
    result = asyncio.run(fn.execute(
        instrument=None,
        query="marketCap > 0",
        live_screen=True,
        universe=["AAPL", "MSFT", "NVDA", "DELISTED"],
    ))
    assert result.metadata["scanned"] == 3
    assert result.metadata["universe_size"] == 4
    assert "DELISTED" not in set(result.data["symbol"])


def test_eqs_batch_failure_falls_back_to_per_symbol_refdata():
    class _BoomBatchYF:
        async def fetch_refdata_batch(self, symbols, **_kwargs):
            raise RuntimeError("batch endpoint down")

        async def fetch(self, request):
            return SimpleNamespace(
                sector="Technology",
                industry="Software",
                market_cap=2.0e11,
                country="US",
                extras={"raw": {
                    "trailingPE": 24.0,
                    "priceToBook": 6.0,
                    "dividendYield": 1.0,
                    "beta": 1.2,
                }},
            )

    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=_BoomBatchYF()))
    result = asyncio.run(fn.execute(
        instrument=None,
        query="marketCap > 1000000000",
        live_screen=True,
        universe="AAPL,MSFT,NVDA",
    ))
    assert isinstance(result.data, pd.DataFrame)
    assert result.metadata["scanned"] == 3
    assert result.metadata["live"] is True


# ── FSRC: expanded fund universe ─────────────────────────────────────────────


def test_fsrc_fund_universe_is_comprehensive():
    rows = screen_funcs._fund_reference_rows()
    assert len(rows) >= 60
    symbols = {row["symbol"] for row in rows}
    assert {"SPY", "QQQ", "VTI", "IWM", "EEM", "GLD", "TLT", "HYG"} <= symbols
    # New liquid categories added with the expansion.
    assert {"SCHD", "VEA", "AGG", "SCHP", "MUB", "ADX", "AVUV"} <= symbols
    categories = {row["category"] for row in rows}
    assert len(categories) >= 12
    # The eight original pane chips must keep matching real rows.
    assert {
        "US Large Blend", "US Large Growth", "US Total Market", "US Small Blend",
        "Emerging Markets", "Commodity Precious Metals", "Long Government",
        "High Yield Bond",
    } <= categories
    for row in rows:
        assert row["symbol"] and row["name"] and row["issuer"] and row["category"]
        assert row["aum_usd"] > 0 and 0 <= row["expenseRatio"] < 0.05


def test_fsrc_accepts_dividend_yield_alias_predicate():
    """The screen suite must fold ``dividendYield`` before its column check."""
    rows = screen_funcs._fund_reference_rows()
    assert screen_funcs._rewrite_screen_query("dividendYield > 0.01") == "dividend_yield > 0.01"
    filtered = screen_funcs._apply_screen_query(rows, "dividendYield > 0.01")
    assert filtered
    assert all(row["dividend_yield"] > 0.01 for row in filtered)


# ── SRCH: full sovereign curve + TIPS ────────────────────────────────────────


def test_srch_bond_universe_covers_full_curve():
    rows = screen_funcs._bond_reference_rows()
    assert len(rows) >= 25
    symbols = {row["symbol"] for row in rows}
    assert {
        "US3M", "US2Y", "US5Y", "US10Y", "US30Y",
        "DE2Y", "DE10Y", "GB2Y", "GB10Y", "JP2Y", "JP10Y",
        "FR2Y", "FR10Y", "IT2Y", "IT10Y", "ES2Y", "ES10Y",
        "USTIPS5Y", "USTIPS10Y", "USTIPS30Y",
    } <= symbols
    types = {row["type"] for row in rows}
    assert "TIPS" in types
    for row in rows:
        assert row["yield"] > 0
        assert row["duration"] > 0
        assert row["tenor_years"] > 0


def test_srch_live_treasury_tenors_match_reference_rows():
    rows = {row["symbol"] for row in screen_funcs._bond_reference_rows()}
    live = screen_funcs._US_TREASURY_CURVE_COLUMNS
    assert {"US6M", "US1Y", "US3Y", "US7Y", "US20Y"} <= set(live)
    # Every live-refreshable tenor must have a reference row to merge into.
    assert set(live) <= rows


# ── ICX: full SP500 + expanded NDX/DJIA ──────────────────────────────────────


def test_icx_sp500_returns_full_constituent_list():
    spx = icx_mod._template_constituents("SPX")
    assert len(spx) >= 500
    # Session-08 contract: a DAX query never leaks SPX names AND the SPX table
    # still leads with AAPL (the historical first-row pin).
    assert spx.iloc[0]["symbol"] == "AAPL"
    symbols = set(spx["symbol"])
    assert {"MMM", "ZTS", "NVDA", "BRK.B"} <= symbols
    companies = set(spx["company"])
    assert "Apple Inc." in companies


def test_icx_expanded_index_minimums():
    assert len(icx_mod._template_constituents("DJIA")) == 30
    assert len(icx_mod._template_constituents("NDX")) >= 25
    for code in ("DAX", "CAC", "FTSE", "STOXX", "BIST"):
        assert len(icx_mod._template_constituents(code)) >= 10


def test_icx_batch_quotes_attach_to_full_sp500():
    class _BatchQuoteProvider:
        async def fetch_refdata_batch(self, symbols, **_kwargs):
            return {
                "AAPL": {"regularMarketPrice": 330.07, "regularMarketChangePercent": -0.9},
                "MSFT": {"regularMarketPrice": 497.33, "regularMarketChangePercent": 1.2},
            }

    fn = icx_mod.ICXFunction(deps=FunctionDeps(yfinance=_BatchQuoteProvider()))
    result = asyncio.run(fn.execute(index="SPX", quotes="1"))
    data = result.data
    assert data["status"] == "ok"
    assert len(data["rows"]) == 503
    by_symbol = {row["symbol"]: row for row in data["rows"]}
    assert by_symbol["AAPL"]["last"] == pytest.approx(330.07)
    assert by_symbol["MSFT"]["change_pct"] == pytest.approx(1.2)
    assert by_symbol["MMM"]["last"] is None  # no fabricated price
    assert "yfinance" in result.sources


def test_icx_index_quotes_disabled_leaves_prices_null():
    fn = icx_mod.ICXFunction(deps=FunctionDeps())
    result = asyncio.run(fn.execute(index="SPX", quotes="0"))
    assert len(result.data["rows"]) == 503
    assert all(row["last"] is None and row["change_pct"] is None for row in result.data["rows"])
