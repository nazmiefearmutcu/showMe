"""Regression tests for SHOWME_BUGHUNT 2026-05-24, theme 5 + 6.

Pins the XSEN + Veryfinder + xAI fixes:

* Bug #10b — /api/x/analyze accepts the legacy {"query": "..."} body shape
  that older UI builds (and ui/src/lib/xai.ts:analyzeXTopic) still send.
  Previously the field was silently dropped by ConfigDict(extra="ignore")
  and every Run press returned HTTP 400.
* Bug #6  — The XAnalyzer.analyze_topic guard refuses to produce a verdict
  off fewer than MIN_POSTS_FOR_VERDICT real posts; instead it returns
  {"verdict": "insufficient_data"} so the UI can render a "not enough data"
  empty state rather than confidently call 2 neutral tweets "bullish".
* Bug #7  — /api/veryfinder/batch returns HTTP 503 when the Veryfinder
  runtime is unavailable, instead of {ok: true, items: []} which made the
  UI fire a green "Veryfinder inference ready" toast every 60 s.
* Bug #10e — XAnalyzeBody now declares query/limit/since/until explicitly
  (alongside symbol/topic) so the handler can both validate them and pass
  the date filters through to the scraper.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme import server

ROOT = Path(__file__).resolve().parents[2] / "showme"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def app(tmp_path_factory: pytest.TempPathFactory):
    home = tmp_path_factory.mktemp("bughunt-x-home")
    os.environ["SHOWME_HOME"] = str(home)
    return server.build_app(engine_root=None)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


# ── Bug #10b — /api/x/analyze tolerates the legacy {query} body shape ──────


def test_x_analyze_legacy_query_field_is_promoted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """{"query": "AAPL"} must not raise HTTP 400 (was the broken path)."""
    from showme import x_analysis

    captured: dict[str, object] = {}

    class _Stub:
        def analyze_topic(self, query, limit, since, until, lang):  # noqa: PLR0913
            captured.update(query=query, limit=limit, since=since, until=until, lang=lang)
            return {"query": query, "post_count": 42, "mood": "bullish"}

        def health(self):
            return {"ok": True, "model_loaded": True}

    monkeypatch.setattr(x_analysis.XAnalyzer, "instance", classmethod(lambda cls: _Stub()))

    r = client.post("/api/x/analyze", json={"query": "AAPL"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"] == "AAPL"
    assert captured["query"] == "AAPL"
    # Default limit is 120 when neither `limit` nor non-empty `posts` is given.
    assert captured["limit"] == 120
    # `since`/`until` default to None when the client omits them.
    assert captured["since"] is None
    assert captured["until"] is None


def test_x_analyze_query_alongside_since_and_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The expanded XAnalyzeBody passes since/until/limit through."""
    from showme import x_analysis

    captured: dict[str, object] = {}

    class _Stub:
        def analyze_topic(self, query, limit, since, until, lang):  # noqa: PLR0913
            captured.update(query=query, limit=limit, since=since, until=until, lang=lang)
            return {"query": query, "post_count": 9, "mood": "mixed"}

    monkeypatch.setattr(x_analysis.XAnalyzer, "instance", classmethod(lambda cls: _Stub()))

    r = client.post(
        "/api/x/analyze",
        json={
            "query": "bitcoin",
            "limit": 80,
            "since": "2026-05-17",
            "until": "2026-05-24",
            "lang": "en",
        },
    )
    assert r.status_code == 200, r.text
    assert captured["query"] == "bitcoin"
    assert captured["limit"] == 80
    assert captured["since"] == "2026-05-17"
    assert captured["until"] == "2026-05-24"
    assert captured["lang"] == "en"


