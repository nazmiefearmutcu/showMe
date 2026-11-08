"""WIRP field dictionary must describe implied_change_bp as cumulative to the meeting.

The CME-derived rows bucket every meeting's target-range distribution against
the same anchor, so implied_change_bp is the expected move vs the anchor at
that meeting (cumulative to that date), not an incremental move. Consumers
that sum it across meetings would double-count, so the label must say so.
"""
from __future__ import annotations

import asyncio

import showme.engine.functions.macro.wirp as wirp_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro.wirp import WIRPFunction


def _run(**params):
    return asyncio.run(WIRPFunction(deps=FunctionDeps()).execute(**params))


def test_implied_change_bp_is_labelled_cumulative_not_incremental(monkeypatch) -> None:
    async def _fred_down(url, timeout=8.0):
        raise RuntimeError("network unreachable")

    async def _irx_down():
        return None, None

    monkeypatch.setattr(wirp_mod, "_fetch_fred_latest", _fred_down)
    monkeypatch.setattr(wirp_mod, "_fetch_irx_implied_rate", _irx_down)
    result = _run(central_bank="FED", meetings=3)
    label = result.data["field_dictionary"]["implied_change_bp"].lower()
    assert "cumulative" in label, label
    assert "vs the" in label and "anchor" in label, label
