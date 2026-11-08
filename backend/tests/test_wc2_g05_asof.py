"""WC2-G05 / ASOF-2: the envelope asOf is the data observation date, not compute time."""

from __future__ import annotations

from showme.function_contracts import normalize_function_contract

_FETCHED = "2026-11-08T10:00:00+00:00"
_COMPUTE_STAMP = "2026-11-08T07:56:00+00:00"


def _env(data, *, metadata=None, sources=("fred",), code="ECST"):
    payload = {
        "data": data,
        "sources": list(sources),
        "metadata": metadata or {},
        "fetched_at": _FETCHED,
    }
    return normalize_function_contract(code, {}, payload)


def test_asof_is_latest_row_observation_date_not_fetch_time() -> None:
    rows = [
        {"observation_date": "2026-08-01", "value": 4.1},
        {"observation_date": "2026-09-01", "value": 4.2},
    ]
    out = _env({"series": rows})
    assert out["asOf"].startswith("2026-09-01"), out["asOf"]
    assert out["asOf"] != _FETCHED
    assert out["retrievedAt"] == _FETCHED
    assert all(d["asOf"].startswith("2026-09-01") for d in out["sourceDetails"])


def test_asof_uses_declared_observation_date_in_metadata() -> None:
    out = _env({"value": 1.0}, metadata={"as_of": "2026-11-06"})
    assert out["asOf"].startswith("2026-11-06"), out["asOf"]


def test_asof_is_null_when_no_observation_date_is_declared() -> None:
    out = _env({"value": 1.0})
    assert out["asOf"] is None
    assert out["retrievedAt"] == _FETCHED
    assert all(d["asOf"] is None for d in out["sourceDetails"])


def test_asof_ignores_fetch_time_even_when_rows_have_no_dates() -> None:
    out = _env({"rows_text": "no date"})
    assert out["asOf"] != _FETCHED


def test_compute_time_stamp_in_data_is_not_an_observation_date() -> None:
    # PORT/ECO producers stamp data['as_of'] = datetime.now() at compute time.
    out = _env({"as_of": _COMPUTE_STAMP, "positions": [], "totals": {}}, code="PORT")
    assert out["asOf"] is None, out["asOf"]
    assert out["retrievedAt"] == _FETCHED


def test_compute_time_stamp_in_metadata_is_not_an_observation_date() -> None:
    out = _env({"value": 1.0}, metadata={"as_of": _COMPUTE_STAMP}, code="ECO")
    assert out["asOf"] is None, out["asOf"]


def test_compute_stamp_does_not_override_a_real_row_observation_date() -> None:
    rows = [{"observation_date": "2026-09-01", "value": 4.2}]
    out = _env({"series": rows, "as_of": _COMPUTE_STAMP}, code="ECO")
    assert out["asOf"].startswith("2026-09-01"), out["asOf"]


def test_future_row_dates_are_not_observation_dates() -> None:
    # An upcoming event date (e.g. an earnings calendar row) is not an observation.
    rows = [
        {"date": "2026-09-01", "value": 1.0},
        {"date": "2026-12-15", "value": 2.0},
    ]
    out = _env({"rows_data": rows})
    assert out["asOf"].startswith("2026-09-01"), out["asOf"]


def test_row_timestamp_at_fetch_time_is_not_an_observation_date() -> None:
    rows = [{"timestamp": "2026-11-08T09:59:59+00:00", "value": 1.0}]
    out = _env({"rows_data": rows})
    assert out["asOf"] is None, out["asOf"]
