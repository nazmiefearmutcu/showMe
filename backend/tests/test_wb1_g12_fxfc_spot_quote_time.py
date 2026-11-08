"""FXFC#4: the yfinance spot carries the upstream quote time and a stale flag.

The adapter used to stamp ``utcnow()`` on every quote, so the fetch time was
presented as the quote time. The chart path now reads ``meta.regularMarketTime``
and marks the timestamp's provenance; FXFC reports the quote time, its age and
a status (fresh / stale / off_session / quote_time_unavailable).

Network is patched: no provider is called.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.quote import Quote
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter
from showme.engine.functions.fx import _funcs as fx
from showme.engine.functions.fx._funcs import FXFCFunction


def _run(coro):
    return asyncio.run(coro)


def _closes(n: int = 400, start: float = 1.10, step: float = 0.002) -> list[float]:
    out = [start]
    for i in range(1, n):
        sign = 1.0 if (i // 3) % 2 == 0 else -1.0
        out.append(out[-1] * math.exp(sign * step))
    return out


@pytest.fixture
def live_history(monkeypatch):
    async def _close_series(fn, pair, params):  # noqa: ARG001
        return _closes()

    monkeypatch.setattr(fx, "_close_series", _close_series)


class _FakeYF:
    """Stands in for the yfinance data source: returns one fixed Quote."""

    def __init__(self, quote: Quote):
        self._quote = quote

    async def fetch(self, request):  # noqa: ARG002
        return self._quote


def _quote(ts: datetime, source: str = "upstream_market_time") -> Quote:
    return Quote(
        symbol="EURUSD=X",
        timestamp=ts,
        last=1.1143,
        source="yfinance",
        timestamp_source=source,
    )


def _execute(quote: Quote, now: datetime):  # noqa: ARG001 - now is pinned by fixed_now
    fn = FXFCFunction(deps=FunctionDeps(yfinance=_FakeYF(quote)))
    return _run(fn.execute(pair="EURUSD", r_base=0.035, r_quote=0.045))


@pytest.fixture
def fixed_now(monkeypatch):
    def _set(when: datetime):
        monkeypatch.setattr(fx, "_fxfc_now", lambda: when)

    return _set


# ── adapter: quote time comes from upstream, not from utcnow() ──────────


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeChart:
    def __init__(self, payload: dict):
        self._payload = payload

    async def get(self, url, params=None):  # noqa: ARG002
        return _FakeResponse(self._payload)


def _chart_payload(meta: dict) -> dict:
    return {"chart": {"result": [{"meta": meta}], "error": None}}


def test_adapter_chart_quote_uses_upstream_market_time(monkeypatch):
    epoch = int(datetime(2026, 11, 6, 21, 59, tzinfo=timezone.utc).timestamp())
    adapter = YFinanceAdapter()

    async def _client():
        return _FakeChart(_chart_payload({"regularMarketPrice": 1.1143, "regularMarketTime": epoch}))

    monkeypatch.setattr(adapter, "_chart_client_", _client)
    quote = _run(adapter._fetch_chart_quote("EURUSD=X"))
    assert quote.last == 1.1143
    assert quote.timestamp == datetime(2026, 11, 6, 21, 59, tzinfo=timezone.utc)
    assert quote.timestamp_source == "upstream_market_time"


def test_adapter_chart_quote_without_market_time_is_marked_fetch_time(monkeypatch):
    adapter = YFinanceAdapter()

    async def _client():
        return _FakeChart(_chart_payload({"regularMarketPrice": 1.1143}))

    monkeypatch.setattr(adapter, "_chart_client_", _client)
    quote = _run(adapter._fetch_chart_quote("EURUSD=X"))
    assert quote.timestamp_source == "fetch_time"


# ── FXFC: quote time, age and status ────────────────────────────────────


def test_friday_close_quote_fetched_sunday_is_stale(live_history, fixed_now):
    """The reported case: last Friday print, fetched Sunday before the open."""
    fixed_now(datetime(2026, 11, 8, 0, 7, tzinfo=timezone.utc))
    quote = _quote(datetime(2026, 11, 6, 21, 59, tzinfo=timezone.utc))
    result = _execute(quote, datetime(2026, 11, 8, 0, 7, tzinfo=timezone.utc))
    assert result.data["spot_quote_status"] == "stale"
    assert result.data["spot_quote_time"] == "2026-11-06T21:59:00+00:00"
    assert result.data["spot_quote_age_minutes"] > 60 * 24
    assert any("stale" in w for w in result.warnings), result.warnings


def test_recent_weekday_quote_is_fresh(live_history, fixed_now):
    now = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)
    fixed_now(now)
    quote = _quote(datetime(2026, 11, 10, 13, 50, tzinfo=timezone.utc))
    result = _execute(quote, now)
    assert result.data["spot_quote_status"] == "fresh"
    assert result.data["spot_quote_age_minutes"] == 10.0
    assert all("stale" not in w for w in result.warnings)


def test_quote_outside_session_is_off_session(live_history, fixed_now):
    now = datetime(2026, 11, 8, 0, 30, tzinfo=timezone.utc)
    fixed_now(now)
    quote = _quote(datetime(2026, 11, 8, 0, 5, tzinfo=timezone.utc))
    result = _execute(quote, now)
    assert result.data["spot_quote_status"] == "off_session"
    assert any("outside the approximate FX session" in w for w in result.warnings), result.warnings


def test_fetch_time_only_quote_reports_no_quote_time(live_history, fixed_now):
    """A quote without an upstream time must not present fetch time as quote time."""
    now = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)
    fixed_now(now)
    quote = _quote(now, source="fetch_time")
    result = _execute(quote, now)
    assert result.data["spot_quote_status"] == "quote_time_unavailable"
    assert result.data["spot_quote_time"] is None
    assert result.data["spot_quote_age_minutes"] is None
    assert any("no upstream quote time" in w for w in result.warnings), result.warnings


def test_non_yfinance_spot_is_not_applicable(monkeypatch, live_history, fixed_now):
    now = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)
    fixed_now(now)

    async def _spot(fn, pair, params, quote_info=None):  # noqa: ARG001
        return 1.1165, "frankfurter_ecb", "live_official"

    monkeypatch.setattr(fx, "_resolve_spot", _spot)
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045))
    assert result.data["spot_quote_status"] == "not_applicable"
    assert result.data["spot_quote_time"] is None
