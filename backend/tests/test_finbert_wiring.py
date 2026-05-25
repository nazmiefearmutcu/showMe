"""FinBERT wiring tests.

Pins the contracts the news handlers (TOP, NI, CN, INSTANT) rely on:

* Importing :mod:`showme.finbert_analyzer` MUST NOT load the model — the
  model load is ~300 MB and would dwarf pytest collection time.
* :func:`FinBertAnalyzer.label` correctly normalises the
  ``transformers`` pipeline output shape (list[list[dict]]) into the
  ``{label, score, score_signed, all_scores}`` envelope.
* :func:`FinBertAnalyzer.label_many` is length-preserving, neutral-stamps
  empty strings without invoking the underlying pipeline, and preserves
  positional alignment for non-empty inputs.
* :func:`stamp_items` mutates items in place, fills both ``sentiment``
  and ``sentiment_score``, and gracefully degrades to neutral stamps when
  the model can't load.

We never load the real ProsusAI/finbert model in CI — every test below
either checks lazy-load semantics or substitutes a deterministic stub via
the per-test singleton reset fixture.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# --- Helpers ----------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


class _StubPipeline:
    """Drop-in for transformers' pipeline output.

    Returns ``list[list[dict]]`` regardless of whether the caller passed
    a single string or a list — matches the contract `transformers`
    pipelines use when ``top_k=None``.
    """

    def __init__(self, label: str = "positive", score: float = 0.92) -> None:
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
    """Reset the FinBert singleton between tests so a stub doesn't leak."""
    from showme import finbert_analyzer

    finbert_analyzer.FinBertAnalyzer._instance = None
    yield
    finbert_analyzer.FinBertAnalyzer._instance = None


def _install_stub(label: str = "positive", score: float = 0.92):
    """Replace the singleton with a pre-built stub-backed analyzer."""
    from showme.finbert_analyzer import FinBertAnalyzer

    analyzer = FinBertAnalyzer.__new__(FinBertAnalyzer)
    analyzer._pipe = _StubPipeline(label=label, score=score)
    import threading

    analyzer._infer_lock = threading.Lock()
    FinBertAnalyzer._instance = analyzer
    return analyzer


# --- Lazy load --------------------------------------------------------------


def test_module_import_does_not_load_model():
    """The expensive transformers pipeline must NOT load on import."""
    from showme import finbert_analyzer

    assert finbert_analyzer.FinBertAnalyzer._instance is None


def test_instance_returns_singleton_with_stub():
    """Two `instance()` calls return the same object (stub-backed)."""
    a = _install_stub()
    from showme.finbert_analyzer import FinBertAnalyzer

    b = FinBertAnalyzer.instance()
    assert b is a


# --- Envelope normalisation -------------------------------------------------


def test_label_returns_canonical_envelope():
    _install_stub(label="positive", score=0.84)
    from showme.finbert_analyzer import FinBertAnalyzer

    result = _run(FinBertAnalyzer.instance().label("Apple beats earnings"))
    assert set(result.keys()) == {"label", "score", "score_signed", "all_scores"}
    assert result["label"] == "pos"
    assert result["score"] == pytest.approx(0.84)
    assert result["score_signed"] == pytest.approx(0.84)
    assert len(result["all_scores"]) == 3


def test_label_negative_signs_score_negative():
    _install_stub(label="negative", score=0.77)
    from showme.finbert_analyzer import FinBertAnalyzer

    result = _run(FinBertAnalyzer.instance().label("Bankruptcy filing announced"))
    assert result["label"] == "neg"
    assert result["score"] == pytest.approx(0.77)
    assert result["score_signed"] == pytest.approx(-0.77)


def test_label_handles_empty_text_without_pipeline_call():
    """Empty / whitespace text must short-circuit to the neutral envelope."""
    _install_stub(label="positive", score=0.99)
    from showme.finbert_analyzer import FinBertAnalyzer

    result = _run(FinBertAnalyzer.instance().label(""))
    assert result["label"] == "neu"
    assert result["score"] == 0.0
    assert result["score_signed"] == 0.0
    assert result["all_scores"] == []

    result2 = _run(FinBertAnalyzer.instance().label("   \n\t   "))
    assert result2["label"] == "neu"


# --- Batch alignment --------------------------------------------------------


