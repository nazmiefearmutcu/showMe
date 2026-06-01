"""De-garbage tests for READ — Reading List backed by the saved-articles store.

READ used to return a hardcoded watchlist "brief" placeholder
(source="watchlist_cache", title="{S} watchlist brief") that ignored the
manifest (which promises a persistent reading list backed by the internal
saved-articles store). These tests pin the real CRUD-backed behaviour:

* rows come from the persistent ReadingListStore (SQLite), never synthetic rows
* status / symbol / tag filters apply
* ``article_count == len(articles)``
* methodology + field_dictionary present
* empty store -> status="empty", articles=[], warning (no placeholder row)
* store I/O failure -> status="provider_unavailable" graceful shape

No live network is required — the store is local SQLite, isolated by the
session-scoped SHOWME_HOME fixture in conftest — so these run cleanly offline.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.news.read import READFunction
from showme.engine.services.reading_list_store import ReadingListStore, SavedArticle

_OK_SET = {"ok", "empty"}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_store():
    """Ensure each test starts with an empty reading list (shared on-disk DB)."""
    ReadingListStore().clear()
    yield
    ReadingListStore().clear()


def _seed() -> None:
    store = ReadingListStore()
    store.save(
        SavedArticle(
            article_id="",
            url="https://news.example/aapl-beat",
            title="Apple posts record services revenue",
            source="news.example",
            published_utc="2026-05-30T12:00:00Z",
            matched_symbol="AAPL",
            tags=["earnings", "tech"],
            status="unread",
        )
    )
    store.save(
        SavedArticle(
            article_id="",
            url="https://news.example/msft-cloud",
            title="Microsoft cloud growth accelerates",
            source="news.example",
            published_utc="2026-05-29T09:00:00Z",
            matched_symbol="MSFT",
            tags=["cloud"],
            status="in_progress",
        )
    )


def test_read_returns_saved_rows_not_placeholder():
    _seed()
    res = _run(READFunction().execute())
    data = res.data

    assert res.code == "READ"
    assert data["status"] in _OK_SET
    assert data["status"] == "ok"
    # rows are real saved-store rows, not the old watchlist_cache placeholder
    assert len(data["rows"]) == 2
    titles = {r["title"] for r in data["rows"]}
    assert "Apple posts record services revenue" in titles
    # the old garbage never had real publisher domains or "watchlist brief"
    assert all("watchlist brief" not in (r["title"] or "").lower() for r in data["rows"])
    assert {r["source"] for r in data["rows"]} == {"news.example"}
    # every row carries a stable store id (semantic: every_article_has_store_id)
    assert all(r.get("article_id") for r in data["rows"])
    # honest provider name, not the old "watchlist_cache" constant
    assert res.sources == ["internal_reading_list"]
    # methodology + field dictionary present per de-garbage contract
    assert data["methodology"] and "saved-articles store" in data["methodology"].lower()
    assert isinstance(data["field_dictionary"], dict) and data["field_dictionary"]


def test_read_article_count_matches_articles_length():
    _seed()
    data = _run(READFunction().execute()).data
    assert data["article_count"] == len(data["articles"])
    assert data["articles"] == data["rows"]


def test_read_status_filter_applies():
    _seed()
    data = _run(READFunction().execute(status=["unread"])).data
    assert data["rows"]
    assert all(r["status"] == "unread" for r in data["rows"])


def test_read_symbol_filter_applies():
    _seed()
    fn = READFunction()
    # `symbols` alias and `watchlist` should behave identically
    by_symbols = _run(fn.execute(symbols="MSFT")).data
    by_watchlist = _run(fn.execute(watchlist=["MSFT"])).data
    assert by_symbols["article_count"] == by_watchlist["article_count"] == 1
    assert all(r["matched_symbol"] == "MSFT" for r in by_symbols["rows"])


def test_read_tag_filter_applies():
    _seed()
    data = _run(READFunction().execute(tags=["cloud"])).data
    assert data["article_count"] == 1
    assert data["rows"][0]["matched_symbol"] == "MSFT"


def test_read_empty_store_returns_empty_not_placeholder():
    res = _run(READFunction().execute())
    data = res.data
    assert data["status"] == "empty"
    assert data["status"] in _OK_SET
    assert data["rows"] == []
    assert data["articles"] == []
    assert data["article_count"] == 0
    # warning explains the empty state; no synthetic placeholder row appears
    assert any("empty" in w.lower() for w in res.warnings)
    # cards / methodology still present (honest shape, no fabricated headlines)
    assert data["methodology"]
    assert data["cards"]["article_count"] == 0


def test_read_counts_reflect_full_queue():
    _seed()
    # filter to only unread, but unread_count should reflect the WHOLE queue
    data = _run(READFunction().execute(status=["unread"])).data
    assert data["unread_count"] == 1
    assert data["in_progress_count"] == 1


def test_read_store_failure_is_graceful_provider_unavailable():
    """If the store raises on read, READ must degrade — never crash or fabricate."""

    class _Boom:
        def list(self, **_kwargs):
            raise OSError("disk gone")

        def counts(self):
            raise OSError("disk gone")

    class _Deps:
        reading_list_store = _Boom()

    fn = READFunction(_Deps())
    res = _run(fn.execute())
    data = res.data
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert data["articles"] == []
    assert res.sources == ["no_live_source"]
    assert res.warnings
    assert data["methodology"]
    assert data["next_actions"]
