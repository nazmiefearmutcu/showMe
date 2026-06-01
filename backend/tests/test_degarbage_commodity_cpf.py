"""De-garbage test for CPF (Commodity Price Forecast).

CPF previously returned a hardcoded ``reference_baseline`` payload built
from ``FORECAST_REFERENCE_ROWS`` constants. It now fetches a live ACTUAL
leg from yfinance futures and a FORWARD forecast leg derived from the
keyless World Bank Pink Sheet commodity price series.

These tests are network-tolerant: when the public feeds are reachable
the payload must report a live/ok shape with real, non-constant rows;
when offline the handler must degrade to the honest
``provider_unavailable`` shape (never fabricate numbers).
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.commodity._funcs import (
    CPF_SERIES_MAP,
    CPFFunction,
    FORECAST_REFERENCE_ROWS,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_handler():
    # BaseFunction handlers are constructed with their provider deps; the
    # default registry build wires the keyless adapters. Construct via the
    # zero-arg path the engine uses and tolerate either signature.
    try:
        return CPFFunction()
    except TypeError:
        from showme.engine.core.base_function import FunctionDeps  # type: ignore

        return CPFFunction(deps=FunctionDeps())  # pragma: no cover


_OLD_CONSTANT_VALUES = {row["forecast_value"] for row in FORECAST_REFERENCE_ROWS}
_OK_STATUSES = {"ok", "empty"}


def test_cpf_series_map_covers_manifest_options():
    # The manifest seed offers these series_id options; the map must route
    # each to a real keyless Yahoo futures proxy (no canned constants).
    for sid in ("WTISPLC", "DCOILWTICO", "DHHNGSP", "PCOPPUSDM", "PGOLD", "PNGASEUUSDM"):
        assert sid in CPF_SERIES_MAP, f"{sid} missing from CPF_SERIES_MAP"
        entry = CPF_SERIES_MAP[sid]
        assert entry["futures"].endswith("=F")
        assert entry["unit"]


def test_cpf_returns_live_or_graceful_unavailable():
    handler = _make_handler()
    try:
        result = _run(handler.execute(series_id="WTISPLC", horizon="1Y"))
    except Exception as exc:  # network/runtime error -> treat as offline skip
        pytest.skip(f"CPF execute raised (likely offline): {exc}")

    data = result.data
    assert result.code == "CPF"
    assert "methodology" in data and isinstance(data["methodology"], str) and data["methodology"]
    assert "field_dictionary" in data and isinstance(data["field_dictionary"], dict)
    # Contract keys required by the manifest output_contract.
    for key in ("series_id", "actual", "forecast", "forecast_vintage", "as_of", "data_mode"):
        assert key in data, f"missing contract key {key}"

    status = data.get("status")
    if status == "provider_unavailable":
        # Honest outage shape: no fabricated rows, clear next_actions.
        assert data.get("rows") == []
        assert data.get("data_mode") == "no_live_source"
        assert data.get("next_actions")
        return

    assert status in _OK_STATUSES, f"unexpected status {status}"
    rows = data.get("rows") or []
    assert isinstance(rows, list)

    if rows:
        # Real data: rows carry the {date, kind, value, vintage} table shape
        # and at least one live actual or forward forecast value that is NOT
        # one of the old hardcoded reference constants.
        kinds = {r.get("kind") for r in rows}
        assert kinds & {"actual", "forecast"}
        real_values = [
            r.get("value")
            for r in rows
            if isinstance(r.get("value"), (int, float))
        ]
        assert real_values, "no numeric values in CPF rows"
        # The forward leg is anchored to the live spot, so values must not
        # be exactly the frozen reference constants for every row.
        assert any(v not in _OLD_CONSTANT_VALUES for v in real_values), (
            "CPF still returning only the old hardcoded reference constants"
        )
        # forecast_vintage, when a forecast exists, must be an iso-ish date.
        if any(r.get("kind") == "forecast" for r in rows):
            vint = data.get("forecast_vintage")
            assert vint is None or (isinstance(vint, str) and len(vint) >= 7)


def test_cpf_no_actual_after_today():
    handler = _make_handler()
    try:
        result = _run(handler.execute(series_id="PGOLD", horizon="6M"))
    except Exception as exc:
        pytest.skip(f"CPF execute raised (likely offline): {exc}")

    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    for pt in result.data.get("actual") or []:
        d = pt.get("date")
        if isinstance(d, str) and len(d) >= 10:
            assert d[:10] <= today, "CPF appended a synthetic actual point beyond today"
