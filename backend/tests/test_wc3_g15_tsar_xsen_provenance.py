"""wc3-g15 TSAR#2 follow-up: an XSEN-only reading is a model reading, never live.

When FinBERT fails and XSEN_RoBERTa scores the transcript, the reading is a model
output over pasted text. The source name must classify as a model so the
sanitizer's data_state is not 'live'. Network-free: the analyzers are patched.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme import server  # noqa: E402
from showme.engine.functions.news.tsar import TSARFunction  # noqa: E402

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


class _StubXsen:
    @staticmethod
    def instance():
        return _StubXsen()

    def classify(self, texts):
        return [{"sentiment": "positive", "sentiment_score": 0.8} for _ in texts]


def _run(coro):
    return asyncio.run(coro)


def test_xsen_only_reading_is_labelled_model_not_live(monkeypatch):
    import showme.finbert_analyzer as fb
    import showme.x_analysis as xa

    monkeypatch.setattr(fb.FinBertAnalyzer, "instance", _BrokenFinbert.instance)
    monkeypatch.setattr(xa.XAnalyzer, "instance", _StubXsen.instance)
    res = _run(TSARFunction().execute(
        text=_TRANSCRIPT, models=["finbert", "xsen_roberta"]
    ))
    assert res.data["data_mode"] == "modeled", res.data["data_mode"]

    payload = server.enforce_live_or_label_synthetic("TSAR", {}, res.to_dict())
    assert payload["data_state"] != "live", payload["data_state"]
    assert payload["data_state"] == "model", payload["data_state"]


def test_xsen_source_name_classifies_as_model():
    assert server._classify_source_state("xsen_roberta_model") == "model"
