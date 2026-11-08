"""CRVF honesty regressions (p2a-g04): non-US curves, observation dates,
the live_curve switch and the tenors filter.

Offline: FRED is reached only through an injected fake HTTP client (the
``_http_client`` seam), and the module-level FRED CSV cache is reset per
test so one test's fixture cannot leak into another.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions._fred_csv import reset_fred_csv_cache  # noqa: E402
from showme.engine.functions.bond.crvf import CRVFFunction  # noqa: E402

_US_MODEL_10Y = 4.45  # the static computed-model 10Y level


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_fred_cache():
    reset_fred_csv_cache()
    yield
    reset_fred_csv_cache()


class _CsvResp:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FredCsvClient:
    """Serves one observation per FRED series id, dated 2026-11-05."""

    def __init__(self, observation_date: str = "2026-11-05", ten_year: float = 4.84) -> None:
        self.observation_date = observation_date
        self.ten_year = ten_year
        self.urls: list[str] = []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        series = url.rsplit("id=", 1)[-1]
        value = self.ten_year if series == "DGS10" else 4.10
        return _CsvResp(f"observation_date,value\n{self.observation_date},{value}\n")


def _client_fn(client) -> CRVFFunction:
    fn = CRVFFunction(FunctionDeps())
    fn._http_client = client
    return fn


# ── CRVF#1: non-US countries never receive the US fixture ────────────


def test_non_us_live_is_provider_unavailable_not_us_levels():
    client = _FredCsvClient()
    res = _run(_client_fn(client).execute(country="DE"))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert res.data["curve"] == []
    assert res.sources == []
    assert "DE" in res.data["reason"]
    # No network call for a country with no wired source.
    assert client.urls == []


def test_non_us_reference_is_also_unavailable_not_us_fixture():
    res = _run(CRVFFunction(FunctionDeps()).execute(country="JP", reference=True))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert not any(
        abs(float(row.get("yield", 0)) - _US_MODEL_10Y) < 1e-9 for row in res.data["rows"]
    )


# ── CRVF#2: as_of is the FRED observation date, not the fetch date ───


def test_live_rows_carry_the_fred_observation_date():
    res = _run(_client_fn(_FredCsvClient(observation_date="2026-11-05")).execute(country="US"))
    assert res.data["summary"]["source_mode"] == "fred"
    as_of = {row["tenor"]: row["as_of"] for row in res.data["rows"]}
    assert as_of["10Y"] == "2026-11-05"
    assert as_of["2Y"] == "2026-11-05"


def test_as_of_is_not_todays_date_when_observation_is_older():
    res = _run(_client_fn(_FredCsvClient(observation_date="2020-01-02")).execute(country="US"))
    as_of = {row["tenor"]: row["as_of"] for row in res.data["rows"]}
    assert as_of["10Y"] == "2020-01-02"


# ── CRVF#3: live_curve is honoured ────────────────────────────────────


def test_live_curve_false_returns_the_model_not_live_fred():
    client = _FredCsvClient()
    res = _run(_client_fn(client).execute(country="US", live_curve=False))
    assert res.sources == ["curve_model"]
    assert res.metadata.get("live") is False
    assert client.urls == []


def test_live_curve_default_still_fetches_live():
    res = _run(_client_fn(_FredCsvClient()).execute(country="US"))
    assert res.data["summary"]["source_mode"] == "fred"


# ── CRVF#4: tenors filter the returned curve ─────────────────────────


def test_tenors_filter_limits_rows_and_is_reported():
    res = _run(_client_fn(_FredCsvClient()).execute(country="US", tenors=["2Y", "10Y"]))
    assert [row["tenor"] for row in res.data["rows"]] == ["2Y", "10Y"]
    assert res.data["summary"]["tenors"] == 2
    assert res.data["summary"]["tenor_filter"] == ["2Y", "10Y"]


def test_tenors_filter_accepts_comma_string():
    res = _run(_client_fn(_FredCsvClient()).execute(country="US", tenors="2Y,10Y"))
    assert [row["tenor"] for row in res.data["rows"]] == ["2Y", "10Y"]


# ── Policy: a failed live US request is an honest state, not the fixture ─


class _FailingCsvClient:
    """Every FRED CSV GET fails (offline outage)."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        raise RuntimeError("offline")


class _EmptyCsvResp:
    text = "observation_date,value\n"

    def raise_for_status(self) -> None:
        return None


class _EmptyCsvClient:
    async def get(self, url, timeout=None):
        return _EmptyCsvResp()


def test_us_live_fetch_failure_is_provider_unavailable_not_fixture():
    res = _run(_client_fn(_FailingCsvClient()).execute(country="US"))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert res.sources == []
    assert not any(
        abs(float(row.get("yield", 0)) - _US_MODEL_10Y) < 1e-9 for row in res.data["rows"]
    )
    assert any("fred" in w.lower() for w in res.warnings)


def test_us_live_empty_csv_is_provider_unavailable_not_fixture():
    res = _run(_client_fn(_EmptyCsvClient()).execute(country="US"))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert res.sources == []


def test_us_live_failure_names_the_explicit_model_opt_out():
    res = _run(_client_fn(_FailingCsvClient()).execute(country="US"))
    actions = " ".join(res.data["next_actions"])
    assert "live_curve=false" in actions


# ── Reference path: an empty tenor filter is reported, not silent ───────


def test_reference_tenor_filter_with_no_match_warns():
    res = _run(CRVFFunction(FunctionDeps()).execute(country="US", reference=True, tenors=["3Y"]))
    assert res.data["rows"] == []
    assert res.data["summary"]["tenor_filter"] == ["3Y"]
    assert any("3Y" in w for w in res.warnings), res.warnings


# ── Keyed adapter: observation dates when the adapter reports them ──────


class _KeyedFredDated:
    """Keyed adapter fake that reports the observation date of each series."""

    api_key = "test-key"

    async def yield_curve_observations(self):
        import pandas as pd

        return {
            "DGS10": (4.84, pd.Timestamp("2026-11-05")),
            "DGS2": (4.10, pd.Timestamp("2026-11-04")),
        }

    async def yield_curve(self):
        return {k: v for k, (v, _d) in (await self.yield_curve_observations()).items()}


def test_keyed_adapter_rows_carry_observation_dates():
    fn = CRVFFunction(FunctionDeps(fred=_KeyedFredDated()))
    res = _run(fn.execute(country="US"))
    assert res.data["summary"]["source_mode"] == "fred"
    as_of = {row["tenor"]: row["as_of"] for row in res.data["rows"]}
    assert as_of["10Y"] == "2026-11-05"
    assert as_of["2Y"] == "2026-11-04"


# ── Keyless path: one fetch per series, even when one series fails ──────


class _OneSeriesDownClient(_FredCsvClient):
    async def get(self, url, timeout=None):
        series = url.rsplit("id=", 1)[-1]
        if series == "DGS2":
            self.urls.append(url)
            raise RuntimeError("DGS2 down")
        return await super().get(url, timeout=timeout)


def test_keyless_failed_series_is_not_refetched_for_its_date():
    client = _OneSeriesDownClient()
    res = _run(_client_fn(client).execute(country="US"))
    assert res.data["summary"]["source_mode"] == "fred"
    assert client.urls.count("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2") == 1
    as_of = {row["tenor"]: row["as_of"] for row in res.data["rows"]}
    assert "2Y" not in as_of
    assert as_of["10Y"] == "2026-11-05"
