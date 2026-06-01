"""Regression tests for the 2026-05-24 news-engine BugHunt.

Each test pins a HIGH or MEDIUM-impact bug from
``/Users/nazmi/Desktop/showme_bughunt_2026-05-24/SHOWME_BUGHUNT_REPORT.md``
(Theme 5). The contract assertions are kept tight on PURPOSE — a future
refactor that re-introduces the old behaviour must break exactly one of
these tests, not silently regress UI rendering.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.core.quote import Quote  # noqa: E402  (kept for potential future use)
from showme.engine.functions.news.av import AVFunction, _matches_query  # noqa: E402
from showme.engine.functions.news.evts import _date_value, _scalar_value  # noqa: E402
from showme.engine.functions.news.ni import (  # noqa: E402
    NIFunction,
    _coerce_float,
    _coerce_int,
)
from showme.engine.functions.news.read import READFunction, _parse_symbol_list  # noqa: E402
from showme.engine.functions.news.tldr import TLDRFunction  # noqa: E402
from showme.engine.functions.news.tran import TRANFunction  # noqa: E402
from showme.engine.functions.news.trqa import (  # noqa: E402
    _extractive_answer,
    _extractive_confidence,
)


def _run(coro):
    return asyncio.run(coro)


# ── Bug #1: AV — generic-term short-circuit ────────────────────────────────


def test_av_matches_query_rejects_generic_podcast_term_against_planet_money() -> None:
    """The query "Apple Podcasts MSFT review" must NOT match a generic
    Planet Money episode about macro markets. Previous code short-circuited
    TRUE for any query containing the word "podcast"."""
    planet_money_row = {
        "feed": "Planet Money",
        "title": "Planet Money: macro markets and the Fed this week",
        "summary": "A weekly podcast on macro and market news from NPR.",
    }
    assert _matches_query(planet_money_row, "Apple Podcasts MSFT review") is False


def test_av_matches_query_accepts_real_substring_match() -> None:
    row = {
        "feed": "TechCo Earnings",
        "title": "MSFT Q3 earnings call replay — Microsoft beats estimates",
        "summary": "Microsoft Corporation reports fiscal Q3 results.",
    }
    assert _matches_query(row, "MSFT earnings") is True
    assert _matches_query(row, "Microsoft") is True


def test_av_matches_query_empty_query_returns_everything() -> None:
    row = {"feed": "X", "title": "Y", "summary": "Z"}
    assert _matches_query(row, "") is True
    assert _matches_query(row, "   ") is True


def test_av_matches_query_only_stop_words_requires_literal_hit() -> None:
    """If a query is all stop words ("podcast", "market"), we only accept
    rows whose haystack contains one of those literal tokens. That keeps
    the door open for terse user queries while killing the false-true
    shortcut on generic media nouns."""
    row_with_word = {"feed": "Anything", "title": "podcast roundup", "summary": ""}
    row_without = {"feed": "Anything", "title": "monetary policy briefing", "summary": ""}
    assert _matches_query(row_with_word, "podcast") is True
    assert _matches_query(row_without, "podcast") is False


# ── Bug #2: TLDR — negative-mover quote-source disagreement ────────────────


def test_tldr_flags_msft_negative_mover_using_canonical_quote_source(monkeypatch) -> None:
    """TLDR must share the quote source with /api/quote/<sym>. Previously
    it walked deps.yfinance and got a stale close_prev, so MSFT at -0.79%
    was never reported as a negative mover.

    The fix: TLDR calls showme.quotes.fetch_quote_snapshot directly. We
    monkeypatch that function to return a deterministic MSFT snapshot at
    -0.79% and assert the markdown reports it as a negative mover."""
    import showme.quotes as _qmod

    async def _fake_snapshot(symbol: str):
        sym = (symbol or "").upper()
        if sym == "MSFT":
            return {
                "symbol": "MSFT",
                "last": 412.10,
                "previous_close": 415.40,
                "change_pct": -0.79,
                "source": "yahoo_chart",
            }
        return {
            "symbol": sym,
            "last": 100.0,
            "previous_close": 100.0,
            "change_pct": 0.0,
            "source": "yahoo_chart",
        }

    monkeypatch.setattr(_qmod, "fetch_quote_snapshot", _fake_snapshot)

    fn = TLDRFunction(deps=FunctionDeps())
    result = _run(
        fn.execute(
            symbols=["MSFT", "AAPL"],
            quote_timeout=2.0,
            news_timeout=0.1,
            eco_timeout=0.1,
            llm_timeout=0.1,
            timeout=3.0,
        )
    )
    quotes = result.data["quotes"]
    msft = next(q for q in quotes if q["symbol"] == "MSFT")
    assert msft["change_pct"] == pytest.approx(-0.79)
    assert msft["quote_source"] == "yahoo_chart"
    markdown = result.data.get("markdown") or ""
    # MSFT must show up in the down-movers line.
    assert "MSFT" in markdown
    assert "-0.79" in markdown
    assert "No live negative movers" not in markdown


# ── Bug #3: TRAN — synthetic transcripts must NEVER be emitted ─────────────
#
# De-garbage 2026-06-01: TRAN was upgraded from "provider_unavailable / opt-in
# synthetic template" to a REAL keyless source (user-pasted transcript_text or
# SEC EDGAR 8-K Exhibit 99.x earnings press release). The synthetic template
# (and the ``include_synthetic`` / ``allow_synthetic`` toggles + the
# ``showme_synthetic_template`` source) were removed entirely. These tests now
# pin the stronger contract: there is NO synthetic path at all, a pasted
# transcript yields REAL ok rows, and a missing real source degrades honestly.


def test_tran_real_pasted_transcript_returns_ok_rows() -> None:
    """A user-pasted transcript is parsed into REAL speaker-attributed rows —
    never the old hardcoded placeholder template."""
    fn = TRANFunction(deps=FunctionDeps())
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    transcript = (
        "Operator -- Conference Coordinator\n\nWelcome to the call.\n\n"
        "Tim Cook -- Chief Executive Officer\n\n"
        "Revenue was $94.9 billion, an all-time September-quarter record."
    )
    result = _run(fn.execute(inst, transcript_text=transcript))
    assert result.data["status"] == "ok"
    assert result.data["data_mode"] == "user_supplied"
    assert result.data["utterances"], "real rows expected"
    assert any("94.9" in r["utterance"] for r in result.data["utterances"])
    # The legacy synthetic source/attribution must be gone for good.
    assert "showme_synthetic_template" not in result.sources
    assert "seekingalpha" not in result.sources
    assert "placeholders are structured for downstream search" not in str(result.data)


def test_tran_no_synthetic_path_remains() -> None:
    """``include_synthetic`` / ``allow_synthetic`` are dead toggles now — with
    no real source and no network, TRAN degrades honestly and NEVER returns a
    synthetic template or the ``showme_synthetic_template`` source."""
    fn = TRANFunction(deps=FunctionDeps())
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    for kwargs in ({"include_synthetic": True}, {"allow_synthetic": True}, {"live_transcripts": True}):
        result = _run(fn.execute(inst, **kwargs))
        # Either a real SEC transcript came back (ok) or it degraded honestly.
        assert result.data["status"] in {"ok", "empty", "provider_unavailable"}
        assert "synthetic" not in result.data["status"]
        assert "showme_synthetic_template" not in result.sources
        assert result.metadata.get("data_state") != "synthetic"
        # No canned placeholder text under any toggle.
        assert "placeholders are structured for downstream search" not in str(result.data)
        if result.data["status"] in {"empty", "provider_unavailable"}:
            assert result.data["utterances"] == []
            assert result.data.get("next_actions")


# ── Bug #4: NI — topic mode TypeError on string limit ──────────────────────


def test_ni_coerce_int_string_limit_returns_int() -> None:
    """The root cause: NI used to forward ``params.get("limit", 50)`` raw
    to ``DataRequest(limit=...)`` which crashed the RSS adapter with
    ``TypeError: slice indices must be integers or None`` when the value
    arrived as a string from the URL query."""
    assert _coerce_int("50", default=50, min_value=1, max_value=500) == 50
    assert _coerce_int(75, default=50, min_value=1, max_value=500) == 75
    assert _coerce_int(None, default=50, min_value=1, max_value=500) == 50
    assert _coerce_int("", default=50, min_value=1, max_value=500) == 50
    assert _coerce_int("not-a-number", default=50, min_value=1, max_value=500) == 50
    # Clamp to range
    assert _coerce_int("9999", default=50, min_value=1, max_value=500) == 500
    assert _coerce_int("-5", default=50, min_value=1, max_value=500) == 1
    # Float-shaped input still safely lands as int
    assert _coerce_int("12.7", default=50, min_value=1, max_value=500) == 12


def test_ni_coerce_float_handles_bad_input() -> None:
    assert _coerce_float("5.5", default=5.0, min_value=0.5, max_value=30.0) == pytest.approx(5.5)
    assert _coerce_float(None, default=5.0, min_value=0.5, max_value=30.0) == 5.0
    assert _coerce_float("xyz", default=5.0, min_value=0.5, max_value=30.0) == 5.0


def test_ni_topic_mode_does_not_crash_with_diverse_string_args() -> None:
    """Smoke: NI must complete without TypeError when topic mode is hit
    with the exact param shapes the UI used to send (all strings)."""
    fn = NIFunction(deps=FunctionDeps())
    result = _run(
        fn.execute(
            None,
            topic="BANKS",
            limit="25",
            threshold="60",
            news_timeout="2",
            live=False,
        )
    )
    assert result.code == "NI"
    # No TypeError surfaced as a provider_error.
    errors = result.metadata.get("provider_errors") or []
    assert not any("slice indices" in str(err) for err in errors), errors


# ── Bug #5: CN — UI/localStorage leak (out of scope here) ──────────────────
#
# The CN backend in ``backend/showme/engine/functions/news/cn.py`` already
# respects ``instrument.symbol``: see the existing ``backend/tests/test_cn.py``
# regression suite which pins ``_prefer_direct_symbol_matches``. The "AMZN
# default" leak lives in the UI's localStorage cache (out of this agent's
# scope per the BugHunt isolation contract).


# ── Bug #6: EVTS — stringified Python repr of date list ────────────────────


def test_evts_date_value_unwraps_single_element_list_of_dates() -> None:
    """Was: yfinance hands back ``[date(2026,7,30)]`` and EVTS rendered the
    literal Python repr ``"[datetime.date(2026, 7, 30)]"`` into the UI."""
    result = _date_value([date(2026, 7, 30)])
    assert result == "2026-07-30"


def test_evts_date_value_unwraps_multi_value_list_to_first_dated_item() -> None:
    """Two-element earnings windows should still serialise to a real date."""
    result = _date_value([date(2026, 7, 30), date(2026, 8, 3)])
    assert result == "2026-07-30"


def test_evts_date_value_passes_through_iso_string() -> None:
    assert _date_value("2026-07-30") == "2026-07-30"


def test_evts_date_value_handles_datetime() -> None:
    dt = datetime(2026, 7, 30, 13, 45, tzinfo=timezone.utc)
    assert _date_value(dt) == "2026-07-30T13:45:00+00:00"


def test_evts_scalar_value_unwraps_single_element_list_of_dates() -> None:
    out = _scalar_value([date(2026, 7, 30)])
    assert out == "2026-07-30"


# ── Bug #7: READ — must accept symbols= and watchlist= ────────────────────


def test_read_parse_symbol_list_accepts_csv_string() -> None:
    assert _parse_symbol_list("AAPL,MSFT,nvda") == ["AAPL", "MSFT", "NVDA"]


def test_read_parse_symbol_list_accepts_list() -> None:
    assert _parse_symbol_list(["aapl", "MSFT", ""]) == ["AAPL", "MSFT"]


def test_read_parse_symbol_list_none_returns_empty() -> None:
    assert _parse_symbol_list(None) == []
    assert _parse_symbol_list("") == []


def test_read_accepts_symbols_param() -> None:
    """``READ`` (now a saved-articles reading list per its manifest) must still
    honour the ``symbols=`` filter the BugHunt fix added — it is threaded into
    the store query and echoed in ``metadata["watchlist"]`` instead of being
    dropped for the hardcoded AAPL/MSFT/BTCUSDT default."""
    fn = READFunction(deps=FunctionDeps())
    result = _run(fn.execute(symbols="GOOG,NVDA"))
    # New store-backed shape: data is a dict with rows/articles, not a list.
    assert isinstance(result.data, dict)
    assert result.data["status"] in {"ok", "empty"}
    assert result.metadata["watchlist"] == ["GOOG", "NVDA"]


def test_read_symbols_param_wins_over_watchlist_param() -> None:
    fn = READFunction(deps=FunctionDeps())
    result = _run(fn.execute(symbols="TSLA", watchlist=["IGNORED"]))
    assert result.metadata["watchlist"] == ["TSLA"]


def test_read_still_accepts_legacy_watchlist_param() -> None:
    fn = READFunction(deps=FunctionDeps())
    result = _run(fn.execute(watchlist=["ETHUSDT"]))
    assert result.metadata["watchlist"] == ["ETHUSDT"]


# ── Bug #8: TRQA — confidence must reflect real signal or be None ──────────


def test_trqa_extractive_confidence_returns_none_when_no_signal() -> None:
    """Was: confidence always at least 0.35 (and 0.59 for two-hit case).
    With zero question terms and zero domain matches, confidence MUST be
    None — refuse to publish a fake number."""
    result = _extractive_answer("This is a generic sentence.", "")
    assert result["confidence"] is None


def test_trqa_extractive_confidence_real_signal_yields_real_number() -> None:
    text = (
        "Revenue grew 12 percent year over year. "
        "Management raised full-year guidance citing strong demand. "
        "Margins expanded by 80 basis points."
    )
    result = _extractive_answer(text, "What was the revenue growth and guidance change?")
    assert isinstance(result["confidence"], float)
    assert 0.0 < result["confidence"] <= 0.95
    # It must NOT be the legacy fake constant 0.59.
    assert result["confidence"] != 0.59


def test_trqa_extractive_confidence_helper_no_signal_returns_none() -> None:
    assert _extractive_confidence(term_hits=0, domain_hits=0, question_terms=0, evidence_chars=120) is None
    assert _extractive_confidence(term_hits=0, domain_hits=0, question_terms=5, evidence_chars=120) is None


def test_trqa_extractive_confidence_helper_signal_returns_clamped_score() -> None:
    score = _extractive_confidence(term_hits=3, domain_hits=2, question_terms=3, evidence_chars=200)
    assert isinstance(score, float)
    assert 0.0 < score <= 0.95
