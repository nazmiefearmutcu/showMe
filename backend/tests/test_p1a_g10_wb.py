"""P1a-g10 WB regression (WB#1): as_of is the FRED observation date.

Live rows used to be stamped with the request date, so a 2018 Russian
observation showed up as a 2026 live reading. Each live row must carry its
last observation date, stale series must be flagged, and the summary must
report the data date rather than the wall clock.
"""

from __future__ import annotations

import asyncio
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions._fred_csv import reset_fred_csv_cache
from showme.engine.functions.bond import wb as wb_mod

_CSV_BY_SERIES = {
    "DGS10": "observation_date,value\n2026-11-04,4.83\n2026-11-05,4.84\n",
    "IRLTLT01DEM156N": "observation_date,value\n2026-08-01,2.61\n2026-09-01,3.46952\n",
    "IRLTLT01RUM156N": "observation_date,value\n2018-05-01,7.40\n2018-06-01,7.62\n",
}


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _Client:
    async def get(self, url, timeout=None):  # noqa: ANN001
        for series_id, text in _CSV_BY_SERIES.items():
            if f"id={series_id}" in url:
                return _Resp(text)
        raise RuntimeError(f"unexpected series in {url}")


def _run(countries: str):
    reset_fred_csv_cache()
    fn = wb_mod.WBFunction(FunctionDeps())
    fn._http_client = _Client()
    return asyncio.run(fn.execute(countries=countries))


def _rows_by_country(result):
    return {row["country"]: row for row in result.data["rows"]}


def test_live_rows_carry_observation_date_not_request_date() -> None:
    result = _run("US,DE")
    rows = _rows_by_country(result)
    assert rows["DE"]["as_of"] == "2026-09-01"
    assert rows["US"]["as_of"] == "2026-11-05"


def test_stale_series_is_flagged_and_not_presented_as_current() -> None:
    result = _run("US,RU")
    rows = _rows_by_country(result)
    assert rows["RU"]["as_of"] == "2018-06-01"
    assert rows["RU"]["stale"] is True
    assert rows["US"]["as_of"] == "2026-11-05"
    assert rows["US"]["stale"] is False


def test_summary_reports_data_date_not_wall_clock() -> None:
    result = _run("US,DE,RU")
    summary = result.data["summary"]
    assert summary["latest_observation"] == "2026-11-05"
    assert summary["oldest_observation"] == "2018-06-01"
    assert summary["stale_countries"] == 1
    assert result.data["field_dictionary"]["as_of"].lower().startswith("last fred observation")
