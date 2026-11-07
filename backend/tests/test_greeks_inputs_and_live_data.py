"""GREEKS reads the inputs it advertises and never invents spot/vol/expiry.

Strict truth audit 2026-11-07 found three defects:
* the help/manifest ask for ``qty``/``expiry``/``rate``/``type`` but the
  Black-Scholes service reads ``quantity``/``T``/``r``/``kind`` — user input
  was silently dropped and replaced by defaults (30d expiry, 0.30 vol);
* the summary card read ``agg["delta"]`` while the service returns
  ``agg["totals"]`` — every summary Greek was ``null``;
* a computed result was served as ``data_state=live`` (source ``greeks``).
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from showme.engine.functions.portfolio.greeks import GREEKSFunction


class _FakeYF:
    def __init__(self, closes):
        self.closes = closes
        self.requests = []

    async def fetch(self, request):
        self.requests.append(request)
        return pd.DataFrame({"close": self.closes})


class _Deps:
    def __init__(self, yfinance=None):
        self.yfinance = yfinance


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


def _closes(n=90, start=200.0, daily_vol=0.02, seed=7):
    rng = np.random.default_rng(seed)
    return list(start * np.exp(np.cumsum(rng.normal(0, daily_vol, n))))


def test_advertised_input_names_are_honoured():
    expiry = (date.today() + timedelta(days=182)).isoformat()
    res = _run(GREEKSFunction(_Deps()), positions=[{
        "symbol": "AAPL", "type": "PUT", "qty": 3, "spot": 250.0, "strike": 240.0,
        "expiry": expiry, "vol": 0.25, "rate": 0.05,
    }])
    row = res.data["positions"][0]
    assert row["kind"] == "put"
    assert row["quantity"] == 3
    assert row["T"] == pytest.approx(182 / 365.25, abs=0.01)
    assert row.get("assumptions_used") in (None, [])  # nothing defaulted
    assert row["delta"] < 0  # a put


def test_summary_card_carries_the_totals():
    res = _run(GREEKSFunction(_Deps()), positions=[
        {"symbol": "AAPL", "kind": "call", "quantity": 1, "spot": 250, "strike": 240, "vol": 0.28, "T": 0.5, "r": 0.04},
        {"symbol": "AAPL", "kind": "put", "quantity": 2, "spot": 250, "strike": 240, "vol": 0.28, "T": 0.5, "r": 0.04},
    ])
    summary, totals = res.data["summary"], res.data["totals"]
    for greek in ("delta", "gamma", "vega", "theta", "rho"):
        assert summary[greek] is not None
        assert summary[greek] == pytest.approx(totals[greek])


def test_missing_spot_and_vol_come_from_live_history():
    closes = _closes()
    yf = _FakeYF(closes)
    res = _run(GREEKSFunction(_Deps(yf)), positions=[
        {"symbol": "AAPL", "kind": "call", "qty": 1, "strike": 200, "expiry_days": 30, "rate": 0.04},
    ])
    row = res.data["positions"][0]
    assert row["spot"] == pytest.approx(closes[-1])
    rets = np.diff(np.log(closes[-31:]))
    assert row["vol"] == pytest.approx(float(np.std(rets, ddof=1) * np.sqrt(252)), rel=1e-6)
    assert row["spot_source"] == "yfinance_last_close"
    assert row["vol_source"] == "realized_30d"
    assert "yfinance" in res.sources
    assert len(yf.requests) == 1  # one history fetch per symbol


def test_missing_expiry_is_an_error_not_a_30_day_default():
    res = _run(GREEKSFunction(_Deps()), positions=[
        {"symbol": "AAPL", "kind": "call", "qty": 1, "spot": 250, "strike": 240, "vol": 0.28},
    ])
    assert res.data["status"] == "input_error"
    assert "expiry" in res.data["reason"].lower()


def test_missing_vol_without_history_is_an_error_not_a_default():
    res = _run(GREEKSFunction(_Deps(yfinance=None)), positions=[
        {"symbol": "AAPL", "kind": "call", "qty": 1, "spot": 250, "strike": 240, "T": 0.25},
    ])
    assert res.data["status"] == "input_error"
    assert "vol" in res.data["reason"].lower()


def test_sources_are_honest():
    res = _run(GREEKSFunction(_Deps()), positions=[
        {"symbol": "AAPL", "kind": "call", "quantity": 1, "spot": 250, "strike": 240, "vol": 0.28, "T": 0.5, "r": 0.04},
    ])
    assert res.sources == ["black_scholes_model"]
