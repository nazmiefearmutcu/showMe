"""CPF#1 — an unmapped or unsupported series must never be served with another
instrument's prices (no Henry Hub futures under a European gas label, no WTI
under an unknown id). Network is patched; no real Yahoo call is made.
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.commodity._funcs import CPF_SERIES_MAP, CPFFunction


def _recording_history(calls: list[str]):
    async def _fake(self, symbol: str, timeout: float):  # noqa: ARG001
        calls.append(symbol)
        return [
            {"date": "2026-11-05", "value": 2.9},
            {"date": "2026-11-06", "value": 3.0},
        ]

    return _fake


def test_european_gas_series_is_not_mapped_to_henry_hub_futures(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(CPFFunction, "_yahoo_history", _recording_history(calls))

    result = asyncio.run(CPFFunction().execute(series_id="PNGASEUUSDM", horizon="1Y"))

    assert "PNGASEUUSDM" not in CPF_SERIES_MAP
    assert "NG=F" not in calls, "European gas must not be fetched from the Henry Hub contract"
    assert result.data["status"] == "input_error"
    assert result.data["actual"] == []
    assert result.data["forecast"] == []
    assert result.data["rows"] == []
    assert result.data["next_actions"]


def test_unknown_series_does_not_fall_back_to_wti(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(CPFFunction, "_yahoo_history", _recording_history(calls))

    result = asyncio.run(CPFFunction().execute(series_id="NOSUCHSERIES", horizon="1Y"))

    assert calls == [], "an unknown series must not fetch any other instrument (WTI CL=F)"
    assert result.data["status"] == "input_error"
    assert result.data["series_id"] == "NOSUCHSERIES"
    assert result.data["rows"] == []
    assert result.data["next_actions"]
