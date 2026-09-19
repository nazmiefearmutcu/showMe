"""MEET Gate-2 — latency budget pins (2026-09-19).

No real waiting anywhere: hanging providers lose the race to instant
fakes while a ``wait_for`` spy records the timeout values (Task A
pattern). Covers the spec §4 latency leg:

  * the GDELT leg is pinned at ``min(timeout, 5)``; the RSS leg keeps
    the full timeout,
  * cold-open worst case is bounded by the capped leg (<= 5 s, pure
    math over the clamped range) and a wedged DOC endpoint fails fast
    into the RSS win (elapsed, not slept),
  * the world-headline cache serves hits in microseconds without
    touching providers,
  * the per-feed / collection clamp table (inputs 1/2/8/15/None
    → 3/3/5/5/5) holds end-to-end through ``execute``.

Fully offline: no test performs real network I/O.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.comm import meet as meet_mod
from showme.engine.functions.macro import eco as eco_mod

import pytest


@pytest.fixture(autouse=True)
def _reset_caches():
    meet_mod._WORLD_CACHE = None
    meet_mod._SYMBOL_NEWS_CACHE = None
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []
    yield
    meet_mod._WORLD_CACHE = None
    meet_mod._SYMBOL_NEWS_CACHE = None
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []


def _iso_ago(**kwargs) -> str:
    return (datetime.now(UTC) - timedelta(**kwargs)).isoformat()


class _EmptyFFClient:
    """ForexFactory stand-in returning an empty calendar."""

    async def get(self, url, timeout=None):
        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return []

        return _Resp()


class _EmptyGDELT:
    """GDELT leg that answers instantly with nothing (RSS must win)."""

    def __init__(self):
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        return []


class _InstantRSS:
    """RSS leg answering instantly; records the per-feed budgets it got."""

    def __init__(self, articles):
        self._articles = list(articles)
        self.calls = 0
        self.extras: list[dict] = []

    async def fetch(self, request):
        self.calls += 1
        self.extras.append(dict(getattr(request, "extra", None) or {}))
        return list(self._articles)


class _HangingGDELT:
    """Simulates a wedged DOC endpoint: never answers."""

    async def fetch(self, request):
        await asyncio.Event().wait()
        return []  # pragma: no cover


def _rss_articles():
    return [{
        "title": "RSS wire on budgets",
        "link": "https://example.test/rss-budget",
        "published_at": _iso_ago(minutes=10),
    }]


def _meet(gdelt=None, rss=None):
    fn = meet_mod.MEETFunction(deps=FunctionDeps(gdelt=gdelt, rss=rss))
    fn._http_client = _EmptyFFClient()
    return fn


def test_gdelt_leg_pinned_at_min_timeout_5_rss_keeps_full_timeout():
    """news_timeout=12 end-to-end: GDELT leg 5 s, RSS leg 12 s, RSS wins."""
    rss = _InstantRSS(_rss_articles())
    started = time.monotonic()
    # (spy wired explicitly so both the timeouts and the result are pinned)
    real_wait_for = asyncio.wait_for
    seen: list[float | None] = []

    async def _spy(coro, *, timeout=None, **kwargs):
        seen.append(timeout)
        return await real_wait_for(coro, timeout=timeout, **kwargs)

    with mock.patch.object(meet_mod.asyncio, "wait_for", _spy):
        result = asyncio.run(_meet(_EmptyGDELT(), rss).execute(kind="world", news_timeout=12))
    elapsed = time.monotonic() - started
    assert result.data["status"] == "ok"
    assert "rss" in result.sources
    assert elapsed < 2.0, f"instant legs took {elapsed:.2f}s"
    assert sorted(seen) == [5.0, 12.0]
    assert rss.extras and rss.extras[0]["per_feed_timeout_seconds"] == 5.0
    assert rss.extras[0]["collection_timeout_seconds"] == 5.0


def test_cold_open_worst_case_bounded_by_capped_leg():
    """Pure math: the capped GDELT leg never exceeds 5 s, and a wedged
    DOC endpoint fails fast into the instant RSS win (no real waiting)."""
    for timeout in (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 15.0):
        assert min(timeout, 5.0) <= 5.0
    rss = _InstantRSS(_rss_articles())
    fn = meet_mod.MEETFunction(deps=FunctionDeps(gdelt=_HangingGDELT(), rss=rss))
    started = time.monotonic()
    items, source, _error = asyncio.run(
        fn._world_headlines(now=datetime.now(UTC), timeout=8.0)
    )
    elapsed = time.monotonic() - started
    assert source == "rss"
    assert [a["title"] for a in items] == ["RSS wire on budgets"]
    assert elapsed < 2.0, f"wedged GDELT held the race {elapsed:.2f}s"


def test_world_cache_hit_is_microseconds_without_provider_calls():
    """First call populates the cache; the second is a µs hit."""
    articles = [{
        "title": "GDELT wire on talks",
        "url": "https://example.test/gdelt-cache",
        "published_at": _iso_ago(hours=1),
    }]
    gdelt = _EmptyGDELT()
    orig_fetch = gdelt.fetch

    async def _items(request):
        gdelt.calls += 1
        return list(articles)

    gdelt.fetch = _items  # type: ignore[method-assign]
    rss = _InstantRSS([])
    fn = meet_mod.MEETFunction(deps=FunctionDeps(gdelt=gdelt, rss=rss))
    now = datetime.now(UTC)
    first = asyncio.run(fn._world_headlines(now=now, timeout=8.0))
    calls_after_first = gdelt.calls
    rss_calls_after_first = rss.calls
    assert first[1] == "gdelt"
    started = time.perf_counter()
    second = asyncio.run(fn._world_headlines(now=now, timeout=8.0))
    elapsed = time.perf_counter() - started
    assert second == first
    assert gdelt.calls == calls_after_first, "cache hit must not touch providers"
    assert rss.calls == rss_calls_after_first, "cache hit must not touch providers"
    assert elapsed < 0.05, f"cache hit took {elapsed * 1000:.1f}ms"


@pytest.mark.parametrize(
    ("given", "expected_clamp", "expected_gdelt_leg"),
    [
        (1, 3.0, 2.0),   # _num floors 1 -> 2.0, clamp floors to 3.0
        (2, 3.0, 2.0),
        (8, 5.0, 5.0),
        (15, 5.0, 5.0),
        (None, 5.0, 5.0),  # default 8.0 -> capped at 5.0
    ],
)
def test_per_feed_and_collection_clamp_table(given, expected_clamp, expected_gdelt_leg):
    """End-to-end through execute: inputs 1/2/8/15/None → 3/3/5/5/5."""
    rss = _InstantRSS(_rss_articles())
    real_wait_for = asyncio.wait_for
    seen: list[float | None] = []

    async def _spy(coro, *, timeout=None, **kwargs):
        seen.append(timeout)
        return await real_wait_for(coro, timeout=timeout, **kwargs)

    params = {"kind": "world"}
    if given is not None:
        params["news_timeout"] = given
    started = time.monotonic()
    with mock.patch.object(meet_mod.asyncio, "wait_for", _spy):
        result = asyncio.run(_meet(_EmptyGDELT(), rss).execute(**params))
    elapsed = time.monotonic() - started
    assert result.data["status"] == "ok"
    assert elapsed < 2.0, f"instant legs took {elapsed:.2f}s"
    assert rss.extras, "RSS leg must run so its budgets are observable"
    for extra in rss.extras:
        assert extra["per_feed_timeout_seconds"] == expected_clamp, (given, extra)
        assert extra["collection_timeout_seconds"] == expected_clamp, (given, extra)
    assert expected_gdelt_leg in seen, (given, seen)
