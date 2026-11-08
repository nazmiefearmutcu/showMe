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
