"""ECST#5 — frequency and vintage are sent to FRED as FRED codes, and never silently ignored.

Two honesty points: a frequency label ("monthly") must reach FRED as its code ("m"), and
"native" must send no frequency at all. The keyless FRED CSV shim cannot apply a frequency
or a pinned vintage, so when it serves a request that asks for either, the response says
so instead of looking as if the request had been honoured. No network: FRED is in-memory.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pandas as pd

import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions._fred_csv import _KeylessFredCSV


def _monthly_frame(months: int = 30) -> pd.DataFrame:
    end = pd.Timestamp(date.today()).to_period("M").to_timestamp()
    dates = pd.date_range(end=end, periods=months, freq="MS")
    return pd.DataFrame({"date": dates, "value": [100.0 + i for i in range(months)]})


class _KeyedFake:
    """Stands in for a keyed FREDAdapter: honours frequency and vintage (records them)."""

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls: list[dict] = []

    async def series(self, sid, start=None, frequency=None, vintage=None, **_kwargs):
        self.calls.append({"sid": sid, "frequency": frequency, "vintage": vintage})
        out = self.frame.copy()
        if start:
            out = out[out["date"] >= pd.Timestamp(start)]
        return out

    async def info(self, sid):
        return {"title": "US CPI all urban consumers", "units": "Index 1982-1984=100",
                "frequency": "monthly"}


class _KeylessFake(_KeylessFredCSV):
    """The keyless shim's type, served from memory: it cannot apply frequency or vintage."""

    def __init__(self, frame: pd.DataFrame):
        super().__init__(client=None)
        self.frame = frame
        self.calls: list[dict] = []

    async def series(self, sid, start=None, frequency=None, vintage=None, **_kwargs):
        self.calls.append({"sid": sid, "frequency": frequency, "vintage": vintage})
        out = self.frame.copy()
        if start:
            out = out[out["date"] >= pd.Timestamp(start)]
        return out

    async def info(self, sid):
        raise RuntimeError("keyed only")


def _run(fred, **params):
    original = ecst_mod.fred_with_keyless_fallback
    ecst_mod.fred_with_keyless_fallback = lambda deps_fred, client=None: fred
    try:
        return asyncio.run(ecst_mod.ECSTFunction(FunctionDeps()).execute(**params))
    finally:
        ecst_mod.fred_with_keyless_fallback = original


def test_monthly_label_is_sent_to_fred_as_its_code():
    fred = _KeyedFake(_monthly_frame())
    _run(fred, series_id="CPIAUCSL", date_range="1Y", frequency="monthly")
    assert fred.calls[0]["frequency"] == "m", fred.calls


def test_native_frequency_sends_no_frequency_to_fred():
    fred = _KeyedFake(_monthly_frame())
    _run(fred, series_id="CPIAUCSL", date_range="1Y", frequency="native")
    assert fred.calls[0]["frequency"] is None, fred.calls


def test_every_declared_frequency_label_has_a_fred_code():
    expected = {"daily": "d", "weekly": "w", "monthly": "m", "quarterly": "q", "annual": "a"}
    for label, code in expected.items():
        fred = _KeyedFake(_monthly_frame())
        _run(fred, series_id="CPIAUCSL", date_range="1Y", frequency=label)
        assert fred.calls[0]["frequency"] == code, (label, fred.calls)


def test_unknown_frequency_is_reported_and_native_served():
    fred = _KeyedFake(_monthly_frame())
    res = _run(fred, series_id="CPIAUCSL", date_range="1Y", frequency="hourly")
    assert fred.calls[0]["frequency"] is None, fred.calls
    assert res.data["rows"], "native rows still served"
    assert any("hourly" in w for w in res.warnings), res.warnings
    assert res.data["frequency_applied"] is False


def test_keyed_provider_reports_frequency_applied():
    fred = _KeyedFake(_monthly_frame())
    res = _run(fred, series_id="CPIAUCSL", date_range="1Y", frequency="monthly")
    assert res.data["frequency_applied"] is True
    assert res.data["frequency_requested"] == "monthly"
    assert not [w for w in res.warnings if "not applied" in w], res.warnings


def test_keyless_shim_says_frequency_was_not_applied():
    fred = _KeylessFake(_monthly_frame())
    res = _run(fred, series_id="CPIAUCSL", date_range="1Y", frequency="monthly")
    assert res.data["frequency_applied"] is False
    assert any("frequency" in w and "not applied" in w for w in res.warnings), res.warnings
    assert res.data["rows"], "native rows still served, labelled not applied"


def test_keyless_shim_says_pinned_vintage_was_not_applied():
    fred = _KeylessFake(_monthly_frame())
    res = _run(fred, series_id="CPIAUCSL", date_range="1Y", vintage="2024-04-25")
    assert res.data["vintage_applied"] is False
    assert any("vintage" in w and "not applied" in w for w in res.warnings), res.warnings


def test_latest_vintage_and_native_frequency_need_no_disclosure():
    fred = _KeylessFake(_monthly_frame())
    res = _run(fred, series_id="CPIAUCSL", date_range="1Y", frequency="native", vintage="latest")
    assert res.data["frequency_applied"] is True
    assert res.data["vintage_applied"] is True
    assert not [w for w in res.warnings if "not applied" in w], res.warnings
