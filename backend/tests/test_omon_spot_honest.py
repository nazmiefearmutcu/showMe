"""OMON#3 follow-up: no underlying spot must be an explicit state, never 100.

The chain fetch is patched at ``_fetch_chain_sync`` and the yfinance quote
adapter is a stub, so no network is used. When neither the caller, the chain
nor the quote adapter yields a spot, OMON must not price moneyness or deltas
on a placeholder anchor; it returns ``provider_unavailable`` with the reason.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative import omon as omon_mod
from showme.engine.functions.derivative.omon import OMONFunction, _resolve_spot


def _patch_chain(monkeypatch, *, spot):
    trade_ts = datetime.now(timezone.utc) - timedelta(minutes=5)
    calls = [
        {
            "strike": 740.0,
            "bid": 5.0,
            "ask": 5.2,
            "impliedVolatility": 0.18,
            "openInterest": 100,
            "volume": 10,
            "lastTradeDate": trade_ts,
        }
    ]
    puts = [
        {
            "strike": 730.0,
            "bid": 4.0,
            "ask": 4.2,
            "impliedVolatility": 0.20,
            "openInterest": 80,
            "volume": 5,
            "lastTradeDate": trade_ts,
        }
    ]

    def _fake_fetch(underlier, requested_expiry):  # noqa: ARG001
        return {
            "spot": spot,
            "expiry": "2026-11-09",
            "expiries": ["2026-11-09"],
            "calls": calls,
            "puts": puts,
        }

    monkeypatch.setattr(omon_mod, "_fetch_chain_sync", _fake_fetch)


class _FailingYf:
    async def fetch(self, _request):
        raise RuntimeError("network down")


class _NoLastYf:
    async def fetch(self, _request):
        class _Quote:
            last = None

        return _Quote()


class _Deps:
    def __init__(self, yfinance=None):
        self.yfinance = yfinance


def _execute(monkeypatch, *, chain_spot, deps, **params):
    _patch_chain(monkeypatch, spot=chain_spot)
    fn = OMONFunction()
    fn.deps = deps
    return asyncio.run(fn.execute(underlier="SPY", **params))


def test_no_spot_anywhere_returns_provider_unavailable_not_100(monkeypatch) -> None:
    # RED before fix: the 100.0 anchor priced the chain with status ok.
    result = _execute(monkeypatch, chain_spot=None, deps=_Deps(yfinance=None))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert data.get("spot") is None
    assert data.get("next_actions")
    assert any("spot" in w.lower() for w in result.warnings)


def test_failed_quote_and_no_chain_spot_is_not_priced_on_100(monkeypatch) -> None:
    result = _execute(monkeypatch, chain_spot=None, deps=_Deps(yfinance=_FailingYf()))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.data.get("spot") is None


def test_quote_without_last_price_is_not_priced_on_100(monkeypatch) -> None:
    result = _execute(monkeypatch, chain_spot=0.0, deps=_Deps(yfinance=_NoLastYf()))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []


def test_live_quote_still_anchors_when_chain_has_no_spot(monkeypatch) -> None:
    class _Quote:
        last = 741.5

    class _Yf:
        async def fetch(self, _request):
            return _Quote()

    result = _execute(monkeypatch, chain_spot=None, deps=_Deps(yfinance=_Yf()))
    assert result.data["status"] == "ok"
    assert result.data["spot"] == 741.5
    assert result.data["spot_source"] == "live_quote"


def test_explicit_spot_still_prices_when_chain_has_no_spot(monkeypatch) -> None:
    result = _execute(monkeypatch, chain_spot=None, deps=_Deps(yfinance=None), spot=700)
    assert result.data["status"] == "ok"
    assert result.data["spot"] == 700
    assert result.data["spot_source"] == "user_override"


def test_resolve_spot_returns_none_when_no_signal() -> None:
    spot = asyncio.run(
        _resolve_spot(
            _Deps(yfinance=None),
            Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
            {},
        )
    )
    assert spot is None
