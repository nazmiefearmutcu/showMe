"""De-garbage regression tests for TSAR (Transcript Sentiment Analyzer).

The TSAR product claim (manifest seed) is: score a transcript with FinBERT
(and optional XSEN RoBERTa) and surface per-section / per-speaker / per-
utterance sentiment — dominant call tone, polarity by speaker role, and a
top-quote ladder. These tests construct the handler directly and assert the
real-data payload shape.

Model-dependent assertions are guarded: when FinBERT cannot load (offline /
weights missing) the handler returns status='ok' with a graceful neutral
(0.0) fallback and a finbert-unavailable warning rather than crashing — we
accept that shape too. The math (length-weighted rollups, hysteresis tone,
model-id-per-utterance) is asserted unconditionally because it runs purely on
the returned scores whatever their provenance.
"""

from __future__ import annotations

import math

import pytest

from showme.engine.functions.news.tsar import (
    TSARFunction,
    _dominant_tone,
    _weighted_mean,
)


_TRANSCRIPT = (
    "CEO: We grew revenue 20% year over year and beat our guidance handily. "
    "Demand is strong and our outlook is excellent.\n"
    "CFO: Operating margins expanded and free cash flow hit a record.\n"
    "Analyst: Margins look weak and the guidance is disappointing; I am worried "
    "about deteriorating demand and rising costs."
)

_OK_STATUSES = {"ok", "empty", "modeled", "not_configured", "no_text"}


@pytest.mark.asyncio
async def test_tsar_pasted_text_scores_real_utterances():
    fn = TSARFunction()
    res = await fn.execute(text=_TRANSCRIPT, models=["finbert"])
    data = res.data

    # Contract: the manifest output_contract.must_have keys are all present.
    for key in ("status", "summary", "speaker_rollups", "utterances"):
        assert key in data, f"missing must-have key {key!r}"
    assert data["status"] in _OK_STATUSES
    assert isinstance(data.get("methodology"), str) and data["methodology"]
    assert isinstance(data.get("field_dictionary"), dict) and data["field_dictionary"]

    utterances = data["utterances"]
    assert isinstance(utterances, list) and len(utterances) >= 3, utterances

    # Every utterance row carries a model id in the allowed set (provenance).
    for u in utterances:
        assert u["model"] in {"finbert", "xsen_roberta"}, u
        assert -1.0 <= float(u["score"]) <= 1.0
        assert u["sentiment"] in {"positive", "negative", "neutral"}
        assert u["role"] in {"management", "analyst", "operator"}

    # rows mirror utterances; data is real, not the old FTS "items" stub.
    assert data["rows"] == utterances
    assert "items" not in data


@pytest.mark.asyncio
async def test_tsar_speaker_rollups_are_length_weighted():
    fn = TSARFunction()
    res = await fn.execute(text=_TRANSCRIPT, models=["finbert"])
    data = res.data

    finbert_rows = [u for u in data["utterances"] if u["model"] == "finbert"]
    by_role: dict[str, list[dict]] = {}
    for u in finbert_rows:
        by_role.setdefault(u["role"], []).append(u)

    for rollup in data["speaker_rollups"]:
        role = rollup["role"]
        group = by_role[role]
        expected = _weighted_mean([(g["score"], g["len"]) for g in group])
        assert math.isclose(rollup["score"], round(expected, 4), abs_tol=1e-3), (
            role,
            rollup["score"],
            expected,
        )
        assert rollup["count"] == len(group)


def test_tsar_dominant_tone_uses_hysteresis_thresholds():
    # Pure-function check of the hysteresis band (+/-0.12).
    assert _dominant_tone(0.0) == "neutral"
    assert _dominant_tone(0.11) == "neutral"
    assert _dominant_tone(-0.11) == "neutral"
    assert _dominant_tone(0.12) == "positive"
    assert _dominant_tone(0.5) == "positive"
    assert _dominant_tone(-0.12) == "negative"
    assert _dominant_tone(-0.5) == "negative"


@pytest.mark.asyncio
async def test_tsar_summary_tone_matches_net_score():
    fn = TSARFunction()
    res = await fn.execute(text=_TRANSCRIPT, models=["finbert"])
    summary = res.data["summary"]
    net = summary["net_score"]
    tone = summary["dominant_tone"]
    if net >= 0.12:
        assert tone == "positive"
    elif net <= -0.12:
        assert tone == "negative"
    else:
        assert tone == "neutral"
    assert summary["utterance_count"] >= 3


@pytest.mark.asyncio
async def test_tsar_audio_without_whisper_returns_not_configured(monkeypatch):
    # Force Whisper to look unavailable so the audio path must degrade honestly.
    import showme.engine.functions.news.tsar as tsar_mod

    monkeypatch.setattr(tsar_mod, "_whisper_available", lambda: False)
    monkeypatch.setattr(tsar_mod, "_whisper_error", lambda: "whisper not installed")

    fn = TSARFunction()
    res = await fn.execute(audio_url="https://example.com/earnings.mp3", models=["finbert"])
    data = res.data

    assert data["status"] == "not_configured"
    assert data["data_mode"] == "not_configured"
    assert data["utterances"] == []
    assert data["summary"]["utterance_count"] == 0
    assert any("whisper" in str(a).lower() for a in data["next_actions"])


@pytest.mark.asyncio
async def test_tsar_no_input_returns_no_text():
    fn = TSARFunction()
    res = await fn.execute(models=["finbert"])
    data = res.data
    assert data["status"] == "no_text"
    assert data["utterances"] == []
    assert isinstance(data.get("methodology"), str) and data["methodology"]


@pytest.mark.asyncio
async def test_tsar_legacy_search_action_still_works():
    # Back-compat: the agent runtime calls TSAR with a bare query; it must not 500.
    fn = TSARFunction()
    res = await fn.execute(action="search", query="")
    # Empty query -> input_required (legacy shape), never a crash.
    assert res.data.get("status") == "input_required"
