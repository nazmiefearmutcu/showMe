"""TRQA#1-RQ regression: the wording must cover press releases, and LLM not-stated answers are not evidence.

The SEC fallback is an 8-K Exhibit 99.1 press release. Before the fix the
function name, the no-source reason and the evidence field description still
described an earnings-call transcript, and an LLM answer such as "the document
does not mention a spin-off" was marked stated=True and shown with evidence rows.

No network: the SEC helper and the LLM router are replaced by in-memory fakes.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import trqa as trqa_mod
from showme.engine.functions.news.trqa import TRQAFunction

_PRESS_RELEASE = (
    "Apple today announced financial results for its fiscal 2026 fourth quarter ended September 27, 2026. "
    "The Company posted quarterly revenue of $102.5 billion, up 4 percent year over year, and quarterly "
    "diluted earnings per share of $1.85. "
    "iPhone revenue was $52.1 billion and Services revenue set an all-time record of $28.4 billion. "
    "The Company repurchased $25 billion of its common stock during the quarter."
)


class _ScriptedRouter:
    reply = ""

    async def complete(self, _req: Any) -> Any:
        return types.SimpleNamespace(text=type(self).reply, model="fake-model", cost_usd=0.0,
                                     tokens_in=1, tokens_out=1)


def _install_llm(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    _ScriptedRouter.reply = reply
    fake_llm = types.SimpleNamespace(
        LLMRequest=lambda **kwargs: types.SimpleNamespace(**kwargs),
        LLMRouter=lambda: _ScriptedRouter(),
    )
    monkeypatch.setitem(sys.modules, "showme.engine.agents.llm_router", fake_llm)


def _press_release_source(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fetch(symbol, deps=None):
        return _PRESS_RELEASE, {"form": "8-K", "exhibit": "99.1", "symbol": symbol}

    monkeypatch.setattr(trqa_mod, "_fetch_transcript_text", _fake_fetch)


def _no_source(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fetch(symbol, deps=None):
        return "", None

    monkeypatch.setattr(trqa_mod, "_fetch_transcript_text", _fake_fetch)


def _run(question: str = "Did the company announce a spin-off?"):
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(TRQAFunction().execute(instrument=instrument, query=question))


def test_function_name_and_description_cover_press_releases() -> None:
    assert "press release" in TRQAFunction.description.lower()
    assert "press release" in TRQAFunction.name.lower()


def test_no_source_reason_does_not_claim_no_transcript_was_found_for_a_press_release_fallback(monkeypatch) -> None:
    _no_source(monkeypatch)
    result = _run()

    assert result.data["status"] == "provider_unavailable"
    assert "No earnings transcript found" not in result.data["reason"]
    assert "press release" in result.data["reason"].lower()


def test_evidence_field_description_is_not_transcript_only() -> None:
    assert "Transcript passages" not in trqa_mod._FIELD_DICT["evidence"]
    assert "press release" in trqa_mod._FIELD_DICT["evidence"].lower()


@pytest.mark.parametrize(
    "reply",
    [
        "The document does not mention a spin-off.",
        "The press release doesn't say anything about a spin-off.",
        "There is no mention of a spin-off in the document.",
        "Not stated in the document.",
    ],
)
def test_llm_not_stated_answer_carries_no_evidence_rows(monkeypatch, reply: str) -> None:
    _press_release_source(monkeypatch)
    _install_llm(monkeypatch, reply)
    result = _run()

    answer = result.data["answers"][0]
    assert answer["model"] == "fake-model"
    assert answer["stated"] is False, reply
    assert result.data["rows"] == []
    assert result.data["evidence"] == []


def test_llm_supported_answer_stays_stated_with_evidence(monkeypatch) -> None:
    _press_release_source(monkeypatch)
    _install_llm(monkeypatch, "Quarterly revenue was $102.5 billion, up 4 percent year over year.")
    result = _run("What was the quarterly revenue?")

    answer = result.data["answers"][0]
    assert answer["stated"] is True
    assert result.data["rows"], "a supported LLM answer keeps its evidence rows"


@pytest.mark.parametrize("text", ["Revenue was $102.5 billion.", "Quarterly revenue rose 4 percent."])
def test_not_stated_detector_does_not_flag_supported_statements(text: str) -> None:
    from showme.engine.functions.news import trqa as mod

    assert mod._is_not_stated_answer(text) is False


@pytest.mark.parametrize("text", ["Not stated in the document", "The filing does not mention a buyback."])
def test_not_stated_detector_flags_negative_statements(text: str) -> None:
    from showme.engine.functions.news import trqa as mod

    assert mod._is_not_stated_answer(text) is True
