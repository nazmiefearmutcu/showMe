"""TRQA#1 regression: unsupported questions must say "not stated".

The SEC fallback is an 8-K Exhibit 99.1 press release, not an earnings-call
transcript. Before the fix, when no question term matched, the extractive
answer fell back to the first sentence of the document, and a weak partial
match was returned as a confident answer. A spin-off question on an AAPL
press release therefore returned the opening line of the release.

These tests pin:

* a question the document does not support returns the explicit
  "not stated in the document" answer with confidence None;
* a supported question still returns the evidence sentence with a real
  confidence;
* the SEC-sourced document is labelled ``press_release``.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import trqa as trqa_mod
from showme.engine.functions.news.trqa import TRQAFunction, _extractive_answer

_PRESS_RELEASE = (
    "Apple today announced financial results for its fiscal 2026 fourth quarter ended September 27, 2026. "
    "The Company posted quarterly revenue of $102.5 billion, up 4 percent year over year, and quarterly "
    "diluted earnings per share of $1.85. "
    "iPhone revenue was $52.1 billion and Services revenue set an all-time record of $28.4 billion. "
    "Apple's board of directors declared a regular quarterly cash dividend of $0.27 per share, payable in November. "
    "The Company repurchased $25 billion of its common stock during the quarter."
)


class _FailingRouter:
    """Forces the LLM path to degrade to the local extractive answer."""

    async def complete(self, _req):
        raise RuntimeError("no LLM configured in tests")


@pytest.fixture
def press_release_offline(monkeypatch):
    async def _fake_fetch(symbol, deps=None):
        return _PRESS_RELEASE, {"form": "8-K", "exhibit": "99.1", "symbol": symbol}

    monkeypatch.setattr(trqa_mod, "_fetch_transcript_text", _fake_fetch)
    fake_llm = types.SimpleNamespace(
        LLMRequest=lambda **kwargs: types.SimpleNamespace(**kwargs),
        LLMRouter=lambda: _FailingRouter(),
    )
    monkeypatch.setitem(sys.modules, "showme.engine.agents.llm_router", fake_llm)


def _run_sec(question: str):
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(TRQAFunction().execute(instrument=instrument, query=question))


def test_unsupported_question_is_not_answered_with_unrelated_sentence(press_release_offline) -> None:
    result = _run_sec("Did the company announce a spin-off?")
    answer = result.data["answers"][0]
    assert result.data["answer"] == "not stated in the document"
    assert answer["a"] == "not stated in the document"
    assert answer["confidence"] is None
    assert answer["stated"] is False


def test_supported_question_still_returns_evidence_with_real_confidence(press_release_offline) -> None:
    result = _run_sec("What was the quarterly revenue?")
    answer = result.data["answers"][0]
    assert answer["stated"] is True
    assert "quarterly revenue" in answer["a"].lower()
    assert isinstance(answer["confidence"], float)
    assert 0.0 < answer["confidence"] <= 0.95


def test_sec_fallback_is_labelled_press_release_not_transcript(press_release_offline) -> None:
    result = _run_sec("What was the quarterly revenue?")
    assert result.data["source"] == "sec_8k_ex99"
    assert result.data["document_type"] == "press_release"


def test_weak_partial_match_is_not_stated() -> None:
    text = "Apple today announced financial results. Revenue was strong across all regions."
    result = _extractive_answer(text, "Did the company announce a spin-off?")
    assert result["a"] == "not stated in the document"
    assert result["confidence"] is None
