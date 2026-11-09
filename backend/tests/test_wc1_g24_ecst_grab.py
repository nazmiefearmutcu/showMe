"""WC1-G24: ECST request honesty (ECST#3, ECST#4) and overlay guard (ECST#2/ASOF-6).
All network is patched; no provider is called.
"""

from __future__ import annotations

import asyncio
import datetime

import pandas as pd
import pytest

import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions._fred_csv import (
    _KeylessFredCSV,
    keyless_ignored_request_params,
    reset_fred_csv_cache,
)


def _run(coro):
    return asyncio.run(coro)


def _execute(monkeypatch, fred, **params):
    monkeypatch.setattr(
        ecst_mod, "fred_with_keyless_fallback", lambda deps_fred, client=None: fred
    )
    return _run(ecst_mod.ECSTFunction(FunctionDeps()).execute(**params))


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _CsvClient:
    """Serves fredgraph.csv payloads (daily DGS10) without touching the network."""

    async def get(self, url, timeout=None):  # noqa: ANN001 - fake seam
        assert "fredgraph.csv" in str(url)
        return _FakeResp(
            "observation_date,value\n2026-09-01,4.00\n2026-09-02,4.10\n2026-09-03,4.20\n"
        )


@pytest.fixture(autouse=True)
def _clear_csv_cache():
    reset_fred_csv_cache()
    yield
    reset_fred_csv_cache()


# ── ECST#3: keyless shim must label frequency/vintage it cannot honour ──


def test_keyless_shim_flags_frequency_request_it_cannot_serve(monkeypatch):
    shim = _KeylessFredCSV(client=_CsvClient())
    result = _execute(monkeypatch, shim, series_id="DGS10", frequency="monthly")

    assert result.data["unhonoured_params"] == ["frequency"]
    assert any("monthly" in w and "frequency" in w for w in result.warnings)


def test_keyless_shim_flags_pinned_vintage_it_cannot_serve(monkeypatch):
    shim = _KeylessFredCSV(client=_CsvClient())
    result = _execute(monkeypatch, shim, series_id="DGS10", vintage="2020-01-01")

    assert result.data["unhonoured_params"] == ["vintage"]
    assert any("vintage" in w for w in result.warnings)


def test_keyless_shim_native_and_latest_defaults_are_not_flagged(monkeypatch):
    shim = _KeylessFredCSV(client=_CsvClient())
    result = _execute(
        monkeypatch, shim, series_id="DGS10", frequency="native", vintage="latest"
    )

    assert result.data["status"] == "ok"
    assert "unhonoured_params" not in result.data
    assert result.warnings == []


def test_helper_reports_nothing_for_keyed_adapter():
    class _Keyed:
        pass

    assert keyless_ignored_request_params(_Keyed(), frequency="monthly") == []
    shim = _KeylessFredCSV()
    assert keyless_ignored_request_params(shim, frequency="monthly", vintage="latest") == [
        "frequency"
    ]


# ── ECST#4: date_range units are D/M/Y; other units are rejected ──


class _StartSpy:
    def __init__(self) -> None:
        self.starts: list[str | None] = []

    async def series(self, sid, start=None, **kwargs):
        self.starts.append(start)
        return pd.DataFrame({"date": ["2026-09-01"], "value": [4.0]})

    async def info(self, sid):
        raise RuntimeError("no info")


def test_six_month_window_is_six_months_not_six_years(monkeypatch):
    spy = _StartSpy()
    _execute(monkeypatch, spy, series_id="DGS10", date_range="6M")

    assert spy.starts and spy.starts[0] is not None
    start = datetime.date.fromisoformat(spy.starts[0])
    age_days = (datetime.date.today() - start).days
    assert 176 <= age_days <= 190, f"6M window started {age_days} days ago"


def test_day_window_is_days(monkeypatch):
    spy = _StartSpy()
    _execute(monkeypatch, spy, series_id="DGS10", date_range="30D")

    start = datetime.date.fromisoformat(spy.starts[0])
    assert (datetime.date.today() - start).days == 30


def test_unknown_date_range_unit_is_rejected_not_read_as_years(monkeypatch):
    spy = _StartSpy()
    result = _execute(monkeypatch, spy, series_id="DGS10", date_range="6X")

    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []
    assert spy.starts == [], "no provider call when the window cannot be parsed"
    assert "6X" in result.data["reason"]


