from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import pytest

from showme import veryfinder_bridge


@pytest.fixture(autouse=True)
def _isolate_veryfinder_state(monkeypatch):
    """Make every test in this file order-independent.

    Two leaks from ``tests/x/test_bughunt_2026_05_24.py`` (when it runs first
    in the full suite) otherwise break the fixture/source/news-proxy tests:

    1. It populates the process-wide ``veryfinder_bridge._CACHE`` (300s TTL) via
       ``analyze_symbol``/``analyze_query``; a stale entry then masks the
       per-test monkeypatched ``public_search_items``.
    2. Its ``app`` fixture does a bare ``os.environ["SHOWME_HOME"]=<tmp>`` that
       is never restored, so ``veryfinder_root()`` resolves to a now-deleted
       junk dir → ``source=unavailable`` / zero fixtures, whereas these tests
       were written against the default resolution that finds the real local
       veryfinder install (``source=fixture``, populated overlays).

    We clear ``_CACHE`` and ``delenv("SHOWME_HOME")`` so root resolution returns
    to its un-leaked default. ``monkeypatch.delenv`` restores whatever value was
    present afterward, so this never leaks further. Tests that set their own
    ``veryfinder_root``/``SHOWME_HOME`` still win (applied after this fixture).
    """
    veryfinder_bridge._CACHE.clear()
    monkeypatch.delenv("SHOWME_HOME", raising=False)
    yield
    veryfinder_bridge._CACHE.clear()


def test_veryfinder_root_prefers_application_support_cache(monkeypatch, tmp_path) -> None:
    app_home = tmp_path / "showMe"
    root = app_home / "integrations" / "veryfinder"
    package = root / "veryfinder"
    package.mkdir(parents=True)
    (package / "orchestrator.py").write_text("", encoding="utf-8")

    monkeypatch.setenv("SHOWME_HOME", str(app_home))
    monkeypatch.delenv("SHOWME_VERYFINDER_ROOT", raising=False)
    monkeypatch.delenv("SHOWME_ALLOW_DESKTOP_VERYFINDER", raising=False)

    assert veryfinder_bridge.veryfinder_root() == root.resolve()


def test_packaged_veryfinder_root_does_not_probe_desktop(monkeypatch, tmp_path) -> None:
    app_home = tmp_path / "showMe"
    bundle_root = tmp_path / "bundle"
    monkeypatch.setenv("SHOWME_HOME", str(app_home))
    monkeypatch.delenv("SHOWME_VERYFINDER_ROOT", raising=False)
    monkeypatch.delenv("SHOWME_ALLOW_DESKTOP_VERYFINDER", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)

    candidates = veryfinder_bridge.veryfinder_root_candidates()

    assert veryfinder_bridge.DEFAULT_ROOT not in candidates
    assert veryfinder_bridge.veryfinder_root() is None


def test_analyze_query_returns_no_data_without_runtime(monkeypatch) -> None:
    monkeypatch.setattr(veryfinder_bridge, "veryfinder_root", lambda: None)

    payload = veryfinder_bridge.analyze_query("ETH OR ethereum", sample=25, source="auto")

    assert payload["ok"] is True
    assert payload["source"] == "unavailable"
    assert payload["social_score"] == 0
    assert payload["posts"] == []
    assert "Desktop fallback is disabled" in payload["model_notes"][0]


def test_auto_fixture_zero_evidence_expands_to_public_search(monkeypatch) -> None:
    veryfinder_bridge._CACHE.clear()

    def fake_public_search_items(query: str, *, sample: int) -> list[dict[str, str]]:
        assert "FLOCK" in query
        assert sample == veryfinder_bridge.MIN_SEARCH_SAMPLE
        return [
            {
                "title": "FLOCK token gains after Binance futures listing",
                "summary": "Traders discuss FLOCKUSDT liquidity and confidence after the listing.",
                "source": "public search",
                "url": "https://example.com/flock",
            }
        ]

    monkeypatch.setattr(veryfinder_bridge, "public_search_items", fake_public_search_items)

    payload = veryfinder_bridge.analyze_symbol("FLOCKUSDT", sample=25, source="auto", engine="rules")

    assert payload["ok"] is True
    assert payload["source"] == "public_search"
    assert payload["fallback_mode"] == "expanded_public_search"
    assert payload["source_fallback_from"] == "fixture"
    assert payload["unique_accounts"] == 1
    assert payload["posts"][0]["text"]


