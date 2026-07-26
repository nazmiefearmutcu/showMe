from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from showme import veryfinder_bridge


@pytest.fixture(autouse=True)
def _isolate_veryfinder_state(monkeypatch):
    """Make every test in this file order-independent *and* machine-independent.

    Two leaks from ``tests/x/test_bughunt_2026_05_24.py`` (when it runs first
    in the full suite) otherwise break the fixture/source/news-proxy tests:

    1. It populates the process-wide ``veryfinder_bridge._CACHE`` (300s TTL) via
       ``analyze_symbol``/``analyze_query``; a stale entry then masks the
       per-test monkeypatched ``public_search_items``.
    2. Its ``app`` fixture does a bare ``os.environ["SHOWME_HOME"]=<tmp>`` that
       is never restored, so ``veryfinder_root()`` resolves to a now-deleted
       junk dir.

    We clear ``_CACHE`` and ``delenv("SHOWME_HOME")`` so root resolution starts
    from a clean slate. ``monkeypatch.delenv`` restores whatever value was
    present afterward, so this never leaks further.

    No test in this file depends on the *default* root resolution any more.
    Every test that needs a running veryfinder builds a throwaway one under
    ``tmp_path`` via the ``synthetic_veryfinder_root`` fixture and points
    ``SHOWME_VERYFINDER_ROOT`` at it; the rest either pin
    ``veryfinder_root``/``SHOWME_HOME`` themselves or exercise pure helpers.
    That is what makes them pass on a bare Linux CI runner, where no
    ``~/Library/Application Support/showMe/integrations/veryfinder`` exists.
    """
    veryfinder_bridge._CACHE.clear()
    monkeypatch.delenv("SHOWME_HOME", raising=False)
    yield
    veryfinder_bridge._CACHE.clear()


# ---------------------------------------------------------------------------
# Synthetic veryfinder runtime
# ---------------------------------------------------------------------------
#
# ``veryfinder_bridge`` needs exactly four things from a veryfinder root:
#   1. ``<root>/veryfinder/orchestrator.py`` must exist  (``veryfinder_root()``)
#   2. ``veryfinder.config.VeryfinderConfig.from_env(env_file=...)``
#   3. ``veryfinder.orchestrator.Veryfinder(config).analyze_query(...)``
#      returning an object with ``.to_dict(include_posts=True)``
#   4. ``<root>/data/fixtures/sample_posts.jsonl`` for the fixture source
#      (``default_fixture_path``)
# Everything below is the smallest thing that satisfies that contract. The
# analysis itself is data-driven from the JSONL, so the bridge's own
# relevance/query filtering — which is what these tests assert on — still
# does all the real work.

_SYNTHETIC_CONFIG_SRC = '''\
"""Synthetic ``veryfinder.config`` for showMe bridge tests."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VeryfinderConfig:
    engine: str = "rules"
    model_profile: str = "default"
    device: str = "cpu"
    # Hardcoded to None and deliberately NOT read from os.environ: with no X
    # credential, ``veryfinder_bridge.resolve_source`` maps source="auto" to
    # "fixture", which is the precondition the auto-source tests are written
    # against. Reading the environment here would reintroduce the
    # machine-dependence these tests exist to avoid.
    x_bearer_token: str | None = None
    request_timeout: float = 30.0
    min_relevance: float = 0.04

    @classmethod
    def from_env(cls, env_file=None) -> "VeryfinderConfig":
        return cls()

    def with_engine(self, engine=None) -> "VeryfinderConfig":
        if not engine:
            return self
        return VeryfinderConfig(
            engine=str(engine),
            model_profile=self.model_profile,
            device=self.device,
            x_bearer_token=self.x_bearer_token,
            request_timeout=self.request_timeout,
            min_relevance=self.min_relevance,
        )
'''

