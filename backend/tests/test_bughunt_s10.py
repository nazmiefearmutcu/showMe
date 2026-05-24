"""Regression tests for Session 10 BugHunt fixes (2026-05-17).

Covers:

1. SYNTHETIC_SOURCE_MARKERS now flags ``reference_*`` sources so the
   live-source guard in ``server._has_live_source`` actually demotes
   fabricated payloads (OVDV vol smile model, OMON BS reference formula,
   WIRP/ECFC reference tables, PCAS template returns).
2. SYNTHETIC_SOURCE_MARKERS deliberately does NOT flag pure-model
   labels like ``black_scholes_formula`` so OVME/OSA (deterministic
   calculators that don't need a live underlying) survive the guard.
3. PCAS non-live source string switched to ``portfolio_state_template_returns``
   so the existing ``template`` marker catches the synthetic PCA result.
4. PEOP ``reference_people_search("")`` returns ``[]`` instead of the
   three Apple-leadership rows (previously ``tokens = ["apple"]``).
5. NSE ``live=false`` path returns an empty list with an honest
   synthetic-marked source instead of a single fabricated snapshot row.
"""

from __future__ import annotations

import pytest

from showme.server import (
    SYNTHETIC_SOURCE_MARKERS,
    _has_live_source,
    _is_synthetic_source,
)


class TestSyntheticSourceMarkers:
    def test_reference_marker_is_registered(self):
        # The marker list must catch any source label that contains the
        # token "reference" — OVDV / OMON ref / WIRP / ECFC all rely on
        # this to flag fabricated rows.
        assert "reference" in SYNTHETIC_SOURCE_MARKERS

    def test_template_marker_still_registered(self):
        # Pre-existing markers must remain so legacy detection paths
        # don't regress.
        for marker in ("template", "sample", "placeholder", "synthetic", "continuity"):
            assert marker in SYNTHETIC_SOURCE_MARKERS

    def test_pure_formula_label_is_NOT_marked_synthetic(self):
        # OVME/OSA legitimately label their output ``black_scholes_formula``
        # — they're pure pricing calculators that don't claim to be a
        # live data feed. We deliberately keep "formula" / "model" out of
        # the marker list so these survive ``_has_live_source``.
        assert _is_synthetic_source("black_scholes_formula") is False

    def test_reference_fx_vol_smile_model_IS_marked_synthetic(self):
        # OVDV's fabricated smile.
        assert _is_synthetic_source("reference_fx_vol_smile_model") is True

    def test_black_scholes_reference_formula_IS_marked_synthetic(self):
        # OMON's reference path source label — flagged via "reference".
        assert _is_synthetic_source("black_scholes_reference_formula") is True

    def test_portfolio_state_template_returns_IS_marked_synthetic(self):
        # PCAS non-live path (renamed in this BugHunt pass).
        assert _is_synthetic_source("portfolio_state_template_returns") is True

    def test_real_provider_labels_pass_through(self):
        # Real provider tokens must NOT be flagged.
        for source in (
            "yfinance",
            "yfinance_options",
            "yfinance_quote",
            "coingecko",
            "deribit",
            "mempool",
            "etherscan",
            "glassnode",
            "rss",
            "gdelt",
            "meilisearch",
        ):
            assert _is_synthetic_source(source) is False, source

    def test_has_live_source_demotes_when_only_reference_sources(self):
        # OVDV with only the reference label must be demoted.
        assert _has_live_source(["reference_fx_vol_smile_model"]) is False

    def test_has_live_source_keeps_payload_when_real_provider_present(self):
        # OMON's live path attaches "yfinance_options" — must survive.
        assert _has_live_source(["yfinance_options"]) is True


class TestPeopReferenceSearch:
    """PEOP must stop returning Apple-leadership for empty queries."""

    def test_empty_query_returns_empty_list(self):
        from showme.engine.functions.comm.peop import reference_people_search

        assert reference_people_search("") == []

    def test_single_char_query_returns_empty_list(self):
        # Tokens must be length > 1, so "?" / "x" are filtered.
        from showme.engine.functions.comm.peop import reference_people_search

        assert reference_people_search("?") == []
        assert reference_people_search("x") == []

    def test_unrelated_query_returns_empty_list(self):
        # No reference row matches "satoshi nakamoto" → empty.
        from showme.engine.functions.comm.peop import reference_people_search

        assert reference_people_search("satoshi nakamoto") == []

    def test_apple_query_still_returns_matches(self):
        # Sanity check: the reference set still works for real queries.
        from showme.engine.functions.comm.peop import reference_people_search

        rows = reference_people_search("apple")
        assert len(rows) > 0
        for row in rows:
            assert "apple" in (
                str(row.get("full_name", "")) + str(row.get("company", ""))
            ).lower()


class TestNseLiveFalsePath:
    """NSE ``live=false`` must not invent a placeholder article."""

    @pytest.mark.asyncio
    async def test_live_false_returns_empty_data_with_synthetic_source(self):
        from showme.engine.functions.news.nse import NSEFunction

        class _StubDeps:
            yfinance = None
            rss = None
            cache = None

        fn = NSEFunction(deps=_StubDeps())  # type: ignore[arg-type]
        result = await fn.execute(query="AAPL", live=False)
        assert result.data == []
        assert "local_news_template" in result.sources
        assert _is_synthetic_source(result.sources[0]) is True


class TestOmonResolveSpot:
    """OMON must derive spot from the live quote, not the $100 placeholder."""

    @pytest.mark.asyncio
    async def test_resolve_spot_uses_explicit_param_first(self):
        from showme.engine.core.instrument import AssetClass, Instrument
        from showme.engine.functions.derivative.omon import _resolve_spot

        class _Deps:
            yfinance = None

        spot = await _resolve_spot(
            _Deps(),
            Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
            {"spot": 232.5},
        )
        assert spot == 232.5

    @pytest.mark.asyncio
    async def test_resolve_spot_returns_100_when_no_yfinance_and_no_param(self):
        # Defensive fallback only kicks in when both signals are missing.
        from showme.engine.core.instrument import AssetClass, Instrument
        from showme.engine.functions.derivative.omon import _resolve_spot

        class _Deps:
            yfinance = None

        spot = await _resolve_spot(
            _Deps(),
            Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
            {},
        )
        assert spot == 100.0

    @pytest.mark.asyncio
    async def test_resolve_spot_pulls_from_yfinance_quote(self):
        from showme.engine.core.instrument import AssetClass, Instrument
        from showme.engine.functions.derivative.omon import _resolve_spot

        class _Quote:
            last = 232.5

        class _YFinance:
            async def fetch(self, request):  # noqa: ARG002
                return _Quote()

        class _Deps:
            yfinance = _YFinance()

        spot = await _resolve_spot(
            _Deps(),
            Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
            {},
        )
        assert spot == 232.5
