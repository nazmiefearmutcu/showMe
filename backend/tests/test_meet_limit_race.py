"""MEET — limit-after-window + GDELT/RSS race pins (2026-09-17).

Regression cover for two owner-observed bugs:
  * a small ``limit`` truncated the week-chronological feed BEFORE windowing,
    eating the entire upcoming section (``limit=5`` -> 0 upcoming);
  * the serial GDELT-timeout + RSS-fallback chain cost ~13 s on a cold cache.

Fully offline: no test performs real network I/O.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.comm import meet as meet_mod
from showme.engine.functions.macro import eco as eco_mod


@pytest.fixture(autouse=True)
def _reset_caches():
    meet_mod._WORLD_CACHE = None
    meet_mod._gdelt_429_until = 0.0
    meet_mod._SYMBOL_NEWS_CACHE = None
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []
    yield
    meet_mod._WORLD_CACHE = None
    meet_mod._gdelt_429_until = 0.0
    meet_mod._SYMBOL_NEWS_CACHE = None
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []


def _run(coro):
    return asyncio.run(coro)


def _iso_in(offset: timedelta) -> str:
    return (datetime.now(UTC) + offset).isoformat()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _OldFirstFFClient:
    """12 stale rows first, then 2 upcoming — feed order is old-first."""

    def __init__(self):
        rows = [
            {
                "title": f"Old print {i}",
                "country": "USD",
                "date": _iso_in(timedelta(hours=-(72 + i))),
                "impact": "Low",
                "forecast": "",
                "actual": "",
                "previous": "",
            }
            for i in range(12)
        ]
        rows += [
            {
                "title": "Soon print A",
                "country": "USD",
                "date": _iso_in(timedelta(hours=5)),
                "impact": "Medium",
                "forecast": "",
                "actual": "",
                "previous": "",
            },
            {
                "title": "Soon print B",
                "country": "USD",
                "date": _iso_in(timedelta(hours=6)),
                "impact": "Medium",
                "forecast": "",
                "actual": "",
                "previous": "",
            },
        ]
        self._payload = rows

    async def get(self, url, timeout=None):
        return _FakeResp(self._payload)


class _InstantNews:
    def __init__(self, articles):
        self._articles = articles
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1
        return list(self._articles)


class _SlowGDELT(_InstantNews):
    async def fetch(self, request):
        self.calls += 1
        await asyncio.sleep(5)
        return list(self._articles)


def _meet(deps=None, client=None):
    fn = meet_mod.MEETFunction(deps=deps or FunctionDeps())
    if client is not None:
        fn._http_client = client
    return fn


def test_small_limit_keeps_upcoming_first():
    """limit=10 over an old-first feed must still surface the 2 upcoming."""
    result = _run(
        _meet(FunctionDeps(), _OldFirstFFClient()).execute(
            mode="calendar", limit=10, days_back=30
        )
    )
    assert result.data["status"] == "ok"
    assert result.data["upcoming_count"] == 2
    assert [r["title"] for r in result.data["upcoming"]] == [
        "Soon print A",
        "Soon print B",
    ]
    # Upcoming-first priority fills the rest of the budget with past rows.
    assert result.data["past_count"] == 8
    assert len(result.data["rows"]) == 10


def test_world_race_fast_rss_wins_over_stalled_gdelt():
    """A stalled GDELT must not hold the pane hostage (was ~13 s serial)."""
    gdelt = _SlowGDELT([
        {"title": "Stale wire", "url": "https://example.test/slow",
         "published_at": _iso_in(timedelta(hours=-3))}
    ])
    rss = _InstantNews([
        {"title": "Fresh wire Russell budgets pass", "link": "https://example.test/f",
         "published_at": _iso_in(timedelta(minutes=-10))}
    ])
    started = time.monotonic()
    result = _run(
        _meet(FunctionDeps(gdelt=gdelt, rss=rss), _OldFirstFFClient()).execute(
            kind="world", news_timeout=2.0
        )
    )
    elapsed = time.monotonic() - started
    assert "rss" in result.sources
    assert "gdelt" not in result.sources
    assert elapsed < 2.0, f"race took {elapsed:.2f}s, laggard was not cut off"


def test_world_race_gdelt_keeps_priority_when_both_ready():
    """Two instantly-ready legs must deterministically prefer GDELT."""
    for _ in range(5):
        meet_mod._WORLD_CACHE = None
        meet_mod._gdelt_429_until = 0.0
        gdelt = _InstantNews([
            {"title": "GDELT wire on talks", "url": "https://example.test/g",
             "published_at": _iso_in(timedelta(hours=-1))}
        ])
        rss = _InstantNews([
            {"title": "RSS wire on budgets", "link": "https://example.test/r",
             "published_at": _iso_in(timedelta(minutes=-30))}
        ])
        result = _run(
            _meet(FunctionDeps(gdelt=gdelt, rss=rss), _OldFirstFFClient()).execute(
                kind="world"
            )
        )
        assert "gdelt" in result.sources


def test_world_race_slow_empty_gdelt_does_not_block_rss():
    """Slow-but-empty GDELT is cancelled; RSS wins with no gdelt warning."""
    gdelt = _SlowGDELT([])
    rss = _InstantNews([
        {"title": "RSS wire on budgets", "link": "https://example.test/r2",
         "published_at": _iso_in(timedelta(minutes=-30))}
    ])
    result = _run(
        _meet(FunctionDeps(gdelt=gdelt, rss=rss), _OldFirstFFClient()).execute(
            kind="world", news_timeout=2.0
        )
    )
    assert "rss" in result.sources
    assert not any("gdelt" in w for w in result.warnings)