def test_x_analyze_symbol_field_still_works(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Documented {symbol: ...} shape must keep working (no regression)."""
    from showme import x_analysis

    captured: dict[str, object] = {}

    class _Stub:
        def analyze_topic(self, query, limit, since, until, lang):  # noqa: PLR0913
            captured.update(query=query)
            return {"query": query, "post_count": 1, "mood": "mixed"}

    monkeypatch.setattr(x_analysis.XAnalyzer, "instance", classmethod(lambda cls: _Stub()))

    r = client.post("/api/x/analyze", json={"symbol": "TSLA"})
    assert r.status_code == 200, r.text
    assert captured["query"] == "TSLA"


def test_x_analyze_empty_body_still_rejects(client: TestClient) -> None:
    """If neither query/symbol/topic is provided we must still 400."""
    r = client.post("/api/x/analyze", json={})
    assert r.status_code == 400


# ── Bug #6 — MIN_POSTS_FOR_VERDICT guard ───────────────────────────────────


def test_analyze_topic_returns_insufficient_data_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2 scraped posts must never produce a bullish/bearish verdict."""
    from showme import x_analysis
    from showme.x_spontaneous import Post

    fake_posts = [
        Post(id="1", text="apple is fine", user="alice", date=""),
        Post(id="2", text="aapl trade desk", user="bob", date=""),
    ]

    analyzer = x_analysis.XAnalyzer()

    class _FakeScraper:
        def search(self, query, limit, since, until, lang):  # noqa: PLR0913
            return fake_posts

        def diagnostics(self):
            return {"backends": {}}

    monkeypatch.setattr(analyzer, "_scraper", _FakeScraper())
    # Should NOT call classify() — the guard short-circuits before it.
    monkeypatch.setattr(
        analyzer,
        "classify",
        lambda *a, **kw: pytest.fail("classify must not run when below threshold"),
    )

    out = analyzer.analyze_topic("AAPL", limit=10)
    assert out["verdict"] == "insufficient_data"
    assert out["mood"] == "insufficient_data"
    assert out["post_count"] == 2
    assert out["scores"]["confidence"] == 0.0
    assert out["scores"]["bullish_score_engagement_weighted"] == 0.0
    assert out["min_posts_for_verdict"] == x_analysis.MIN_POSTS_FOR_VERDICT
    # The diagnostics blob from the scraper should also be surfaced so the
    # UI can show which backends were tried.
    assert "scraper" in out


def test_analyze_topic_with_zero_posts_is_still_no_posts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero-post path keeps its own warning, separate from insufficient_data."""
    from showme import x_analysis

    analyzer = x_analysis.XAnalyzer()

    class _EmptyScraper:
        def search(self, *_a, **_kw):
            return []

        def diagnostics(self):
            return {"backends": {}}

    monkeypatch.setattr(analyzer, "_scraper", _EmptyScraper())
    out = analyzer.analyze_topic("ZZZZ", limit=10)
    assert out["post_count"] == 0
    # The empty path uses warning text, not verdict (distinguishes from #6).
    assert out.get("verdict") is None
    assert "no posts" in out["warning"]


def test_min_posts_for_verdict_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operators can lower/raise the threshold via env for ops tuning."""
    monkeypatch.setenv("SHOWME_X_MIN_POSTS_FOR_VERDICT", "12")
    import importlib

    from showme import x_analysis as mod

    importlib.reload(mod)
    try:
        assert mod.MIN_POSTS_FOR_VERDICT == 12
    finally:
        # Restore default for downstream tests in the same session.
        monkeypatch.delenv("SHOWME_X_MIN_POSTS_FOR_VERDICT", raising=False)
        importlib.reload(mod)


def test_symbol_chip_does_not_pretend_to_have_data_on_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DES/CN chips that build on symbol_chip must not raise KeyError when
    analyze_topic returns the insufficient_data shape (no examples key)."""
    from showme import x_analysis

    analyzer = x_analysis.XAnalyzer()
    insufficient = {
        "query": "AAPL",
        "post_count": 3,
        "verdict": "insufficient_data",
        "mood": "insufficient_data",
        "warning": "only 3 post(s) scraped",
    }
    monkeypatch.setattr(analyzer, "analyze_topic", lambda **kw: insufficient)

    chip = analyzer.symbol_chip("AAPL")
    assert chip["ok"] is False
    assert chip["post_count"] == 3
    assert chip["verdict"] == "insufficient_data"


# ── Bug #7 — /api/veryfinder/batch fails closed when runtime is missing ────


def test_veryfinder_batch_returns_503_when_runtime_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The batch endpoint must refuse work when the runtime can't be found,
    so the UI's `sidecarFetch` rejects and the "ready" toast never fires."""
    from showme import veryfinder_bridge

    monkeypatch.setattr(veryfinder_bridge, "veryfinder_root", lambda: None)

    r = client.post(
        "/api/veryfinder/batch",
        json={"items": [{"title": "stub"}], "sample": 25},
    )
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert detail["ok"] is False
    assert detail["reason"] == "veryfinder_runtime_unavailable"


def test_veryfinder_batch_still_runs_when_runtime_is_present(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity-check: if veryfinder_root() returns a Path, the batch must
    actually call analyze_batch (i.e., we did not over-block the route)."""
    from pathlib import Path as _Path

    from showme import veryfinder_bridge

    called: dict[str, object] = {}

    monkeypatch.setattr(veryfinder_bridge, "veryfinder_root", lambda: _Path("/tmp/fake"))

    def _fake_analyze_batch(*args, **kwargs):
        called.update(kwargs)
        called["item_count"] = len(args[0]) if args else 0
        return {"ok": True, "count": 1, "items": [{"key": "k", "overlay": {}}]}

    monkeypatch.setattr(veryfinder_bridge, "analyze_batch", _fake_analyze_batch)

    r = client.post(
        "/api/veryfinder/batch",
        json={"items": [{"title": "stub"}], "sample": 25},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert called["item_count"] == 1
