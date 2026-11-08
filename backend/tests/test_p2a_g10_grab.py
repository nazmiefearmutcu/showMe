"""GRAB#2 regression: the manifest seed describes the shipped Screenshot Email
capture plan, not a shopping list."""

from __future__ import annotations

from showme.manifest.seeds.grab_seed import grab


def test_grab_seed_name_matches_shipped_function():
    assert grab.name == "Screenshot Email"


def test_grab_seed_inputs_are_the_ones_the_handler_reads():
    names = {i.name for i in grab.inputs}
    assert names == {"target", "recipient", "send"}


def test_grab_seed_does_not_describe_a_shopping_list():
    text = f"{grab.name} {grab.intent} {grab.methodology}".lower()
    assert "shopping" not in text
    assert "errand" not in text
    assert "status" not in grab.defaults


def test_grab_seed_semantic_test_forbids_silent_send():
    descriptions = " ".join(t.description.lower() for t in grab.semantic_tests)
    assert "send" in descriptions or "transmi" in descriptions


# ── Review 2026-11-08: GRAB seed and handler agree; no phantom capture (GRAB#2) ──


def test_grab_seed_declares_every_input_the_handler_reads():
    names = {i.name for i in grab.inputs}
    assert {"target", "recipient", "send"} <= names


def test_grab_seed_semantic_test_inputs_are_declared():
    declared = {i.name for i in grab.inputs}
    for test in grab.semantic_tests:
        assert set(test.inputs) <= declared, test.name


def test_grab_send_request_is_recorded_and_never_transmitted():
    import asyncio

    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.misc._extras import GRABFunction

    res = asyncio.run(GRABFunction(FunctionDeps()).execute(
        target="current_pane", recipient="ops@example.com", send=True,
    ))
    email = next(r for r in res.data["rows"] if r["step"] == "email")
    assert email["status"] == "draft_only"
    assert all(r["status"] != "sent" for r in res.data["rows"])
    assert any("not executed" in w for w in res.warnings)


def test_grab_capture_row_does_not_claim_a_screenshot_exists():
    import asyncio

    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.misc._extras import GRABFunction

    res = asyncio.run(GRABFunction(FunctionDeps()).execute(target="current_pane"))
    capture = next(r for r in res.data["rows"] if r["step"] == "capture")
    assert capture["status"] == "planned"
    assert "screenshot artifact" not in capture["output"]
