"""SEC-12: Brave/DDG/Bing 429 must bump per-engine ban; throttle must not
eat the route timeout.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from showme import x_spontaneous as xs


@pytest.fixture(autouse=True)
def _fresh_throttle(monkeypatch):
    """Replace the module-level throttle with a fresh one per test."""
    fresh = xs._SearchEngineThrottle(min_interval=30.0, max_sleep=2.0)
    monkeypatch.setattr(xs, "_SEARCH_THROTTLE", fresh)
    yield fresh


def test_wait_slot_returns_true_when_no_wait(_fresh_throttle):
    """Fresh throttle (no prior call) returns True without sleeping."""
    t0 = time.monotonic()
    ok = _fresh_throttle.wait_slot("brave")
    elapsed = time.monotonic() - t0
    assert ok is True
    assert elapsed < 0.1


def test_wait_slot_caps_sleep_and_returns_false(monkeypatch, _fresh_throttle):
    """Within min_interval, sleep is capped at max_sleep and returns False."""
    _fresh_throttle._last_call["brave"] = xs._now()  # just called
    slept: list[float] = []
    monkeypatch.setattr(xs.time, "sleep", lambda s: slept.append(s))

    ok = _fresh_throttle.wait_slot("brave")

    assert slept and slept[0] <= 2.0, f"sleep was {slept}, expected ≤ 2.0"
    assert ok is False, "wait_slot should return False when capped"


def test_ban_and_is_banned(_fresh_throttle):
    """ban() marks engine as rate-limited for at least 60s."""
    assert not _fresh_throttle.is_banned("brave")
    _fresh_throttle.ban("brave", 1.0)  # request 1s, floor is 60s
    assert _fresh_throttle.is_banned("brave")


def test_brave_429_triggers_ban_with_retry_after(_fresh_throttle):
    """HTTP 429 with Retry-After: 600 must ban brave for 600s."""
    scraper = xs.SpontaneousXScraper()
    fake_response = MagicMock()
    fake_response.status_code = 429
    fake_response.headers = {"Retry-After": "600"}
    fake_response.text = ""
    scraper._client = MagicMock()
    scraper._client.get.return_value = fake_response

    with pytest.raises(RuntimeError, match="429"):
        scraper._search_brave_syndication("AAPL", limit=10)

    assert _fresh_throttle.is_banned("brave")


def test_banned_engine_short_circuits_without_http(_fresh_throttle):
    """is_banned must skip the HTTP request entirely on the next call."""
    scraper = xs.SpontaneousXScraper()
    scraper._client = MagicMock()
    _fresh_throttle.ban("brave", 300.0)

    with pytest.raises(RuntimeError, match="banned"):
        scraper._search_brave_syndication("AAPL", limit=10)

    scraper._client.get.assert_not_called()


def test_ddg_and_bing_also_honor_429(_fresh_throttle):
    """Parallel ban behavior must apply to DDG and Bing too."""
    scraper = xs.SpontaneousXScraper()
    fake_response = MagicMock()
    fake_response.status_code = 429
    fake_response.headers = {}  # missing Retry-After → default 300s
    fake_response.text = ""
    scraper._client = MagicMock()
    scraper._client.get.return_value = fake_response
    scraper._client.post.return_value = fake_response

    with pytest.raises(RuntimeError, match="429"):
        scraper._search_ddg_syndication("AAPL", limit=10)
    assert _fresh_throttle.is_banned("ddg")

    with pytest.raises(RuntimeError, match="429"):
        scraper._search_bing_syndication("AAPL", limit=10)
    assert _fresh_throttle.is_banned("bing")


def test_throttle_does_not_eat_route_timeout(monkeypatch, _fresh_throttle):
    """End-to-end: search() must return within a few seconds even when all
    three engines have a fresh _last_call entry forcing throttle waits."""
    scraper = xs.SpontaneousXScraper()
    for eng in ("brave", "ddg", "bing"):
        _fresh_throttle._last_call[eng] = xs._now()

    # All requests fail (503) → search() falls through every engine.
    fake_response = MagicMock()
    fake_response.status_code = 503
    fake_response.text = ""
    fake_response.headers = {}
    scraper._client = MagicMock()
    scraper._client.get.return_value = fake_response
    scraper._client.post.return_value = fake_response

    t0 = time.monotonic()
    try:
        scraper.search("AAPL", limit=10)
    except Exception:
        pass
    elapsed = time.monotonic() - t0

    assert elapsed < 8.0, f"search took {elapsed:.1f}s — throttle eating budget"


def test_parse_retry_after_handles_missing_and_invalid():
    """_parse_retry_after returns 300s floor on missing/invalid input."""
    assert xs._parse_retry_after(None) == 300.0
    assert xs._parse_retry_after("") == 300.0
    assert xs._parse_retry_after("not-a-number") == 300.0
    # Valid numbers honored (with 60s floor).
    assert xs._parse_retry_after("120") == 120.0
    assert xs._parse_retry_after("30") == 60.0  # floored to 60
    assert xs._parse_retry_after("600") == 600.0
