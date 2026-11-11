"""TRQA#2 regression: the max_tokens_per_answer input must reach the LLM request.

Before the fix the LLM request hard-coded max_tokens=500 and the declared
input was ignored. These tests pin that the caller's cap is honoured (clamped to
the declared 64..2048 range) and that the seed default (512) applies when absent.

No network: the LLM router is replaced by an in-memory fake that records the
request it receives.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news.trqa import TRQAFunction

_TRANSCRIPT = (
    "Revenue for the quarter was 102.5 billion dollars, up 4 percent year over year. "
    "The company expects revenue growth to continue into the next quarter. "
    "Management flagged supply constraints as the main headwind for the period."
)


class _RecordingRouter:
    seen: list[Any] = []

    async def complete(self, req: Any) -> Any:
        type(self).seen.append(req)
        return types.SimpleNamespace(text="Revenue grew 4 percent.", model="fake-model", cost_usd=0.0,
                                     tokens_in=1, tokens_out=1)


@pytest.fixture
def recording_llm(monkeypatch: pytest.MonkeyPatch):
    _RecordingRouter.seen = []

    def _llm_request(**kwargs: Any) -> types.SimpleNamespace:
        return types.SimpleNamespace(**kwargs)

    fake_llm = types.SimpleNamespace(LLMRequest=_llm_request, LLMRouter=lambda: _RecordingRouter())
    monkeypatch.setitem(sys.modules, "showme.engine.agents.llm_router", fake_llm)
    return _RecordingRouter


def _run(**params: Any) -> None:
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    asyncio.run(TRQAFunction().execute(
        instrument=instrument,
        text=_TRANSCRIPT,
        questions=["What was the revenue?"],
        **params,
    ))


def test_caller_max_tokens_per_answer_reaches_llm_request(recording_llm) -> None:
    _run(max_tokens_per_answer=128)

    assert len(recording_llm.seen) == 1
    assert recording_llm.seen[0].max_tokens == 128


def test_max_tokens_per_answer_is_clamped_to_declared_range(recording_llm) -> None:
    _run(max_tokens_per_answer=99999)
    _run(max_tokens_per_answer=1)

    assert [req.max_tokens for req in recording_llm.seen] == [2048, 64]


def test_absent_max_tokens_per_answer_uses_seed_default(recording_llm) -> None:
    _run()

    assert recording_llm.seen[0].max_tokens == 512


def test_unparseable_max_tokens_per_answer_falls_back_to_default(recording_llm) -> None:
    _run(max_tokens_per_answer="not-a-number")

    assert recording_llm.seen[0].max_tokens == 512
