"""ECST#5 — date-range and year-over-year transform are real, labelled, and honest.

The handler reads date_range; the new transform=yoy computes percent change against
the observation one calendar year earlier. A period with no prior-year observation
is dropped, never estimated; the unit and series name state the transform. No
network: FRED is an in-memory fake.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pandas as pd

import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps


class _RecordingFred:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls: list[dict] = []

    async def series(self, sid, start=None, frequency=None, vintage=None, **_kwargs):
        self.calls.append({"sid": sid, "start": start})
        out = self.frame.copy()
        if start:
            out = out[out["date"] >= pd.Timestamp(start)]
        return out

    async def info(self, sid):
        return {"title": "US CPI all urban consumers", "units": "Index 1982-1984=100",
                "frequency": "monthly"}


def _monthly_frame(months: int = 30, growth: float = 0.01) -> pd.DataFrame:
    """Geometric monthly series ending this month: every year-over-year change is (1+g)^12-1."""
    end = pd.Timestamp(date.today()).to_period("M").to_timestamp()
    dates = pd.date_range(end=end, periods=months, freq="MS")
    values = [100.0 * (1.0 + growth) ** i for i in range(months)]
    return pd.DataFrame({"date": dates, "value": values})


def _run(fred, **params):
    original = ecst_mod.fred_with_keyless_fallback
    ecst_mod.fred_with_keyless_fallback = lambda deps_fred, client=None: fred
    try:
        return asyncio.run(ecst_mod.ECSTFunction(FunctionDeps()).execute(**params))
    finally:
        ecst_mod.fred_with_keyless_fallback = original


def test_default_transform_is_level_and_unchanged():
    fred = _RecordingFred(_monthly_frame())
    res = _run(fred, series_id="CPIAUCSL", date_range="1Y")
    assert res.data["unit"] == "Index 1982-1984=100"
    assert "transform" not in res.data["rows"][-1]
    assert "y/y" not in res.data["series_name"].lower()


def test_yoy_transform_is_percent_change_vs_one_year_earlier():
    growth = 0.01
    fred = _RecordingFred(_monthly_frame(months=30, growth=growth))
    res = _run(fred, series_id="CPIAUCSL", date_range="MAX", transform="yoy")
    expected = ((1.0 + growth) ** 12 - 1.0) * 100.0
    rows = res.data["rows"]
    assert rows, "y/y rows expected once a prior-year observation exists"
    for row in rows:
        assert abs(row["value"] - expected) < 1e-4, row
        assert row["unit"] == "% y/y", row
        assert row["transform"] == "yoy", row
    assert res.data["unit"] == "% y/y"
    assert "y/y" in res.data["series_name"]


def test_yoy_drops_periods_without_a_prior_year_observation():
    frame = _monthly_frame(months=18)
    # Remove one month that has a prior-year observation: its y/y must vanish, not be guessed.
    missing = frame["date"].iloc[12]
    frame = frame[frame["date"] != missing]
    fred = _RecordingFred(frame)
    res = _run(fred, series_id="CPIAUCSL", date_range="MAX", transform="yoy")
    dates = {r["date"] for r in res.data["rows"]}
    assert missing.strftime("%Y-%m-%d") not in dates
    # The first 12 months have no prior year: no rows for them either.
    assert frame["date"].iloc[0].strftime("%Y-%m-%d") not in dates


def test_yoy_fetches_history_before_the_window_start():
    fred = _RecordingFred(_monthly_frame(months=40))
    _run(fred, series_id="CPIAUCSL", date_range="1Y", transform="yoy")
    window_start = pd.Timestamp(date.today().replace(year=date.today().year - 1))
    assert fred.calls, "FRED must be queried"
    fetched_start = pd.Timestamp(fred.calls[0]["start"])
    assert fetched_start < window_start, (fetched_start, window_start)


def test_yoy_rows_are_trimmed_to_the_requested_window():
    fred = _RecordingFred(_monthly_frame(months=40))
    res = _run(fred, series_id="CPIAUCSL", date_range="1Y", transform="yoy")
    window_start = date.today().replace(year=date.today().year - 1).strftime("%Y-%m-%d")
    assert res.data["rows"]
    assert all(r["date"] >= window_start for r in res.data["rows"])


def test_unknown_transform_is_reported_and_level_is_served():
    fred = _RecordingFred(_monthly_frame())
    res = _run(fred, series_id="CPIAUCSL", date_range="1Y", transform="pct_mom")
    assert res.data["unit"] == "Index 1982-1984=100"
    assert any("transform" in w and "pct_mom" in w for w in res.warnings), res.warnings
