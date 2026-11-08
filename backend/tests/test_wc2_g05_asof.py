"""WC2-G05 / ASOF-2: the envelope asOf is the data observation date, not compute time."""

from __future__ import annotations

from showme.function_contracts import normalize_function_contract

_FETCHED = "2026-11-08T10:00:00+00:00"


def _env(data, *, metadata=None, sources=("fred",)):
    payload = {
        "data": data,
        "sources": list(sources),
        "metadata": metadata or {},
        "fetched_at": _FETCHED,
    }
    return normalize_function_contract("ECST", {}, payload)


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


def test_asof_uses_declared_metadata_as_of() -> None:
    out = _env({"value": 1.0}, metadata={"as_of": "2026-11-06T21:00:00+00:00"})
    assert out["asOf"] == "2026-11-06T21:00:00+00:00"


def test_asof_is_null_when_no_observation_date_is_declared() -> None:
    out = _env({"value": 1.0})
    assert out["asOf"] is None
    assert out["retrievedAt"] == _FETCHED
    assert all(d["asOf"] is None for d in out["sourceDetails"])


def test_asof_ignores_fetch_time_even_when_rows_have_no_dates() -> None:
    out = _env({"rows_text": "no date"})
    assert out["asOf"] != _FETCHED