def test_label_many_preserves_length_and_position():
    _install_stub(label="positive", score=0.9)
    from showme.finbert_analyzer import FinBertAnalyzer

    texts = ["Apple beats earnings", "", "Tesla cuts guidance", "  "]
    out = _run(FinBertAnalyzer.instance().label_many(texts))
    assert len(out) == len(texts)
    # Blanks get neutral-stamped without calling the pipeline.
    assert out[1]["label"] == "neu"
    assert out[3]["label"] == "neu"
    # Real entries get the stub's verdict.
    assert out[0]["label"] == "pos"
    assert out[2]["label"] == "pos"


def test_label_many_returns_all_neutral_when_every_input_is_blank():
    _install_stub()
    from showme.finbert_analyzer import FinBertAnalyzer

    out = _run(FinBertAnalyzer.instance().label_many(["", "  ", ""]))
    assert len(out) == 3
    assert all(r["label"] == "neu" and r["score"] == 0.0 for r in out)


def test_label_many_empty_list_returns_empty_list():
    _install_stub()
    from showme.finbert_analyzer import FinBertAnalyzer

    assert _run(FinBertAnalyzer.instance().label_many([])) == []


# --- stamp_items ------------------------------------------------------------


def test_stamp_items_fills_sentiment_and_score_in_place():
    _install_stub(label="positive", score=0.81)
    from showme.finbert_analyzer import stamp_items

    items = [
        {"title": "Fed cuts rates", "summary": "Powell speech"},
        {"title": "Earnings beat", "summary": "Q3 record"},
    ]
    out, warning = _run(stamp_items(items))
    assert warning is None
    assert out is items
    for item in items:
        # Long-form label per existing manifest contract.
        assert item["sentiment"] == "positive"
        assert item["sentiment_score"] == pytest.approx(0.81)
        assert item["sentiment_model"] == "finbert"
        assert isinstance(item["sentiment_all_scores"], list)


def test_stamp_items_preserves_existing_labels_by_default():
    """An item already carrying sentiment + sentiment_score is left alone."""
    _install_stub(label="positive", score=0.9)
    from showme.finbert_analyzer import stamp_items

    items = [
        {
            "title": "Already labelled",
            "sentiment": "negative",
            "sentiment_score": -0.42,
        },
        {"title": "Fresh row"},
    ]
    _, warning = _run(stamp_items(items))
    assert warning is None
    # First item kept its upstream label verbatim.
    assert items[0]["sentiment"] == "negative"
    assert items[0]["sentiment_score"] == pytest.approx(-0.42)
    # Second item got stamped.
    assert items[1]["sentiment"] == "positive"
    assert items[1]["sentiment_score"] == pytest.approx(0.9)


def test_stamp_items_overwrite_flag_replaces_existing():
    _install_stub(label="negative", score=0.7)
    from showme.finbert_analyzer import stamp_items

    items = [{"title": "Big news", "sentiment": "neutral", "sentiment_score": 0.0}]
    _, warning = _run(stamp_items(items, overwrite_existing=True))
    assert warning is None
    assert items[0]["sentiment"] == "negative"
    assert items[0]["sentiment_score"] == pytest.approx(-0.7)


def test_stamp_items_degrades_to_neutral_when_model_fails(monkeypatch):
    """Simulate a model load failure — every item must still get sentiment."""
    from showme import finbert_analyzer

    def _boom():
        raise RuntimeError("transformers wheel missing")

    monkeypatch.setattr(finbert_analyzer.FinBertAnalyzer, "instance", classmethod(lambda cls: _boom()))

    items = [{"title": "Headline A"}, {"title": "Headline B"}]
    out, warning = _run(finbert_analyzer.stamp_items(items))
    assert warning is not None
    assert "finbert unavailable" in warning
    assert out is items
    for item in items:
        assert item["sentiment"] == "neutral"
        assert item["sentiment_score"] == 0.0
        assert item["sentiment_model"] == "neutral_fallback"


def test_stamp_items_empty_list_is_noop():
    """No items → no work, no warning."""
    from showme.finbert_analyzer import stamp_items

    out, warning = _run(stamp_items([]))
    assert out == []
    assert warning is None


