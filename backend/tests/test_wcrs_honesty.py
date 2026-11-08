"""WCRS honesty regressions (wb1-g10).

Network-free: every provider / fetcher the matrix can reach is replaced by a
spy, so a test fails loudly if a live tier is called when it must not be.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.fx import _funcs as fx
from showme.engine.functions.fx._funcs import WCRSFunction


def _run(coro):
    return asyncio.run(coro)


def _spy_live_tiers(monkeypatch, calls: list) -> None:
    async def _frankfurter(base, quotes, **kwargs):  # noqa: ARG001
        calls.append(("frankfurter", base))
        return {q: 1.0 for q in quotes}, "2026-11-06"

    async def _history(fn, symbol, params):  # noqa: ARG001
        calls.append(("history", symbol))
        return [], None

    monkeypatch.setattr(fx, "fetch_frankfurter_rates_dated", _frankfurter)
    monkeypatch.setattr(fx, "_history_rows", _history)


# ── WCRS#3: explicit live_fx=false must switch every live tier off ────


def test_wcrs_live_fx_false_disables_every_live_tier(monkeypatch) -> None:
    calls: list = []
    _spy_live_tiers(monkeypatch, calls)

    result = _run(WCRSFunction(deps=FunctionDeps()).execute(live_fx=False))

    assert calls == [], f"live_fx=false must not reach any live tier: {calls}"
    assert result.data["source_mode"] == "reference_cross_rate_matrix"


def test_wcrs_default_still_reaches_the_live_tiers(monkeypatch) -> None:
    """Guard against a vacuous test: with no opt-out the live path runs."""
    calls: list = []
    _spy_live_tiers(monkeypatch, calls)

    _run(WCRSFunction(deps=FunctionDeps()).execute())

    assert any(kind == "frankfurter" for kind, _ in calls)


# ── WCRS#1 / WCRS#4: the ECB daily fix is delayed, dated, never "live" ──


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.urls: list[str] = []

    async def get(self, url, **kwargs):  # noqa: ARG002
        self.urls.append(url)
        return _FakeResp(self._payload)


def test_frankfurter_dated_helper_returns_the_fix_date() -> None:
    from showme.engine.functions.fx._frankfurter import (
        fetch_frankfurter_rates_dated,
        reset_frankfurter_cache,
    )

    reset_frankfurter_cache()
    client = _FakeClient({"amount": 1.0, "base": "EUR", "date": "2026-11-06", "rates": {"USD": 1.1234}})
    rates, as_of = _run(fetch_frankfurter_rates_dated("EUR", ["USD"], client=client))
    assert rates == {"USD": 1.1234}
    assert as_of == "2026-11-06"
    reset_frankfurter_cache()


def test_wcrs_ecb_fix_is_labelled_delayed_with_its_date(monkeypatch) -> None:
    async def _fix(base, quotes, **kwargs):  # noqa: ARG001
        return {q: 1.1165 for q in quotes}, "2026-11-06"

    async def _no_history(fn, symbol, params):  # noqa: ARG001
        return [], None

    monkeypatch.setattr(fx, "fetch_frankfurter_rates_dated", _fix)
    monkeypatch.setattr(fx, "_history_rows", _no_history)

    result = _run(WCRSFunction(deps=FunctionDeps()).execute(bases="EUR", quotes="USD,GBP"))
    data = result.data

    assert data["source_mode"] == "official_daily_fix"
    assert not data["source_mode"].startswith("live_"), "a daily ECB fix must never claim live"
    assert data["as_of"] == "2026-11-06"
    assert all(row["as_of"] == "2026-11-06" for row in data["rows"])
    assert result.metadata["data_mode"] == "delayed_reference"
    assert result.metadata["as_of"] == "2026-11-06"
    assert any("2026-11-06" in w for w in result.warnings)
    assert result.sources == ["frankfurter_ecb"]


def test_wcrs_reference_matrix_carries_its_vintage(monkeypatch) -> None:
    async def _none(base, quotes, **kwargs):  # noqa: ARG001
        return None, None

    async def _no_history(fn, symbol, params):  # noqa: ARG001
        return [], None

    monkeypatch.setattr(fx, "fetch_frankfurter_rates_dated", _none)
    monkeypatch.setattr(fx, "_history_rows", _no_history)

    result = _run(WCRSFunction(deps=FunctionDeps()).execute(bases="EUR", quotes="USD,GBP"))
    assert result.data["source_mode"] == "reference_cross_rate_matrix"
    assert result.data["as_of"] == fx._REFERENCE_AS_OF
    assert result.metadata["reference_as_of"] == fx._REFERENCE_AS_OF


# ── WCRS#2: no constructed bid/ask/spread without a real bid/ask source ──


def test_wcrs_never_constructs_a_bid_ask_spread(monkeypatch) -> None:
    """bid = mid*0.9999 / ask = mid*1.0001 made every pair's spread the same
    0.02% of the rate (EURTRY 111.991 pips). No keyless bid/ask source is
    wired, so bid, ask and spread_pips must be null, not invented."""

    async def _none(base, quotes, **kwargs):  # noqa: ARG001
        return None, None

    async def _no_history(fn, symbol, params):  # noqa: ARG001
        return [], None

    monkeypatch.setattr(fx, "fetch_frankfurter_rates_dated", _none)
    monkeypatch.setattr(fx, "_history_rows", _no_history)

    result = _run(WCRSFunction(deps=FunctionDeps()).execute(bases="EUR", quotes="USD,TRY"))
    rows = result.data["rows"]
    assert rows
    for row in rows:
        assert row["bid"] is None, row
        assert row["ask"] is None, row
        assert row["spread_pips"] is None, row
        assert row["rate"] > 0
    assert "spread" in result.data["field_dictionary"]["spread_pips"].lower()
