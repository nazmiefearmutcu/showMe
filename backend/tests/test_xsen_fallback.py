"""Route-level XSEN Stocktwits fallback (2026-09-15).

The X scraper chain is dead on this host (search engines blocked, model
bundle missing) and ``/api/x/analyze`` answered 503 / "No posts found" while
a live source sat one call away: Stocktwits' public author-tagged
Bullish/Bearish stream. Pins the route contract:

* FileNotFoundError (model missing) + ticker query → 200 Stocktwits payload;
* ``post_count == 0`` / ``verdict == "insufficient_data"`` + ticker → same;
* free text ("solar stocks") never rides the fallback — it keeps the honest
  X empty/503 path unchanged;
* fallback failure keeps the legacy 503 / empty payload untouched;
* a cooling circuit breaker skips the dead X attempt entirely (tickers go
  straight to the fallback, free text gets the empty payload without wait).

``XAnalyzer.analyze_topic`` itself is untouched — its zero-post behaviour is
pinned by ``tests/x/test_bughunt_2026_05_24.py``.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from showme import server

_CHIP: dict = {
    "symbol": "AAPL",
    "ok": True,
    "source": "stocktwits",
    "stocktwits_symbol": "AAPL",
    "post_count": 12,
    "messages_scanned": 40,
    "mood": "bullish",
    "summary": "Stocktwits: 12 labelled posts of the latest 40 (8 bullish / 4 bearish).",
    "summary_tr": "Stocktwits: son 40 gönderinin 12'si etiketli.",
    "bullish_score": 0.5,
    "confidence": 0.6,
    "dominant": {"sentiment": "bullish", "emotion": "", "topic": ""},
    "distributions": {
        "sentiment_pct": {"bullish": 66.7, "bearish": 33.3},
        "emotion_pct": {},
        "topic_pct": {},
    },
    "examples": {
        "bullish": [
            {
                "user": "stubber",
                "text": "AAPL to the moon",
                "likes": 7,
                "retweets": 0,
                "url": "https://stocktwits.com/stubber/message/1",
                "score": 1.0,
                "emotion": "",
                "topic": "",
                "date": "2026-09-15T12:00:00Z",
            }
        ],
        "bearish": [],
    },
    "fetched_at": "2026-09-15T12:00:00+00:00",
    "methodology": "Author-labelled Bullish/Bearish tags.",
}


@pytest.fixture
def app(tmp_path_factory: pytest.TempPathFactory):
    home = tmp_path_factory.mktemp("xsen-fallback-home")
    os.environ["SHOWME_HOME"] = str(home)
    return server.build_app(engine_root=None)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_x_breaker():
    from showme import x_analysis

    x_analysis._reset_x_chain_breaker()
    yield
    x_analysis._reset_x_chain_breaker()


def _stub_chip(monkeypatch: pytest.MonkeyPatch, result: dict | None) -> list[str]:
    """Patch the route module's imported ``fetch_symbol_chip``; log calls."""
    from showme.server_routes import xai

    calls: list[str] = []

    def fake_fetch(symbol: str, *, timeout=None, cache_ttl=None):
        calls.append(symbol)
        return None if result is None else dict(result)

    monkeypatch.setattr(xai, "fetch_symbol_chip", fake_fetch)
    return calls


def _patch_analyze(monkeypatch: pytest.MonkeyPatch, fn) -> None:
    from showme import x_analysis

    monkeypatch.setattr(x_analysis.XAnalyzer.instance(), "analyze_topic", fn)


def _raise_missing(query, limit, since, until, lang):
    raise FileNotFoundError("X sentiment model not found")


def _empty(query, limit, since, until, lang):
    return {
        "query": query,
        "post_count": 0,
        "warning": "no posts returned by any scraper backend",
    }