def test_auto_source_enforces_minimum_search_sample(monkeypatch) -> None:
    veryfinder_bridge._CACHE.clear()

    def fake_public_search_items(query: str, *, sample: int) -> list[dict[str, str]]:
        return [
            {
                "title": f"FLOCK evidence {sample}",
                "summary": "FLOCKUSDT liquidity discussion",
                "source": "public search",
                "url": "https://example.com/min-sample",
            }
        ]

    monkeypatch.setattr(veryfinder_bridge, "public_search_items", fake_public_search_items)

    payload = veryfinder_bridge.analyze_symbol("FLOCKUSDT", sample=60, source="auto", engine="rules")

    assert payload["requested_sample"] == veryfinder_bridge.MIN_SEARCH_SAMPLE
    assert "140" in payload["posts"][0]["text"]


def test_public_search_drops_stale_dated_evidence() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=veryfinder_bridge.RECENT_EVIDENCE_DAYS)
    old = datetime.now(timezone.utc) - timedelta(days=400)
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    assert not veryfinder_bridge._append_unique_search_item(
        items,
        seen,
        {
            "title": "AMZN stale search result",
            "summary": "Old public search evidence",
            "source": "public search",
            "url": "https://example.com/stale",
            "published_at": old.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        },
        5,
        cutoff=cutoff,
    )
    assert items == []

    assert veryfinder_bridge._append_unique_search_item(
        items,
        seen,
        {
            "title": "AMZN recent search result",
            "summary": "Recent public search evidence",
            "source": "public search",
            "url": "https://example.com/recent",
            "published_at": recent.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        },
        5,
        cutoff=cutoff,
    )
    assert items[0]["url"] == "https://example.com/recent"


def test_public_search_parses_ui_style_old_dates() -> None:
    parsed = veryfinder_bridge.public_item_datetime(
        {
            "title": "Amazon Web Services result",
            "summary": "Cryptocurrency data page 4/22/2022, 1:48:19 AM",
            "url": "https://example.com/aws",
        }
    )

    assert parsed is not None
    assert parsed.year == 2022


def test_public_search_sorts_rolling_window_newest_first() -> None:
    items = [
        {"title": "older", "published_at": "Mon, 13 Apr 2026 10:00:00 GMT", "url": "https://example.com/older"},
        {"title": "undated", "url": "https://example.com/undated"},
        {"title": "newer", "published_at": "Tue, 05 May 2026 10:00:00 GMT", "url": "https://example.com/newer"},
    ]

    sorted_items = veryfinder_bridge.sort_public_items_newest_first(items)

    assert [item["title"] for item in sorted_items] == ["newer", "older", "undated"]


def test_retained_cached_overlay_keeps_previous_nonempty_window() -> None:
    retained = veryfinder_bridge.retained_cached_overlay(
        {
            "unique_accounts": 7,
            "collected_posts": 140,
            "model_notes": ["previous run"],
        },
        reason="refresh empty",
    )

    assert retained is not None
    assert retained["cache"] == "retained"
    assert retained["unique_accounts"] == 7
    assert retained["model_notes"][0] == "refresh empty"

    assert veryfinder_bridge.retained_cached_overlay({"unique_accounts": 0}, reason="empty") is None


