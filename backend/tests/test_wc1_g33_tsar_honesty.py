"""wc1-g33 honesty regression: TSAR#2 (a failed sentiment model must not
produce a neutral reading).

Network-free. The FinBERT and XSEN analyzers are patched.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.functions.news.tsar import TSARFunction  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── TSAR#2 ────────────────────────────────────────────────────────────────

_TRANSCRIPT = (
    "CEO: We grew revenue 20% year over year and beat our guidance handily. "
    "Demand is strong and our outlook is excellent.\n"
    "Analyst: Margins look weak and the guidance is disappointing; I am worried "
    "about deteriorating demand."
)


class _BrokenFinbert:
    @staticmethod
    def instance():
        raise RuntimeError("weights missing")


class _StubFinbert:
    def __init__(self, score: float) -> None:
        self._score = score

    async def label_many(self, texts):
        return [{"score_signed": self._score} for _ in texts]

    @staticmethod
    def instance():
        return _StubFinbert(0.5)


class _BrokenXsen:
    @staticmethod
    def instance():
        raise RuntimeError("xsen weights missing")


def test_finbert_failure_emits_no_neutral_reading(monkeypatch):
    import showme.finbert_analyzer as fb
    import showme.x_analysis as xa

    monkeypatch.setattr(fb.FinBertAnalyzer, "instance", _BrokenFinbert.instance)
    res = _run(TSARFunction().execute(text=_TRANSCRIPT, models=["finbert"]))
    data = res.data

    assert data["status"] == "provider_unavailable", data["status"]
    assert data["utterances"] == []
    assert data["rows"] == []
    assert data["summary"]["net_score"] is None
    assert data["summary"]["dominant_tone"] is None
    assert data["summary"]["utterance_count"] == 0
    assert "finbert" not in res.sources
    assert any("finbert" in w for w in res.warnings)
    assert data["cards"]["net_score"] is None


def test_xsen_failure_adds_no_zero_rows(monkeypatch):
    import showme.finbert_analyzer as fb
    import showme.x_analysis as xa

    monkeypatch.setattr(fb.FinBertAnalyzer, "instance", _StubFinbert.instance)
    monkeypatch.setattr(xa.XAnalyzer, "instance", _BrokenXsen.instance)
    res = _run(TSARFunction().execute(
        text=_TRANSCRIPT, models=["finbert", "xsen_roberta"]
    ))
    data = res.data

    models = {u["model"] for u in data["utterances"]}
    assert models == {"finbert"}, models
    assert all(u["score"] == 0.5 for u in data["utterances"])
    assert "xsen_roberta" not in res.sources
    assert any("xsen" in w for w in res.warnings)
    # the FinBERT pass is still the canonical reading
    assert data["summary"]["net_score"] == 0.5
    assert data["status"] == "ok"


def test_no_text_summary_carries_no_neutral_score():
    res = _run(TSARFunction().execute(models=["finbert"]))
    assert res.data["status"] == "no_text"
    assert res.data["summary"]["net_score"] is None
    assert res.data["summary"]["dominant_tone"] is None


# ── TSAR#2 review follow-up: a signed label with no confidence is not neutral ──


def test_xsen_label_without_confidence_is_not_a_zero_reading():
    from showme.engine.functions.news.tsar import _xsen_signed

    assert _xsen_signed({"sentiment": "positive"}) is None
    assert _xsen_signed({"sentiment": "negative"}) is None
    # A neutral label is a genuine neutral reading, not a missing one.
    assert _xsen_signed({"sentiment": "neutral"}) == 0.0


# ── TSAR#3 review follow-up: a no-text envelope is not a live reading ──


def test_no_text_envelope_is_not_labelled_live_and_status_is_empty():
    from showme import server
    from showme.function_contracts import normalize_function_contract

    res = _run(TSARFunction().execute(models=["finbert"]))
    assert res.data["status"] == "no_text"

    payload = server.enforce_live_or_label_synthetic("TSAR", {}, res.to_dict())
    assert payload["data_state"] != "live", payload["data_state"]

    envelope = normalize_function_contract("TSAR", {}, res.to_dict())
    assert envelope["status"] == "empty", envelope["status"]


# ── TSAR#2 review follow-up: model_set names only the models that scored ──


class _StubXsen:
    @staticmethod
    def instance():
        return _StubXsen()

    def classify(self, texts):
        return [{"sentiment": "positive", "sentiment_score": 0.8} for _ in texts]


def test_model_set_lists_only_models_that_produced_rows(monkeypatch):
    """FinBERT failed and XSEN carried the reading: model_set must not still name finbert."""
    import showme.finbert_analyzer as fb
    import showme.x_analysis as xa

    monkeypatch.setattr(fb.FinBertAnalyzer, "instance", _BrokenFinbert.instance)
    monkeypatch.setattr(xa.XAnalyzer, "instance", _StubXsen.instance)
    res = _run(TSARFunction().execute(
        text=_TRANSCRIPT, models=["finbert", "xsen_roberta"]
    ))
    data = res.data

    assert {u["model"] for u in data["utterances"]} == {"xsen_roberta"}
    assert data["summary"]["model_set"] == ["xsen_roberta"], data["summary"]["model_set"]
    assert data["cards"]["model_set"] == "xsen_roberta", data["cards"]["model_set"]
    assert data["summary"]["net_score"] == 0.8
    assert data["data_mode"] == "modeled"
    assert data["status"] == "ok"


def test_model_set_keeps_every_model_when_all_score(monkeypatch):
    import showme.finbert_analyzer as fb
    import showme.x_analysis as xa

    monkeypatch.setattr(fb.FinBertAnalyzer, "instance", _StubFinbert.instance)
    monkeypatch.setattr(xa.XAnalyzer, "instance", _StubXsen.instance)
    res = _run(TSARFunction().execute(
        text=_TRANSCRIPT, models=["finbert", "xsen_roberta"]
    ))
    assert res.data["summary"]["model_set"] == ["finbert", "xsen_roberta"]
    assert res.data["cards"]["model_set"] == "finbert, xsen_roberta"