def test_missing_model_falls_back_to_stocktwits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FileNotFoundError (model bundle missing) → live Stocktwits payload."""
    from showme import x_analysis

    _patch_analyze(monkeypatch, _raise_missing)
    calls = _stub_chip(monkeypatch, _CHIP)

    r = client.post("/api/x/analyze", json={"query": "AAPL"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "stocktwits"
    assert body["device"] == "stocktwits"
    assert body["query"] == "AAPL"
    assert body["post_count"] == 12
    assert body["mood"] == "bullish"
    assert body["scores"]["bullish_score_avg"] == 0.5
    assert body["scores"]["bullish_score_engagement_weighted"] == 0.5
    assert body["scores"]["confidence"] == 0.6
    assert body["distributions"]["sentiment_pct"] == {"bullish": 66.7, "bearish": 33.3}
    assert body["dominant"] == {"sentiment": "bullish", "emotion": "", "topic": ""}
    assert body["examples"] == _CHIP["examples"]
    assert body["summary"] == _CHIP["summary"]
    assert body["summary_en"] == _CHIP["summary"]
    assert body["summary_tr"] == _CHIP["summary_tr"]
    assert body["fetched_at"] == _CHIP["fetched_at"]
    assert isinstance(body["scrape_seconds"], (int, float))
    assert "Stocktwits" in body["warning"]
    # The fallback must not pretend an X verdict exists.
    assert "verdict" not in body
    assert calls == ["AAPL"]
    # The dead model cools the chain so the next refresh takes the fast path.
    assert x_analysis._x_chain_available() is False


def test_zero_post_result_falls_back_to_stocktwits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty X result (all scrapers down) → live Stocktwits payload."""
    from showme import x_analysis

    _patch_analyze(monkeypatch, _empty)
    calls = _stub_chip(monkeypatch, _CHIP)

    r = client.post("/api/x/analyze", json={"symbol": "AAPL"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "stocktwits"
    assert body["post_count"] == 12
    assert calls == ["AAPL"]
    assert x_analysis._x_chain_available() is False


def test_insufficient_data_result_falls_back_to_stocktwits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Below-threshold scraped posts → fallback instead of a hollow verdict."""
    _patch_analyze(
        monkeypatch,
        lambda query, limit, since, until, lang: {
            "query": query,
            "post_count": 3,
            "verdict": "insufficient_data",
            "mood": "insufficient_data",
            "warning": "only 3 post(s) scraped",
        },
    )
    calls = _stub_chip(monkeypatch, _CHIP)

    r = client.post("/api/x/analyze", json={"query": "AAPL"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "stocktwits"
    assert body["post_count"] == 12
    assert calls == ["AAPL"]


def test_free_text_query_keeps_honest_empty_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Free text is never ticker-mapped onto Stocktwits (honest empty path)."""
    seen: list[str] = []

    def _record(query, limit, since, until, lang):
        seen.append(query)
        return _empty(query, limit, since, until, lang)

    _patch_analyze(monkeypatch, _record)

    from showme.server_routes import xai

    monkeypatch.setattr(
        xai,
        "fetch_symbol_chip",
        lambda *a, **k: pytest.fail("free text must not ride the Stocktwits fallback"),
    )

    r = client.post("/api/x/analyze", json={"query": "solar stocks"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["post_count"] == 0
    assert body["warning"] == "no posts returned by any scraper backend"
    assert "source" not in body
    assert seen == ["solar stocks"]


def test_missing_model_free_text_still_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Free text + missing model keeps the legacy 503 (no fake fallback)."""
    _patch_analyze(monkeypatch, _raise_missing)
    _stub_chip(monkeypatch, _CHIP)

    r = client.post("/api/x/analyze", json={"query": "solar stocks"})
    assert r.status_code == 503
    assert "model not found" in r.json()["detail"]


def test_fallback_failure_keeps_503_for_missing_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stocktwits has nothing → FileNotFoundError keeps its 503."""
    _patch_analyze(monkeypatch, _raise_missing)
    calls = _stub_chip(monkeypatch, None)

    r = client.post("/api/x/analyze", json={"query": "AAPL"})
    assert r.status_code == 503
    assert "model not found" in r.json()["detail"]
    assert calls == ["AAPL"]


def test_fallback_failure_keeps_empty_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stocktwits has nothing → the original empty X payload is returned."""
    _patch_analyze(monkeypatch, _empty)
    calls = _stub_chip(monkeypatch, None)

    r = client.post("/api/x/analyze", json={"query": "AAPL"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["post_count"] == 0
    assert body["warning"] == "no posts returned by any scraper backend"
    assert "source" not in body
    assert calls == ["AAPL"]


def test_cooling_chain_skips_x_and_uses_stocktwits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tripped breaker: ticker → fallback without touching the dead X chain."""
    from showme import x_analysis

    x_analysis._note_x_chain_failure("test trip")
    assert x_analysis._x_chain_available() is False

    _patch_analyze(monkeypatch, lambda *a, **k: pytest.fail("X must be skipped while cooling"))
    calls = _stub_chip(monkeypatch, _CHIP)

    r = client.post("/api/x/analyze", json={"query": "BTCUSDT"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "stocktwits"
    assert calls == ["BTCUSDT"]


def test_cooling_chain_free_text_returns_empty_without_dead_wait(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tripped breaker + free text: honest empty payload, zero X attempts."""
    from showme import x_analysis

    x_analysis._note_x_chain_failure("test trip")
    _patch_analyze(monkeypatch, lambda *a, **k: pytest.fail("X must be skipped while cooling"))

    from showme.server_routes import xai

    monkeypatch.setattr(
        xai,
        "fetch_symbol_chip",
        lambda *a, **k: pytest.fail("free text must not ride the Stocktwits fallback"),
    )

    r = client.post("/api/x/analyze", json={"query": "solar stocks"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["post_count"] == 0
    assert "cooling" in body["warning"]