_SYNTHETIC_ORCHESTRATOR_SRC = '''\
"""Synthetic ``veryfinder.orchestrator`` for showMe bridge tests.

Implements only the surface ``showme.veryfinder_bridge`` calls, with the
payload shape of the real ``veryfinder.domain.AnalysisReport.to_dict``.
The fixture provider returns the demo posts verbatim (unique by author,
capped at ``sample``) regardless of the query — exactly like the real
fixture provider — so query relevance is decided by the bridge.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = ROOT / "data" / "fixtures" / "sample_posts.jsonl"

_POST_FIELDS = (
    "id",
    "author_id",
    "username",
    "created_at",
    "lang",
    "text",
    "like_count",
    "reply_count",
    "repost_count",
    "quote_count",
    "view_count",
)


def _load_rows(fixture_path):
    path = Path(fixture_path) if fixture_path else DEFAULT_FIXTURE
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _unique_by_author(rows, limit):
    seen = set()
    out = []
    for row in rows:
        key = str(row.get("author_id") or row.get("username") or row.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _distribution(analyses, field):
    counter = {}
    for entry in analyses:
        label = str((entry.get(field) or {}).get("label") or "")
        if label:
            counter[label] = counter.get(label, 0) + 1
    total = sum(counter.values())
    if not total:
        return {}
    return {label: round(count / total, 4) for label, count in sorted(counter.items())}


class AnalysisReport:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self, include_posts=True):
        payload = dict(self._payload)
        if not include_posts:
            payload.pop("analyzed_posts", None)
        return payload


class Veryfinder:
    def __init__(self, config=None):
        self.config = config

    def analyze_query(
        self,
        query,
        sample,
        source="official",
        engine=None,
        fixture_path=None,
        rss_item=None,
    ):
        if sample <= 0:
            raise ValueError("sample must be greater than 0")
        rows = _unique_by_author(_load_rows(fixture_path), sample) if source == "fixture" else []
        analyses = []
        for row in rows:
            post = {field: row.get(field) for field in _POST_FIELDS}
            post["source"] = source
            analyses.append(
                {
                    "post": post,
                    "relevance": row.get("relevance", 0.0),
                    "sentiment": row.get("sentiment"),
                    "financial_sentiment": row.get("sentiment"),
                    "emotion": row.get("mood"),
                    "action": row.get("action"),
                    "mood": row.get("mood"),
                    "view": row.get("view"),
                    "themes": [],
                    "emoji_reactions": {},
                    "signals": list(row.get("signals") or []),
                }
            )
        view_distribution = _distribution(analyses, "view")
        if view_distribution:
            label, score = max(view_distribution.items(), key=lambda item: item[1])
        else:
            label, score = "no_data", 0.0
        authors = {str((entry["post"] or {}).get("author_id") or "") for entry in analyses}
        return AnalysisReport(
            {
                "query": query,
                "source": source,
                "requested_sample": sample,
                "collected_posts": len(analyses),
                "unique_accounts": len([author for author in authors if author]),
                "dominant_view": {"label": label, "score": score, "scores": {}},
                "view_distribution": view_distribution,
                "sentiment_distribution": _distribution(analyses, "sentiment"),
                "mood_distribution": _distribution(analyses, "mood"),
                "action_distribution": _distribution(analyses, "action"),
                "tweet_count_estimate": None,
                "model_notes": ["synthetic veryfinder test runtime"],
                "analyzed_posts": analyses,
            }
        )
'''


def _fixture_posts() -> list[dict[str, object]]:
    """Demo posts for ``data/fixtures/sample_posts.jsonl``.

    Shaped like the real fixture (raw social posts) plus the pre-baked label
    dicts the synthetic analyzer hands straight back. Three distinct authors,
    all BTC-flavoured: BTC/bitcoin queries must score them, everything else
    (FLOCK, AMZN, ETH) must be filtered out by the bridge. ``created_at`` is
    relative so this file never rots into a date-dependent failure.
    """
    stamp = datetime.now(timezone.utc) - timedelta(hours=3)
    created_at = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    return [
        {
            "id": "1",
            "author_id": "a1",
            "username": "alpha_cap",
            "created_at": created_at,
            "lang": "en",
            "text": "BTC is holding the range after the ETF headline; spot demand looks strong.",
            "like_count": 42,
            "reply_count": 4,
            "repost_count": 7,
            "quote_count": 2,
            "relevance": 0.82,
            "view": {"label": "bullish_or_confident", "score": 0.74},
            "sentiment": {"label": "positive", "score": 0.74},
            "mood": {"label": "confidence", "score": 0.68},
            "action": {"label": "buy_or_hold", "score": 0.61},
        },
        {
            "id": "2",
            "author_id": "a2",
            "username": "riskdesk",
            "created_at": created_at,
            "lang": "en",
            "text": "Bitcoin looks overheated after that headline. I sold half into the move.",
            "like_count": 18,
            "reply_count": 3,
            "repost_count": 2,
            "quote_count": 1,
            "relevance": 0.71,
            "view": {"label": "bearish_or_panic", "score": 0.66},
            "sentiment": {"label": "negative", "score": 0.66},
            "mood": {"label": "fear", "score": 0.58},
            "action": {"label": "sell_or_reduce", "score": 0.6},
        },
        {
            "id": "3",
            "author_id": "a3",
            "username": "chainwatch",
            "created_at": created_at,
            "lang": "en",
            "text": "Volume is strong and buyers keep defending support, BTC bid stays firm.",
            "like_count": 63,
            "reply_count": 6,
            "repost_count": 8,
            "quote_count": 2,
            "relevance": 0.79,
            "view": {"label": "bullish_or_confident", "score": 0.7},
            "sentiment": {"label": "positive", "score": 0.7},
            "mood": {"label": "confidence", "score": 0.64},
            "action": {"label": "buy_or_hold", "score": 0.58},
        },
    ]


