"""Regression (2026-09-17): NI must keep the curated topic mapping even when
the UI mirrors the topic text into ``query``.

The pane sends ``topicParams = {topic: "MACRO", query: "MACRO"}``. The old
``query = explicit_query or _TOPIC_QUERIES.get(topic, topic)`` took the
mirrored text as an explicit query, so the backend searched for the literal
word "macro" — a day's market headlines contain no such word and the pane
rendered "No headlines yet" forever. A query that merely repeats the topic
must keep the mapped boolean query; a genuinely different query still wins.
"""
from __future__ import annotations

from typing import Any

import pytest

from showme.engine.core.base_data_source import DataRequest
from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.functions.news.ni import NIFunction, _TOPIC_QUERIES


class _CapturingRSS:
    def __init__(self) -> None:
        self.requests: list[DataRequest] = []

    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        self.requests.append(request)
        return []


class _StubGdelt:
    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        return []


def _deps(rss: _CapturingRSS) -> FunctionDeps:
    deps = FunctionDeps()
    deps.rss = rss
    deps.gdelt = _StubGdelt()
    return deps


def _captured_query(rss: _CapturingRSS) -> str:
    assert rss.requests, "RSS adapter was never called"
    return str((rss.requests[0].extra or {}).get("query") or "")


@pytest.fixture(autouse=True)
def _no_top_fallback(monkeypatch):
    """Keep the tests offline: TOP is the third fallback and hits the network."""

    async def _empty_top(self, instrument=None, **params):  # type: ignore[no-untyped-def]
        return FunctionResult(
            code="TOP", instrument=None,
            data={"items": [], "alerts": [], "status": "empty"},
            sources=[],
        )

    monkeypatch.setattr(
        "showme.engine.functions.news.top.TOPFunction.execute",
        _empty_top,
    )


async def test_query_equal_to_topic_keeps_mapped_query() -> None:
    rss = _CapturingRSS()
    ni = NIFunction(_deps(rss))
    await ni.execute(topic="MACRO", query="MACRO", live=True,
                     news_timeout=2, limit=5)
    assert _captured_query(rss) == _TOPIC_QUERIES["MACRO"]


async def test_topic_only_still_maps() -> None:
    rss = _CapturingRSS()
    ni = NIFunction(_deps(rss))
    await ni.execute(topic="FED", live=True, news_timeout=2, limit=5)
    assert _captured_query(rss) == _TOPIC_QUERIES["FED"]


async def test_custom_query_still_wins() -> None:
    rss = _CapturingRSS()
    ni = NIFunction(_deps(rss))
    await ni.execute(topic="FED", query="powell speech", live=True,
                     news_timeout=2, limit=5)
    assert _captured_query(rss) == "powell speech"


async def test_custom_topic_without_mapping_uses_text() -> None:
    rss = _CapturingRSS()
    ni = NIFunction(_deps(rss))
    await ni.execute(topic="WHEAT PRICES", query="WHEAT PRICES", live=True,
                     news_timeout=2, limit=5)
    assert _captured_query(rss) == "WHEAT PRICES"
