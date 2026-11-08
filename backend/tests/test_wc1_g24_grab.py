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


def test_grab_with_recipient_stays_draft_only():
    res = _run(
        GRABFunction(FunctionDeps()).execute(target="current_pane", recipient="ops@example.com")
    )
    assert res.data["status"] == "draft_only"
    email = next(r for r in res.data["rows"] if r["step"] == "email")
    assert email["status"] == "draft_only"
    assert all(r["status"] != "sent" for r in res.data["rows"])