def _purge_veryfinder_modules() -> None:
    """Drop any imported ``veryfinder`` package.

    ``veryfinder_bridge._load_veryfinder`` imports by module name, so without
    this a previously imported runtime (the developer's real install, or an
    earlier test's tmp_path copy) would be reused from ``sys.modules`` and the
    synthetic root would silently have no effect.
    """
    for name in [n for n in sys.modules if n == "veryfinder" or n.startswith("veryfinder.")]:
        del sys.modules[name]


@pytest.fixture
def synthetic_veryfinder_root(monkeypatch, tmp_path) -> Path:
    """Build a throwaway veryfinder runtime under ``tmp_path`` and select it.

    Tests that call ``analyze_symbol``/``analyze_query``/``analyze_item``
    request this fixture instead of relying on whatever veryfinder happens to
    be installed on the machine: on CI nothing is installed (every overlay
    degrades to ``source="unavailable"``), on the author's Mac the real
    integration cache is found. Both are now irrelevant.
    """
    root = tmp_path / "veryfinder-runtime"
    package = root / "veryfinder"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "config.py").write_text(_SYNTHETIC_CONFIG_SRC, encoding="utf-8")
    (package / "orchestrator.py").write_text(_SYNTHETIC_ORCHESTRATOR_SRC, encoding="utf-8")

    fixtures = root / "data" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "sample_posts.jsonl").write_text(
        "\n".join(json.dumps(post) for post in _fixture_posts()) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("SHOWME_VERYFINDER_ROOT", str(root))
    # ``_load_veryfinder`` mutates sys.path in place; hand it a copy so the
    # tmp_path entry disappears with the test.
    monkeypatch.setattr(sys, "path", list(sys.path))
    _purge_veryfinder_modules()

    assert veryfinder_bridge.veryfinder_root() == root.resolve()
    try:
        yield root
    finally:
        _purge_veryfinder_modules()


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


def test_auto_fixture_zero_evidence_expands_to_public_search(monkeypatch, synthetic_veryfinder_root) -> None:
    """source="auto" + a fixture with no FLOCK evidence must widen the net.

    The synthetic root resolves "auto" to "fixture" (no X credential) and its
    demo posts are BTC-only, so the fixture leg genuinely returns zero
    query-relevant evidence — the precondition for the public-search expansion.
    """
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


def test_auto_source_enforces_minimum_search_sample(monkeypatch, synthetic_veryfinder_root) -> None:
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


def test_veryfinder_bridge_symbol_overlay_uses_unique_account_view(synthetic_veryfinder_root) -> None:
    # The synthetic fixture holds three BTC posts from three distinct authors,
    # so a BTC query must score all three (unique_accounts == 3).
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


def test_veryfinder_bridge_batch_preserves_item_keys(synthetic_veryfinder_root) -> None:
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


def test_veryfinder_bridge_fixture_does_not_score_unrelated_queries(synthetic_veryfinder_root) -> None:
    # A live fixture source that *has* posts (BTC ones) but none matching the
    # query — without the synthetic root this assertion was satisfied trivially
    # by an "unavailable" overlay on any machine lacking the integration.
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


def test_veryfinder_bridge_uses_news_proxy_for_symbol_article_when_fixture_has_no_match(
    synthetic_veryfinder_root,
) -> None:
    # source_fallback_from == "fixture" below is the load-bearing bit: the
    # fixture leg must really have run and really have found nothing for ETH.
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