def test_veryfinder_bridge_symbol_overlay_uses_unique_account_view() -> None:
    payload = veryfinder_bridge.analyze_symbol(
        "BTCUSDT",
        sample=3,
        source="fixture",
        engine="rules",
    )

    assert payload["ok"] is True
    assert payload["source"] == "fixture"
    assert payload["engine"] == "rules"
    assert payload["dominant_view"]["label"]
    assert isinstance(payload["social_score"], int)
    assert payload["unique_accounts"] == 3
    assert "social confirmation/contradiction" in payload["meaning"]


def test_veryfinder_bridge_batch_preserves_item_keys() -> None:
    payload = veryfinder_bridge.analyze_batch(
        [
            {
                "key": "article-1",
                "title": "BTC traders wait for the Fed decision",
                "summary": "Market discussion is split between hold and buy reactions.",
            }
        ],
        symbol="BTCUSDT",
        sample=3,
        source="fixture",
        engine="rules",
    )

    assert payload["ok"] is True
    assert payload["items"][0]["key"] == "article-1"
    assert payload["items"][0]["overlay"]["ok"] is True


def test_veryfinder_bridge_fixture_does_not_score_unrelated_queries() -> None:
    payload = veryfinder_bridge.analyze_symbol(
        "AMZN",
        sample=12,
        source="fixture",
        engine="rules",
    )

    assert payload["ok"] is True
    assert payload["dominant_view"]["label"] == "no_data"
    assert payload["social_score"] == 0
    assert payload["unique_accounts"] == 0
    assert payload["posts"] == []

    article_payload = veryfinder_bridge.analyze_item(
        {
            "title": "Private payrolls rose by 109,000 in April, topping expectations, ADP says",
            "summary": "The report provided more evidence of a stable labor market and less incentive for the Fed.",
        },
        topic="market",
        sample=33,
        source="fixture",
        engine="rules",
    )

    assert article_payload["dominant_view"]["label"] == "no_data"
    assert article_payload["social_score"] == 0
    assert article_payload["unique_accounts"] == 0
    assert article_payload["posts"] == []


def test_veryfinder_bridge_uses_news_proxy_for_symbol_article_when_fixture_has_no_match() -> None:
    payload = veryfinder_bridge.analyze_item(
        {
            "title": "Ethereum co-founder Lubin backs ETH treasury firms, calls DATs profound innovation",
            "summary": "Joseph Lubin backed ETH treasury firms and highlighted Ethereum's quantum-safe roadmap.",
            "source": "crypto news",
        },
        symbol="ETHUSDT",
        sample=107,
        source="fixture",
        engine="rules",
    )

    assert payload["ok"] is True
    assert payload["source"] == "news_proxy"
    assert payload["fallback_mode"] == "article_context"
    assert payload["source_fallback_from"] == "fixture"
    assert payload["dominant_view"]["label"] == "bullish_or_confident"
    assert payload["social_score"] > 0
    assert payload["impact_score"] > 0
    assert payload["unique_accounts"] == 1


def test_neutral_veryfinder_view_keeps_nonzero_impact_score() -> None:
    payload = veryfinder_bridge.compact_report(
        {
            "source": veryfinder_bridge.PUBLIC_SEARCH_SOURCE,
            "query": "AMZN",
            "requested_sample": 140,
            "collected_posts": 1,
            "analyzed_posts": [
                {
                    "post": {
                        "id": "neutral-1",
                        "text": "AMZN investors are waiting for the next earnings update.",
                        "username": "marketdesk",
                    },
                    "view": {"label": "neutral_or_waiting", "score": 0.56},
                    "sentiment": {"label": "neutral", "score": 0.56},
                    "mood": {"label": "uncertainty", "score": 0.52},
                    "action": {"label": "no clear trading advice", "score": 0.55},
                    "relevance": 0.82,
                }
            ],
        },
        engine="rules",
    )

    assert payload["dominant_view"]["label"] == "neutral_or_waiting"
    assert payload["social_score"] == 0
    assert payload["impact_score"] == 56
