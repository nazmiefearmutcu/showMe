"""WC1-G24 GRAB#1: the top-level status must not claim a draft exists when no
recipient was given. No network is used; GRAB never transmits anything.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc._extras import GRABFunction


def _run(coro):
    return asyncio.run(coro)


def test_grab_without_recipient_is_not_configured_not_draft():
    res = _run(GRABFunction(FunctionDeps()).execute(target="current_pane"))
    email = next(r for r in res.data["rows"] if r["step"] == "email")
    assert email["status"] == "not_configured"
    assert res.data["status"] == "not_configured"


def test_grab_with_recipient_is_planned_not_a_draft():
    res = _run(
        GRABFunction(FunctionDeps()).execute(target="current_pane", recipient="ops@example.com")
    )
    # No draft object is created by this function, so the top-level status
    # must not claim one.
    assert res.data["status"] == "planned"
    assert res.data["status"] != "draft_only"
    assert all("draft" not in card["value"] for card in res.data["cards"])
    assert all(r["status"] != "sent" for r in res.data["rows"])
    assert res.sources == ["local_capture_plan"]


def test_grab_capture_row_is_planned_and_top_status_has_no_draft_object():
    res = _run(
        GRABFunction(FunctionDeps()).execute(target="current_pane", recipient="ops@example.com")
    )
    capture = next(r for r in res.data["rows"] if r["step"] == "capture")
    assert capture["status"] == "planned"
    assert "draft" not in res.data
    assert "data_state" not in res.data