def test_max_window_still_requests_full_history(monkeypatch):
    spy = _StartSpy()
    _execute(monkeypatch, spy, series_id="DGS10", date_range="MAX")
    assert spy.starts == [None]


# ── ECST#2 / ASOF-6 guard: overlay never extends the main series past its last obs ──


def test_overlay_does_not_extend_monthly_main_series_past_last_observation(monkeypatch):
    class _Mixed:
        async def series(self, sid, start=None, **kwargs):
            if sid == "UNRATE":
                return pd.DataFrame(
                    {"date": ["2026-09-01", "2026-10-01"], "value": [4.0, 4.1]}
                )
            return pd.DataFrame(
                {
                    "date": ["2026-10-01", "2026-10-02", "2026-11-05"],
                    "value": [4.0, 4.05, 4.1],
                }
            )

        async def info(self, sid):
            raise RuntimeError("no info")

    result = _execute(
        monkeypatch, _Mixed(), series_id="UNRATE", compare_with="DGS10", date_range="10Y"
    )
    rows = result.data["rows"]
    assert rows[-1]["date"] == "2026-10-01"
    assert all(row["date"] <= "2026-10-01" for row in rows)
    latest_card = next(c for c in result.data["cards"] if c["label"] == "As of")
    assert latest_card["value"] == "2026-10-01"




def test_out_of_range_day_window_raises_value_error_not_overflow():
    today = datetime.date(2026, 11, 8)
    for rng in ("1000000D", "999999999D"):
        with pytest.raises(ValueError):
            ecst_mod._window_start(rng, today)


def test_out_of_range_day_window_is_input_error_without_provider_call(monkeypatch):
    spy = _StartSpy()
    for rng in ("1000000D", "999999999D"):
        result = _execute(monkeypatch, spy, series_id="DGS10", date_range=rng)
        assert result.data["status"] == "input_error"
        assert result.data["rows"] == []
        assert rng in result.data["reason"]
    assert spy.starts == [], "no provider call when the window is out of range"


# ── ECST#3 (keyed path): the request sent to FRED must be a valid FRED request ──


class _JsonResp:
    def __init__(self, payload) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _FakeFredHTTP:
    """Records the FRED REST calls the keyed adapter would make (no network)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path == "/series/observations":
            return _JsonResp(
                {"observations": [
                    {"date": "2026-08-01", "value": "4.0"},
                    {"date": "2026-09-01", "value": "4.1"},
                ]}
            )
        return _JsonResp({"seriess": [{"title": "T", "units": "Percent", "frequency": "Daily"}]})

    def observation_params(self) -> list[dict]:
        return [p for path, p in self.calls if path == "/series/observations"]


def _keyed_adapter(http: _FakeFredHTTP):
    from showme.engine.data_sources.macro.fred_adapter import FREDAdapter

    adapter = FREDAdapter()
    adapter.api_key = "test-key-not-real"

    async def _client():
        return http

    adapter._client_ = _client
    return adapter


def test_keyed_default_native_frequency_is_not_sent_to_fred(monkeypatch):
    http = _FakeFredHTTP()
    result = _execute(
        monkeypatch, _keyed_adapter(http), series_id="DGS10", frequency="native", vintage="latest"
    )
    obs = http.observation_params()
    assert obs, "keyed adapter was not called"
    assert "frequency" not in obs[0], "'native' is not a FRED frequency code"
    assert "vintage_dates" not in obs[0]
    assert result.data["status"] == "ok"
    assert "unhonoured_params" not in result.data


def test_keyed_monthly_request_is_sent_as_fred_code_and_labelled_as_applied(monkeypatch):
    http = _FakeFredHTTP()
    result = _execute(monkeypatch, _keyed_adapter(http), series_id="DGS10", frequency="monthly")
    assert http.observation_params()[0]["frequency"] == "m"
    assert result.data["frequency"] == "monthly"
    assert "unhonoured_params" not in result.data
    rows = result.data["rows"]
    assert rows, "keyed monthly request returned no rows"
    # Every row must carry the applied frequency, not the native catalog label.
    assert {row["frequency"] for row in rows} == {"monthly"}


def test_keyed_unknown_frequency_is_input_error_without_provider_call(monkeypatch):
    http = _FakeFredHTTP()
    result = _execute(monkeypatch, _keyed_adapter(http), series_id="DGS10", frequency="fortnightly")
    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []
    assert "fortnightly" in result.data["reason"]
    assert http.observation_params() == []
