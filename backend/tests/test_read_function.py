"""Tests for the READ (Reading List) function.

READ is backed by the persistent saved-articles store (ReadingListStore). The
legacy behaviour returned a hardcoded "watchlist brief" placeholder that
ignored the store; that path was removed in the de-garbage pass. These tests
pin the store-backed contract (see also test_degarbage_news_read.py).
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.news.read import READFunction
from showme.engine.services.reading_list_store import ReadingListStore, SavedArticle


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_store():
    ReadingListStore().clear()
    yield
    ReadingListStore().clear()


def test_read_reads_from_store():
    ReadingListStore().save(
        SavedArticle(
            article_id="",
            url="https://example.com/aapl",
            title="AAPL saved headline",
            source="example.com",
            matched_symbol="AAPL",
            status="unread",
        )
    )
    res = _run(READFunction().execute())
    assert res.code == "READ"
    data = res.data
    assert isinstance(data, dict)
    assert data["status"] == "ok"
    assert any(r.get("matched_symbol") == "AAPL" for r in data["rows"])
    assert res.sources == ["internal_reading_list"]


def test_read_symbols_param_filters_store():
    store = ReadingListStore()
    store.save(SavedArticle(article_id="", url="https://example.com/tsla",
                            title="TSLA saved headline", source="example.com",
                            matched_symbol="TSLA", status="unread"))
    store.save(SavedArticle(article_id="", url="https://example.com/aapl2",
                            title="AAPL saved headline 2", source="example.com",
                            matched_symbol="AAPL", status="unread"))
    res = _run(READFunction().execute(symbols="TSLA"))
    data = res.data
    assert data["article_count"] == 1
    assert all(r.get("matched_symbol") == "TSLA" for r in data["rows"])


def test_read_empty_store_no_placeholder():
    res = _run(READFunction().execute())
    data = res.data
    assert data["status"] == "empty"
    assert data["rows"] == []
    assert any("empty" in w.lower() for w in res.warnings)
