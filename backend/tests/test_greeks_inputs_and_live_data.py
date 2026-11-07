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


# ── review follow-ups (2026-11-08) ────────────────────────────────────────

class _FRED:
    api_key = "test"

    async def series(self, series_id, frequency="d"):
        assert series_id == "DGS3MO"
        return pd.DataFrame({"value": [4.30, 4.33]}, index=pd.to_datetime(["2026-11-05", "2026-11-06"]))


class _DepsFred(_Deps):
    def __init__(self, yfinance=None):
        super().__init__(yfinance)
        self.fred = _FRED()


BASE = {"symbol": "AAPL", "type": "call", "qty": 1, "spot": 250, "strike": 240, "vol": 0.28, "T": 0.5}


@pytest.mark.parametrize("override, needle", [
    ({"strike": "abc"}, "strike"),
    ({"vol": 0}, "vol"),
    ({"vol": -0.2}, "vol"),
    ({"qty": 0}, "qty"),
    ({"spot": -5}, "spot"),
    ({"T": "soon"}, "expiry"),
])
def test_invalid_numbers_are_input_errors(override, needle):
    res = _run(GREEKSFunction(_Deps()), positions=[{**BASE, "rate": 0.04, **override}])
    assert res.data["status"] == "input_error"
    assert needle in res.data["reason"]


def test_missing_rate_uses_the_live_tbill_and_labels_it():
    res = _run(GREEKSFunction(_DepsFred()), positions=[dict(BASE)])
    row = res.data["positions"][0]
    assert row["rate_source"] == "fred_DGS3MO_2026-11-06"
    assert "fred" in res.sources
    with_rate = _run(GREEKSFunction(_Deps()), positions=[{**BASE, "rate": 0.0433}])
    assert row["rho"] == pytest.approx(with_rate.data["positions"][0]["rho"])


def test_missing_rate_without_fred_is_an_input_error(monkeypatch):
    from showme.engine.functions.portfolio import greeks as mod

    async def _down(*a, **k):
        return None

    monkeypatch.setattr(mod, "_risk_free_rate", _down)
    res = _run(GREEKSFunction(_Deps()), positions=[dict(BASE)])
    assert res.data["status"] == "input_error"
    assert "rate" in res.data["reason"]


def test_percent_rate_is_converted():
    pct = _run(GREEKSFunction(_Deps()), positions=[{**BASE, "rate": 4.5}])
    dec = _run(GREEKSFunction(_Deps()), positions=[{**BASE, "rate": 0.045}])
    assert pct.data["positions"][0]["rho"] == pytest.approx(dec.data["positions"][0]["rho"])
    assert pct.data["positions"][0]["rate_source"] == "input_percent"


def test_a_position_that_fails_pricing_fails_the_book(monkeypatch):
    from showme.engine.services import greeks as svc

    real = svc.position_greeks

    def flaky(pos):
        if pos.get("symbol") == "BAD":
            raise ValueError("boom")
        return real(pos)

    monkeypatch.setattr(svc, "position_greeks", flaky)
    res = _run(GREEKSFunction(_Deps()), positions=[{**BASE, "rate": 0.04}, {**BASE, "symbol": "BAD", "rate": 0.04}])
    assert res.data["status"] == "calc_error"
    assert "BAD" in res.data["reason"]
    assert "totals" not in res.data
