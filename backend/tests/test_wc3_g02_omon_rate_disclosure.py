"""XCON-3: OMON says when its risk-free rate is a fixed assumption, not a live yield.

OMON prices with a fixed 4.5% default (echoed as risk_free_source "default"),
while GREEKS uses the live 3-month T-bill (FRED DGS3MO). The same option can
therefore show different theta and rho in the two panes. The response must say
so in a warning; a caller-supplied rate is not flagged.

The yfinance chain fetch is patched at ``_fetch_chain_sync`` so no network is used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from showme.engine.functions.derivative import omon as omon_mod
from showme.engine.functions.derivative.omon import OMONFunction

SPOT = 735.29


def _chain(trade_ts):
    calls = [{"strike": 740.0, "bid": 5.0, "ask": 5.2, "impliedVolatility": 0.18,
              "openInterest": 100, "volume": 10, "lastTradeDate": trade_ts}]
    puts = [{"strike": 730.0, "bid": 4.0, "ask": 4.2, "impliedVolatility": 0.20,
             "openInterest": 300, "volume": 20, "lastTradeDate": trade_ts}]
    return calls, puts


def _run(monkeypatch, **params):
    calls, puts = _chain(datetime.now(timezone.utc) - timedelta(minutes=5))

    def _fake_fetch(underlier, requested_expiry):  # noqa: ARG001
        return {"spot": SPOT, "expiry": "2026-11-09", "expiries": ["2026-11-09"],
                "calls": calls, "puts": puts}

    monkeypatch.setattr(omon_mod, "_fetch_chain_sync", _fake_fetch)
    return asyncio.run(OMONFunction().execute(underlier="SPY", **params))


def _rate_warnings(result):
    return [w for w in result.warnings if "risk-free" in w.lower()]


def test_default_rate_is_disclosed_as_fixed_assumption_not_live(monkeypatch) -> None:
    result = _run(monkeypatch)
    assert result.data["risk_free_source"] == "default"
    warnings = _rate_warnings(result)
    assert warnings, "a fixed default risk-free rate must carry a warning"
    text = " ".join(warnings)
    assert "4.5%" in text
    assert "not a live" in text.lower()
    assert "DGS3MO" in text


def test_caller_supplied_rate_has_no_fixed_rate_warning(monkeypatch) -> None:
    result = _run(monkeypatch, risk_free=0.045)
    assert result.data["risk_free_source"] == "param"
    assert not _rate_warnings(result)
