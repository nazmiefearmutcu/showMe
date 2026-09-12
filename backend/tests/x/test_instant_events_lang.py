"""C9/C3-Q15 i18n regression — /api/x/instant_events must be language-aware.

Commission round-2 (`commission/round2/c3-answers.md`, Q15) found that the
INSTANT summary event hardcoded the Turkish ``summary_tr`` as both its
``summary`` and ``generated_summary`` regardless of the request ``lang``,
so the INSTANT pane — which renders ``generated_summary ?? summary``
(`ui/src/functions/INSTANT.tsx:930`) and speaks the same field
(`INSTANT.tsx:196`) — showed Turkish copy on an English UI.

Contract pinned here:

* no ``lang`` (route default "en") and ``lang=en`` → English summary text;
* ``lang=tr`` → Turkish text (explicit opt-in);
* the event still carries ``summary_tr`` for legacy consumers, and the
  top-level payload exposes both ``summary`` (language-picked) and
  ``summary_tr`` so no caller loses a field it relied on.
"""
from __future__ import annotations

from typing import Any

import pytest

from showme import x_analysis

SUMMARY_EN = "For 'AAPL', the dominant view across the latest 12 posts is bullish."
SUMMARY_TR = "'AAPL' için son 12 paylaşımda baskın görüş olumlu / boğa."


def _full_result(lang: str | None) -> dict[str, Any]:
    """Aggregate shape as ``_aggregate`` emits it: language-picked
    ``summary`` plus both concrete variants."""
    normalized = (lang or "en").strip().lower()
    return {
        "query": "AAPL",
        "post_count": 12,
        "scrape_seconds": 1.25,
        "summary": SUMMARY_EN if normalized.startswith("en") else SUMMARY_TR,
        "summary_en": SUMMARY_EN,
        "summary_tr": SUMMARY_TR,
        "mood": "bullish",
        "scores": {
            "bullish_score_avg": 0.4,
            "bullish_score_engagement_weighted": 0.42,
            "confidence": 0.8,
        },
        "distributions": {
            "sentiment_pct": {"positive": 60},
            "emotion_pct": {},
            "topic_pct": {},
        },
        "dominant": {"sentiment": "positive", "emotion": "joy", "topic": "markets"},
        # No per-tweet events → the language-aware summary event is the only
        # event, which keeps these assertions deterministic.
        "examples": {},
    }


def _install_analyzer(monkeypatch: pytest.MonkeyPatch) -> x_analysis.XAnalyzer:
    """Real XAnalyzer with its (model-backed) analyze_topic stubbed out."""
    analyzer = x_analysis.XAnalyzer()
    captured: dict[str, Any] = {}

    def _fake_analyze_topic(
        query: str,
        limit: int = 60,
        since: str | None = None,
        until: str | None = None,
        lang: str | None = None,
    ) -> dict[str, Any]:
        captured["lang"] = lang
        captured["query"] = query
        return _full_result(lang)

    monkeypatch.setattr(analyzer, "analyze_topic", _fake_analyze_topic)
    monkeypatch.setattr(
        x_analysis.XAnalyzer,
        "instance",
        classmethod(lambda cls: analyzer),
    )
    return analyzer


def _summary_event(payload: dict[str, Any]) -> dict[str, Any]:
    return next(
        event
        for event in payload["events"]
        if str(event.get("dedupe_key", "")).startswith("x-summary::")
    )


# ── direct method contract ────────────────────────────────────────────────


def test_summary_event_is_english_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    analyzer = _install_analyzer(monkeypatch)
    payload = analyzer.analyze_topic_as_instant_events(symbol="AAPL")
    assert payload["ok"] is True
    event = _summary_event(payload)
    # The language-picked summary is the primary text — never the hardcoded TR.
    assert event["summary"] == SUMMARY_EN
    assert event["generated_summary"] == SUMMARY_EN
    # Legacy Turkish text stays present on the event for tr consumers.
    assert event["summary_tr"] == SUMMARY_TR
    # Top-level aliases: summary language-picked, summary_tr still present.
    assert payload["summary"] == SUMMARY_EN
    assert payload["summary_tr"] == SUMMARY_TR


def test_summary_event_follows_explicit_tr_lang(monkeypatch: pytest.MonkeyPatch) -> None:
    analyzer = _install_analyzer(monkeypatch)
    payload = analyzer.analyze_topic_as_instant_events(symbol="AAPL", lang="tr")
    assert payload["ok"] is True
    event = _summary_event(payload)
    assert event["summary"] == SUMMARY_TR
    assert event["generated_summary"] == SUMMARY_TR
    assert event["summary_tr"] == SUMMARY_TR
    assert payload["summary"] == SUMMARY_TR


def test_empty_lang_falls_back_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    """`?lang=` (empty) must not fall through to the legacy TR default."""
    analyzer = _install_analyzer(monkeypatch)
    payload = analyzer.analyze_topic_as_instant_events(symbol="AAPL", lang="")
    assert payload["ok"] is True
    assert _summary_event(payload)["summary"] == SUMMARY_EN


def test_insufficient_path_keeps_summary_tr_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The degraded shape must not lose `summary_tr` (existing consumers)."""
    analyzer = x_analysis.XAnalyzer()
    monkeypatch.setattr(
        analyzer,
        "analyze_topic",
        lambda **kw: {
            "query": "AAPL",
            "post_count": 2,
            "verdict": "insufficient_data",
            "warning": "few",
        },
    )
    payload = analyzer.analyze_topic_as_instant_events(symbol="AAPL")
    assert payload["ok"] is False
    assert "summary_tr" in payload
    assert "summary" in payload


# ── route contract (lang plumbing + default) ──────────────────────────────


@pytest.fixture
def x_client(monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from showme.server_routes import xai as xai_routes

    _install_analyzer(monkeypatch)
    app = FastAPI()
    xai_routes.register(app, deps=None)  # type: ignore[arg-type]
    with TestClient(app) as client:
        yield client


def test_route_defaults_to_en(x_client) -> None:
    response = x_client.get("/api/x/instant_events", params={"symbol": "AAPL"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    event = _summary_event(payload)
    assert event["summary"] == SUMMARY_EN
    assert event["generated_summary"] == SUMMARY_EN


def test_route_honors_lang_en(x_client) -> None:
    response = x_client.get(
        "/api/x/instant_events", params={"symbol": "AAPL", "lang": "en"}
    )
    assert response.status_code == 200, response.text
    event = _summary_event(response.json())
    assert event["summary"] == SUMMARY_EN
    assert event["generated_summary"] == SUMMARY_EN


def test_route_honors_lang_tr(x_client) -> None:
    response = x_client.get(
        "/api/x/instant_events", params={"symbol": "AAPL", "lang": "tr"}
    )
    assert response.status_code == 200, response.text
    event = _summary_event(response.json())
    assert event["summary"] == SUMMARY_TR
    assert event["generated_summary"] == SUMMARY_TR
