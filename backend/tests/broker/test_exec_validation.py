"""A02-2026-05-24 — EXEC route regressions.

Two related bugs in ``EXECFunction.execute`` (engine/functions/trade/exec.py):

1. Missing required fields surfaced as a raw ``KeyError`` repr in the
   ``reason`` field — ``"'parent_id'"`` was reaching the UI verbatim.
   Fix: validate required fields up-front and return a human-readable
   ``"missing required field(s): parent_id"`` message.

2. ``action=slice`` accepted orphan parent_ids — every slice was
   silently written to the SQLite table even when no parent had been
   opened. The metrics view then joined on parent_id and produced
   garbage rows. Fix: ``get_parent`` lookup before insert; 404-flavoured
   ``status="unknown_parent"`` result if absent.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from showme.engine.functions.trade.exec import EXECFunction
from showme.engine.services import exec_monitor


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path: Path):
    """Point ``runtime_path`` at an empty tmpdir so each test gets a
    fresh exec_monitor.sqlite. We also reset the SQLite connection's
    cached path if any other test has touched it."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    # exec_monitor uses ``runtime_path`` lazily on each call, so the
    # env var swap above is enough — no module-level state to reset.
    yield


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ── Missing required fields ────────────────────────────────────────────


def test_open_missing_parent_id_returns_reason_not_keyerror_repr():
    fn = EXECFunction()
    result = _run(fn.execute(action="open", symbol="AAPL", side="buy", target_qty=100))
    assert result.data["status"] == "invalid_request"
    reason = result.data["reason"]
    assert "missing required field" in reason
    assert "parent_id" in reason
    # The bug was returning literal "'parent_id'" (with quotes — the
    # default ``str(KeyError("parent_id"))`` repr). Make sure that
    # shape can never reappear.
    assert reason != "'parent_id'"
    assert "parent_id" in result.data["missing_fields"]


def test_slice_missing_qty_returns_clean_reason():
    """Slice path also gets clean validation, not a KeyError repr."""
    fn = EXECFunction()
    # Open the parent first so we don't trip the orphan check below.
    _run(fn.execute(action="open", parent_id="P1", symbol="AAPL",
                    side="buy", target_qty=100))
    result = _run(fn.execute(action="slice", parent_id="P1", slice_idx=0,
                             avg_px=200.0))
    assert result.data["status"] == "invalid_request"
    assert "qty" in result.data["reason"]
    assert "qty" in result.data["missing_fields"]


def test_close_missing_parent_id_returns_clean_reason():
    fn = EXECFunction()
    result = _run(fn.execute(action="close"))
    assert result.data["status"] == "invalid_request"
    assert "parent_id" in result.data["reason"]


def test_get_missing_parent_id_returns_clean_reason():
    fn = EXECFunction()
    result = _run(fn.execute(action="get"))
    assert result.data["status"] == "invalid_request"
    assert "parent_id" in result.data["reason"]


def test_missing_field_treats_none_and_empty_string_as_missing():
    """None and "" must not slip past validation as 'present'."""
    fn = EXECFunction()
    result_none = _run(fn.execute(action="open", parent_id=None, symbol="AAPL",
                                  side="buy", target_qty=100))
    assert result_none.data["status"] == "invalid_request"
    result_blank = _run(fn.execute(action="open", parent_id="", symbol="AAPL",
                                   side="buy", target_qty=100))
    assert result_blank.data["status"] == "invalid_request"


# ── Orphan slice rejection ─────────────────────────────────────────────


def test_slice_against_nonexistent_parent_is_rejected():
    fn = EXECFunction()
    result = _run(fn.execute(action="slice", parent_id="GHOST-PARENT",
                             slice_idx=0, qty=10, avg_px=200.0))
    assert result.data["status"] == "unknown_parent"
    assert "GHOST-PARENT" in result.data["reason"]
    assert "open it with action=open first" in result.data["reason"]
    # The slice MUST NOT be persisted.
    parent = exec_monitor.get_parent("GHOST-PARENT")
    assert parent is None
    # Direct probe: count slices written under that parent_id.
    rows = exec_monitor.list_parents(symbol=None)
    assert all(r["parent_id"] != "GHOST-PARENT" for r in rows)


def test_slice_against_real_parent_records_successfully():
    """Sanity check: the orphan guard doesn't break the happy path."""
    fn = EXECFunction()
    _run(fn.execute(action="open", parent_id="P-OK", symbol="AAPL",
                    side="buy", target_qty=100, arrival_price=200.0))
    result = _run(fn.execute(action="slice", parent_id="P-OK", slice_idx=0,
                             qty=50, avg_px=200.5))
    assert "slice_id" in result.data
    parent = exec_monitor.get_parent("P-OK")
    assert parent is not None
    assert parent["metrics"]["filled_qty"] == pytest.approx(50.0)


# ── Field-coercion errors still surface cleanly ────────────────────────


def test_invalid_numeric_field_returns_clean_reason():
    """``target_qty="not-a-number"`` should yield ``invalid field value``
    rather than letting the ValueError bubble up to the route layer."""
    fn = EXECFunction()
    result = _run(fn.execute(action="open", parent_id="P-BAD", symbol="AAPL",
                             side="buy", target_qty="not-a-number"))
    assert result.data["status"] == "invalid_request"
    assert "invalid field value" in result.data["reason"]
