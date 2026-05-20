"""Regression: NI must unwrap TOPFunction's dict result back to a list.

FUNC-10 P1 changed TOPFunction to return ``{"items": [...], "alerts": [...],
"status": "ok"}`` instead of a bare ``list``. The NI fallback in
``backend/showme/engine/functions/news/ni.py`` then assigned ``top.data``
directly to ``results`` and passed it to ``enrich_articles``, which iterates
``items`` and rejects anything that's not a ``dict``. The result: NI silently
returned 0 items whenever RSS and GDELT were both empty but TOP had data.

This pins the dict-unwrap fix so a future refactor can't reintroduce the
silent-empty regression.
"""
from __future__ import annotations

from typing import Any

from showme.engine.core.base_data_source import DataRequest
from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.functions.news.ni import NIFunction


class _StubRSS:
    """Empty RSS source so NI is forced to fall back to TOP."""

    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        return []


class _StubGdelt:
    """Empty GDELT source so the gdelt branch also returns nothing."""

    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        return []


def _build_deps(monkeypatch) -> FunctionDeps:
    deps = FunctionDeps()
    deps.rss = _StubRSS()
    deps.gdelt = _StubGdelt()
    return deps


async def test_ni_unwraps_top_dict_result(monkeypatch) -> None:
    """When RSS/GDELT return nothing, NI falls back to TOP. TOP now returns
    a wrapped ``{items, alerts, status}`` dict — NI must unwrap before
    handing it to ``enrich_articles``."""
    sample_article = {
        "title": "Federal Reserve cuts rates by 50 bps",
        "summary": "FOMC delivered an outsized cut citing labour weakness.",
        "source": "Reuters",
        "published_at": "2026-05-17T14:00:00+00:00",
        "url": "https://example.test/fed-cut",
    }

    async def fake_top_execute(self, instrument=None, **params):  # type: ignore[no-untyped-def]
        # Mirror the FUNC-10 P1 envelope shape — a dict, not a list.
        return FunctionResult(
            code="TOP",
            instrument=None,
            data={
                "items": [sample_article],
                "alerts": [],
                "status": "ok",
            },
            sources=["rss"],
        )

    monkeypatch.setattr(
        "showme.engine.functions.news.top.TOPFunction.execute",
        fake_top_execute,
    )

    ni = NIFunction(_build_deps(monkeypatch))
    # threshold=0 so enrich_articles can't filter the seeded article out for
    # being below the importance gate — the test is about the dict-unwrap,
    # not the scoring math.
    result = await ni.execute(topic="FED", live=True, news_timeout=2, threshold=0, limit=5)

    assert isinstance(result.data, dict), "NI result must use the wrapped dict shape"
    items = result.data.get("items") or []
    assert len(items) >= 1, (
        "NI must unwrap TOP's dict and surface the article; got empty list "
        "which means the dict-vs-list shape mismatch regressed."
    )
    assert items[0].get("title") == sample_article["title"]
    # TOP source should propagate so the UI can credit the provider.
    assert "rss" in (result.sources or [])


async def test_ni_still_handles_top_list_for_back_compat(monkeypatch) -> None:
    """An older TOPFunction stub that returns a bare list must keep working."""
    sample_article = {
        "title": "ECB holds rates",
        "summary": "Council unchanged at 4.0% — guidance hawkish.",
        "source": "ECB",
        "published_at": "2026-05-17T13:30:00+00:00",
        "url": "https://example.test/ecb-hold",
    }

    async def fake_top_execute(self, instrument=None, **params):  # type: ignore[no-untyped-def]
        return FunctionResult(
            code="TOP",
            instrument=None,
            data=[sample_article],
            sources=["rss"],
        )

    monkeypatch.setattr(
        "showme.engine.functions.news.top.TOPFunction.execute",
        fake_top_execute,
    )

    ni = NIFunction(_build_deps(monkeypatch))
    result = await ni.execute(topic="EARN", live=True, news_timeout=2, threshold=0, limit=5)

    items = result.data.get("items") or []
    assert len(items) >= 1
    assert items[0].get("title") == sample_article["title"]
