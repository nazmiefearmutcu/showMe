"""GRAB#2 regression: the manifest seed describes the shipped Screenshot Email
capture plan, not a shopping list."""

from __future__ import annotations

from showme.manifest.seeds.grab_seed import grab


def test_grab_seed_name_matches_shipped_function():
    assert grab.name == "Screenshot Email"


def test_grab_seed_inputs_are_the_ones_the_handler_reads():
    names = {i.name for i in grab.inputs}
    assert names == {"target", "recipient"}


def test_grab_seed_does_not_describe_a_shopping_list():
    text = f"{grab.name} {grab.intent} {grab.methodology}".lower()
    assert "shopping" not in text
    assert "errand" not in text
    assert "status" not in grab.defaults


def test_grab_seed_semantic_test_forbids_silent_send():
    descriptions = " ".join(t.description.lower() for t in grab.semantic_tests)
    assert "send" in descriptions or "transmi" in descriptions