def test_stamp_items_skips_non_dict_rows():
    """Defensive: malformed list entries don't crash the pipeline."""
    _install_stub(label="positive", score=0.6)
    from showme.finbert_analyzer import stamp_items

    items: list = [{"title": "Real headline"}, "string_row", None]
    _, warning = _run(stamp_items(items))  # type: ignore[arg-type]
    assert warning is None
    assert items[0]["sentiment"] == "positive"
    # Non-dict rows untouched.
    assert items[1] == "string_row"
    assert items[2] is None


# --- Long-form label mapping ------------------------------------------------


def test_stamp_items_uses_long_form_labels_per_manifest_contract():
    """top_seed.py / cn_seed.py declare the field as `pos/neu/neg` short-form
    documentation but the live payload everywhere else in showMe uses the
    long form. We stamp the long form so the UI keeps rendering 'positive'
    instead of 'pos'.
    """
    from showme.finbert_analyzer import stamp_items

    for stub_label, expected in (
        ("positive", "positive"),
        ("negative", "negative"),
        ("neutral", "neutral"),
    ):
        _install_stub(label=stub_label, score=0.5)
        items = [{"title": "Some headline"}]
        _run(stamp_items(items))
        assert items[0]["sentiment"] == expected


# --- Handler integration ----------------------------------------------------


def test_top_handler_stamps_sentiment_on_each_item():
    """TOPFunction.execute must call stamp_items so every returned item
    carries `sentiment` + `sentiment_score`. We mock the rss data source
    to return two fixed articles, install a stub FinBERT, and assert the
    contract.
    """
    _install_stub(label="positive", score=0.88)

    from showme.engine.core.base_data_source import DataKind, DataRequest
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.news.top import TOPFunction

    class _FakeRss:
        async def fetch(self, request: DataRequest):
            assert request.kind == DataKind.NEWS
            return [
                {
                    "title": "Apple beats Q3 earnings expectations",
                    "summary": "Apple posted record revenue.",
                    "feed": "Bloomberg",
                    "url": "https://example.com/apple",
                    "published_at": "2026-05-24T12:00:00Z",
                },
                {
                    "title": "Tesla cuts guidance",
                    "summary": "Lower deliveries weighed on profit.",
                    "feed": "Reuters",
                    "url": "https://example.com/tesla",
                    "published_at": "2026-05-24T11:30:00Z",
                },
            ]

    deps = FunctionDeps()
    deps.rss = _FakeRss()
    result = _run(TOPFunction(deps).execute(symbol="AAPL", query="apple"))
    items = result.data["items"]
    assert items, "TOP returned no items — fixture did not flow through"
    for item in items:
        assert "sentiment" in item, "TOP must stamp sentiment on every item"
        assert "sentiment_score" in item
        assert item["sentiment"] in {"positive", "negative", "neutral"}
        assert -1.0 <= item["sentiment_score"] <= 1.0
        assert item["sentiment_model"] == "finbert"
    assert result.metadata["sentiment_model"] == "finbert"


def test_instant_route_stamps_sentiment_on_events(monkeypatch):
    """The /api/instant/events route post-processes events through FinBERT."""
    _install_stub(label="negative", score=0.74)

    from showme import instant_line
    from showme.server_routes import instant as instant_routes

    async def _fake_instant_events(limit: int = 100):
        return {
            "ok": True,
            "mode": "secondary",
            "events": [
                {
                    "id": 1,
                    "title": "Major exchange hack reported",
                    "summary": "Hot wallet drained, withdrawals frozen.",
                    "source_id": "rss_breaking",
                    "published_at": "2026-05-24T08:00:00Z",
                },
                {
                    "id": 2,
                    "title": "Tesla up 4% pre-market",
                    "summary": "Solid delivery numbers.",
                    "source_id": "rss_breaking",
                    "published_at": "2026-05-24T07:30:00Z",
                },
            ],
        }

    monkeypatch.setattr(instant_line, "instant_events", _fake_instant_events)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    instant_routes.register(app, deps=None)  # type: ignore[arg-type]
    client = TestClient(app)
    response = client.get("/api/instant/events", params={"limit": 50})
    assert response.status_code == 200
    payload = response.json()
    events = payload["events"]
    assert events
    for event in events:
        assert event["sentiment"] in {"positive", "negative", "neutral"}
        assert "sentiment_score" in event
        assert event["sentiment_model"] == "finbert"
