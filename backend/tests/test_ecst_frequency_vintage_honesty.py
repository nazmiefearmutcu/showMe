"""ECST#5-RQ / ECST#3-RQ: applied flags and row labels must tell the truth.

ECST#5-RQ: when no provider returns observations, a requested frequency or vintage
must not be reported as applied.

ECST#3-RQ: when FRED fails and the World Bank serves an annual series, the requested
frequency or vintage is not honoured, so the response must say so and label the rows
with the World Bank's annual frequency, not the catalog's monthly one.

No network: FRED and World Bank are in-memory fakes.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pandas as pd

import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps


def _monthly_frame(months: int = 30) -> pd.DataFrame:
    end = pd.Timestamp(date.today()).to_period("M").to_timestamp()
    dates = pd.date_range(end=end, periods=months, freq="MS")
    return pd.DataFrame({"date": dates, "value": [100.0 + i for i in range(months)]})


class _EmptyKeyedFred:
    """Keyed FRED adapter that returns no observations."""

    async def series(self, sid, start=None, frequency=None, vintage=None, **_kwargs):
        return pd.DataFrame(columns=["date", "value"])

    async def info(self, sid):
        return {}


class _FailingFred:
    async def series(self, sid, start=None, frequency=None, vintage=None, **_kwargs):
        raise RuntimeError("fred down")

    async def info(self, sid):
        raise RuntimeError("fred down")


class _AnnualWorldBank:
    """World Bank annual indicator: one observation per year, year as int."""

    async def indicator(self, country, indicator):
        return pd.DataFrame({"date": [2021, 2022, 2023], "value": [3.9, 3.6, 3.6]})


def _run(fred, worldbank=None, **params):
    original = ecst_mod.fred_with_keyless_fallback
    ecst_mod.fred_with_keyless_fallback = lambda deps_fred, client=None: fred
    try:
        deps = FunctionDeps(worldbank=worldbank)
        return asyncio.run(ecst_mod.ECSTFunction(deps).execute(**params))
    finally:
        ecst_mod.fred_with_keyless_fallback = original


def test_unserved_request_is_not_reported_as_applied():
    result = _run(_EmptyKeyedFred(), series_id="UNRATE", date_range="1Y",
                  frequency="monthly", vintage="2024-04-25")
    assert result.data["status"] == "provider_unavailable"
    assert result.data["frequency_applied"] is False, result.data
    assert result.data["vintage_applied"] is False, result.data
    joined = " | ".join(result.warnings)
    assert "frequency monthly not applied" in joined, result.warnings
    assert "vintage 2024-04-25 not applied" in joined, result.warnings


def test_native_request_with_no_data_stays_applied():
    # Native frequency and latest vintage send nothing, so there is nothing to apply.
    result = _run(_EmptyKeyedFred(), series_id="UNRATE", date_range="1Y")
    assert result.data["frequency_applied"] is True
    assert result.data["vintage_applied"] is True


def test_world_bank_fallback_is_labelled_annual_and_request_flagged():
    result = _run(_FailingFred(), worldbank=_AnnualWorldBank(), series_id="UNRATE",
                  date_range="MAX", frequency="quarterly")
    assert result.data["source_mode"] == "worldbank"
    assert result.data["frequency_applied"] is False
    assert result.data["frequency"] == "annual", result.data["frequency"]
    assert result.data["rows"], "World Bank rows should be served"
    assert all(row["frequency"] == "annual" for row in result.data["rows"]), result.data["rows"][:2]
    assert any("frequency quarterly not applied" in w for w in result.warnings), result.warnings


def test_world_bank_fallback_flags_unhonoured_vintage():
    result = _run(_FailingFred(), worldbank=_AnnualWorldBank(), series_id="UNRATE",
                  date_range="MAX", vintage="2024-04-25")
    assert result.data["vintage_applied"] is False
    assert any("vintage 2024-04-25 not applied" in w for w in result.warnings), result.warnings
