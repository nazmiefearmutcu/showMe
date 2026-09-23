"""Contrarian-corrector tests.

Pins the neg→pos correction contract layered on FinBERT
(``showme.contrarian.correct_direction``, wired into ``stamp_items``):

* bottom-call headlines ("cycle bottom may already be in at $56K") and
  fear-pivot headlines ("braced for a total wipeout but Bitcoin had
  other plans") flip from FinBERT's neg verdict to pos, with a
  ``sentiment_score`` that clears the UI bull bucket (>= +0.5);
* genuine negative headlines pass through untouched — the corrector
  never widens the bear bucket, only repairs false negatives;
* pos / neu rows are NEVER touched (a flip can only ever remove a
  negative read, never create one);
* corrected rows are visibly stamped — ``sentiment_model``
  "finbert+contrarian" plus a ``sentiment_note`` — while untouched rows
  keep plain "finbert" and carry no note.

Same stub discipline as ``test_finbert_wiring.py``: the real
ProsusAI/finbert weights are never loaded in CI.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# --- Helpers (mirrors test_finbert_wiring.py) --------------------------------


def _run(coro):
    return asyncio.run(coro)


class _StubPipeline:
    """Returns list[list[dict]] for any input, like transformers top_k=None."""

    def __init__(self, label: str = "negative", score: float = 0.92) -> None:
        self._label = label
        self._score = score

    def _payload_for_one(self) -> list[dict[str, object]]:
        other = (1.0 - self._score) / 2.0
        return [
            {"label": self._label, "score": self._score},
            {"label": "neutral", "score": other},
            {"label": "negative" if self._label != "negative" else "positive", "score": other},
        ]

    def __call__(self, x):
        if isinstance(x, list):
            return [self._payload_for_one() for _ in x]
        return [self._payload_for_one()]


@pytest.fixture(autouse=True)
def _reset_singleton():
    from showme import finbert_analyzer

    finbert_analyzer.FinBertAnalyzer._instance = None
    yield
    finbert_analyzer.FinBertAnalyzer._instance = None


def _install_stub(label: str = "negative", score: float = 0.92):
    from showme.finbert_analyzer import FinBertAnalyzer

    analyzer = FinBertAnalyzer.__new__(FinBertAnalyzer)
    analyzer._pipe = _StubPipeline(label=label, score=score)
    analyzer._infer_lock = threading.Lock()
    FinBertAnalyzer._instance = analyzer
    return analyzer


# --- Unit level: correct_direction -------------------------------------------


def _env(label: str, score: float) -> dict:
    return {
        "label": label,
        "score": score,
        "score_signed": score if label == "pos" else (-score if label == "neg" else 0.0),
        "all_scores": [],
    }


def test_bottom_call_headline_flips_neg_to_pos():
    """The exact headline from the CN pane bug report: bear-listed although
    its thesis ("the bottom is already in") is bullish."""
    from showme.contrarian import correct_direction

    text = "Bitcoin cycle bottom may already be in at $56K, says analyst James Check"
    flipped, note = correct_direction(text, _env("neg", 0.83))
    assert flipped["label"] == "pos"
    assert flipped["score_signed"] == pytest.approx(0.83)
    assert note == "contrarian bottom-call"


def test_fear_pivot_headline_flips_neg_to_pos():
    from showme.contrarian import correct_direction

    text = "Crypto traders braced for a total wipeout this week but Bitcoin had other plans"
    flipped, note = correct_direction(text, _env("neg", 0.9))
    assert flipped["label"] == "pos"
    assert note == "contrarian fear-pivot"


def test_flip_floor_reaches_ui_bull_bucket():
    """Low-confidence neg verdicts still flip to a score that clears the
    NI bull bucket (>= +0.5); high-confidence ones keep their magnitude."""
    from showme.contrarian import correct_direction

    flipped, _ = correct_direction("Bitcoin has bottomed", _env("neg", 0.51))
    assert flipped["score_signed"] >= 0.6
    assert flipped["score_signed"] == pytest.approx(0.6)

    flipped_hi, _ = correct_direction("Bitcoin has bottomed", _env("neg", 0.95))
    assert flipped_hi["score_signed"] == pytest.approx(0.95)


def test_genuine_negative_passes_through_untouched():
    """Real bear headline from the same pane — must stay raw FinBERT neg."""
    from showme.contrarian import correct_direction

    text = (
        "Corporate treasuries bought just 5,901 bitcoin in 3 months. "
        "Other demand signals look weak, too."
    )
    result, note = correct_direction(text, _env("neg", 0.77))
    assert result["label"] == "neg"
    assert result["score_signed"] == pytest.approx(-0.77)
    assert note is None


def test_bottom_anticipation_is_not_a_completed_bottom():
    """"Searching for a bottom" / "bottom is near" still expect downside —
    only completed-bottom claims may flip."""
    from showme.contrarian import correct_direction

    for text in (
        "Bitcoin still searching for a bottom as sell pressure persists",
        "Analyst: BTC bottom is near, more pain first",
    ):
        result, note = correct_direction(text, _env("neg", 0.8))
        assert result["label"] == "neg", text
        assert note is None, text


def test_pos_and_neu_rows_are_never_touched():
    """A flip can only ever remove a negative read, never create one."""
    from showme.contrarian import correct_direction

    text = "Bitcoin has bottomed"
    result, note = correct_direction(text, _env("pos", 0.9))
    assert result["label"] == "pos"
    assert note is None

    result_neu, note_neu = correct_direction(text, _env("neu", 0.0))
    assert result_neu["label"] == "neu"
    assert note_neu is None


def test_empty_text_is_noop():
    from showme.contrarian import correct_direction

    result, note = correct_direction("", _env("neg", 0.9))
    assert result["label"] == "neg"
    assert note is None


# --- stamp_items integration -------------------------------------------------


def test_stamp_items_flips_and_stamps_provenance():
    _install_stub(label="negative", score=0.83)
    from showme.finbert_analyzer import stamp_items

    items = [
        {
            "title": "Bitcoin cycle bottom may already be in at $56K, says analyst James Check",
            "summary": "The analyst argues the drawdown is over.",
        },
        {
            "title": "Corporate treasuries bought just 5,901 bitcoin in 3 months",
            "summary": "Other demand signals look weak, too.",
        },
    ]
    _, warning = _run(stamp_items(items))
    assert warning is None

    corrected, genuine = items
    assert corrected["sentiment"] == "positive"
    assert corrected["sentiment_score"] >= 0.5, "flip must land in the UI bull bucket"
    assert corrected["sentiment_model"] == "finbert+contrarian"
    assert corrected["sentiment_note"] == "contrarian bottom-call"

    assert genuine["sentiment"] == "negative"
    assert genuine["sentiment_score"] == pytest.approx(-0.83)
    assert genuine["sentiment_model"] == "finbert"
    assert "sentiment_note" not in genuine


def test_stamp_items_neutral_fallback_never_flips(monkeypatch):
    """On a model-load failure everything is neutral-stamped — the
    corrector must not turn fallback rows into positives."""
    from showme import finbert_analyzer

    def _boom():
        raise RuntimeError("transformers wheel missing")

    monkeypatch.setattr(
        finbert_analyzer.FinBertAnalyzer,
        "instance",
        classmethod(lambda cls: _boom()),
    )

    items = [{"title": "Bitcoin has bottomed, says analyst"}]
    out, warning = _run(finbert_analyzer.stamp_items(items))
    assert warning is not None
    assert out[0]["sentiment"] == "neutral"
    assert out[0]["sentiment_model"] == "neutral_fallback"
    assert "sentiment_note" not in out[0]
