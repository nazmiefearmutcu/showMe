"""Regression tests for OMON findings OMON#1 (undefined IV shown as 0.0 / delta -1)
and OMON#2 (as_of / live label not tied to the option trade timestamps).

The yfinance chain fetch is patched at ``_fetch_chain_sync`` so no network is used.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from showme.engine.functions.derivative import omon as omon_mod
from showme.engine.functions.derivative.omon import OMONFunction

SPOT = 735.29


def _patch_chain(monkeypatch, calls, puts, *, spot=SPOT, expiry="2026-11-09"):
    def _fake_fetch(underlier, requested_expiry):  # noqa: ARG001
        return {
            "spot": spot,
            "expiry": expiry,
            "expiries": [expiry],
            "calls": calls,
            "puts": puts,
        }

    monkeypatch.setattr(omon_mod, "_fetch_chain_sync", _fake_fetch)


def _run(underlier="SPY"):
    return asyncio.run(OMONFunction().execute(underlier=underlier))


def _row(rows, strike):
    matches = [r for r in rows if r["strike"] == strike]
    assert matches, f"strike {strike} missing from rows"
    return matches[0]


# ── OMON#1 ─────────────────────────────────────────────────────────────────


def test_omon1_solver_failed_itm_put_has_no_iv_or_delta(monkeypatch) -> None:
    """750 put: raw IV 1e-5 (solver failure), mid 14.27 below K - S = 14.71.

    Before the fix the row carried put_iv 0.0 and put_delta -1.0 as if real.
    """
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
            "strike": 750.0,
            "bid": 14.14,
            "ask": 14.40,
            "impliedVolatility": 1e-5,
            "openInterest": 500,
            "volume": 40,
            "lastTradeDate": trade_ts,
        },
        {
            "strike": 730.0,
            "bid": 4.0,
            "ask": 4.2,
            "impliedVolatility": 0.20,
            "openInterest": 300,
            "volume": 20,
            "lastTradeDate": trade_ts,
        },
    ]
    _patch_chain(monkeypatch, calls, puts)
    result = _run()
    data = result.data
    assert data["status"] == "ok"
    bad = _row(data["rows"], 750.0)
    # Undefined IV must be null, never 0.0, and the delta must not be computed.
    assert bad["put_iv"] is None, bad
    assert bad["put_delta"] is None, bad
    # A real OTM put keeps a real IV and a delta in (-1, 0).
    good = _row(data["rows"], 730.0)
    assert good["put_iv"] == 0.2
    assert -1.0 < good["put_delta"] < 0.0
    # The undefined quote is counted and disclosed.
    assert data["summary"]["iv_undefined_count"] == 1
    assert any("undefined" in w.lower() for w in result.warnings)


# ── OMON#2 ─────────────────────────────────────────────────────────────────


def _basic_chain(trade_ts):
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
            "openInterest": 300,
            "volume": 20,
            "lastTradeDate": trade_ts,
        }
    ]
    return calls, puts


def test_omon2_as_of_is_last_trade_date_not_fetch_date(monkeypatch) -> None:
    """Trades from three days ago must not be stamped with today's date as as_of."""
    trade_ts = datetime.now(timezone.utc) - timedelta(days=3)
    calls, puts = _basic_chain(trade_ts)
    _patch_chain(monkeypatch, calls, puts)
    result = _run()
    meta = result.metadata
    assert meta["as_of"] == trade_ts.date().isoformat()
    # Stale trades must not be labelled as a live chain.
    assert meta["live"] is False
    assert meta["data_mode"] != "live_yfinance"
    assert any("not live" in w.lower() for w in result.warnings)


def test_omon2_recent_trades_are_live(monkeypatch) -> None:
    trade_ts = datetime.now(timezone.utc) - timedelta(minutes=5)
    calls, puts = _basic_chain(trade_ts)
    _patch_chain(monkeypatch, calls, puts)
    result = _run()
    assert result.metadata["live"] is True
    assert result.metadata["data_mode"] == "live_yfinance"
    assert result.metadata["as_of"] == trade_ts.date().isoformat()


def test_omon2_no_trade_timestamp_is_not_live(monkeypatch) -> None:
    calls = [{"strike": 740.0, "bid": 5.0, "ask": 5.2, "impliedVolatility": 0.18}]
    puts = [{"strike": 730.0, "bid": 4.0, "ask": 4.2, "impliedVolatility": 0.20}]
    _patch_chain(monkeypatch, calls, puts)
    result = _run()
    assert result.metadata["live"] is False
    assert result.metadata["as_of"] is None
    assert result.metadata["data_mode"] != "live_yfinance"
