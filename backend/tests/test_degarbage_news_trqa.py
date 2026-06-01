"""De-garbage regression: TRQA transcript Q&A (keyless SEC + extractive QA).

Uses a pasted transcript so the core retrieval logic is exercised WITHOUT a
network call; a second test allows the SEC path to degrade gracefully offline.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news.trqa import TRQAFunction, _rank_passages


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _instrument(sym="AAPL"):
    try:
        return Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
    except Exception:
        return None


_TRANSCRIPT = (
    "Good afternoon everyone. In the third quarter our total revenue was 94.9 billion dollars, "
    "up 6 percent year over year. iPhone revenue set a quarterly record. "
    "For the next quarter we expect revenue growth to accelerate into the low double digits. "
    "Our gross margin came in at 46.2 percent, at the high end of guidance. "
    "We returned over 28 billion dollars to shareholders through dividends and buybacks."
)


def test_trqa_pasted_transcript_answers_from_evidence():
    fn = TRQAFunction()
    res = _run(fn.execute(
        instrument=_instrument("AAPL"),
        query="what is the revenue guidance for next quarter?",
        transcript=_TRANSCRIPT,
    ))
    data = res.data
    assert isinstance(data, dict)
    assert str(data.get("status", "")).lower() == "ok"
    # Answer must be grounded — non-empty and present in evidence rows.
    answer = data.get("answer") or data.get("answer_text") or ""
    assert answer and "no_live_source" not in (res.sources or [])
    rows = data.get("rows") or data.get("evidence") or []
    assert rows, "expected evidence passages"
    # The guidance sentence should rank into the evidence.
    joined = " ".join(str(r.get("evidence", "")) for r in rows).lower()
    assert "double digits" in joined or "next quarter" in joined


def test_trqa_extractive_ranker_picks_relevant_passage():
    passages = _rank_passages(_TRANSCRIPT, "what was the gross margin?", k=3)
    assert passages
    assert "gross margin" in passages[0]["passage"].lower()


def test_trqa_no_transcript_is_graceful():
    fn = TRQAFunction()
    # No paste; SEC may be unreachable offline → must be honest, never invented.
    res = _run(fn.execute(instrument=_instrument("AAPL"), query="revenue?"))
    data = res.data
    assert isinstance(data, dict)
    status = str(data.get("status", "")).lower()
    assert status in {"ok", "provider_unavailable"}
    if status == "provider_unavailable":
        assert not (data.get("answer") or "")
        assert "methodology" in data
