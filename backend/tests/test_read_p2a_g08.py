"""READ (Reading List) manifest/handler agreement pins (p2a-g08).

Network-free: the saved-articles store is injected through deps, so no file or
provider is touched.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from showme.engine.functions.news.read import READFunction
from showme.engine.services.reading_list_store import SavedArticle
from showme.manifest.seeds import read_seed


class _Store:
    def __init__(self, items):
        self._items = list(items)

    def list(self, status=None, tags=None, symbols=None, limit=50):
        out = self._items
        if status:
            out = [a for a in out if a.status in status]
        return out[:limit]

    def counts(self):
        counts: dict[str, int] = {}
        for a in self._items:
            counts[a.status] = counts.get(a.status, 0) + 1
        return counts


def _article(title: str, status: str) -> SavedArticle:
    return SavedArticle(
        article_id=title,
        url=f"https://news.example/{title}",
        title=title,
        source="news.example",
        matched_symbol="AAPL",
        status=status,
    )


def _fn(items) -> READFunction:
    return READFunction(deps=SimpleNamespace(reading_list_store=_Store(items)))


def _run(fn, **params):
    return asyncio.run(fn.execute(**params)).data


# ── READ#3: handler default status must match the manifest default ──────────


def _manifest():
    return read_seed.read  # @manifest() already returns the FunctionManifest


def test_manifest_default_status_is_unread_and_in_progress():
    assert _manifest().defaults["status"] == ["unread", "in_progress"]


def test_handler_default_excludes_read_and_archived_like_the_manifest():
    fn = _fn([
        _article("u", "unread"),
        _article("p", "in_progress"),
        _article("r", "read"),
        _article("a", "archived"),
    ])
    data = _run(fn)
    assert sorted(r["status"] for r in data["rows"]) == ["in_progress", "unread"]


def test_explicit_status_filter_still_returns_archived_items():
    fn = _fn([_article("a", "archived"), _article("u", "unread")])
    data = _run(fn, status=["archived"])
    assert [r["status"] for r in data["rows"]] == ["archived"]


def test_methodology_names_the_real_store_module():
    text = _manifest().methodology
    assert "reading_list_store" in text
    assert "news_store" not in text


# ── READ#2: the manifest must not declare a live refresh the handler lacks ──


def test_manifest_declares_no_unimplemented_live_input():
    names = [spec.name for spec in _manifest().inputs]
    assert "live" not in names
    assert "live" not in _manifest().defaults


def test_manifest_methodology_does_not_claim_a_feed_refetch():
    text = _manifest().methodology.lower()
    assert "re-fetches" not in text
    assert "open-graph" not in text
    assert "live=true" not in text
