"""ALRT#8 — the seed must describe the backend rule store, not a removed model.

Reviewer follow-up on p2a-g02: semantic tests still documented the removed
``active`` / ``fired_count`` fields and a feed-consuming evaluator, and a card
slot (``storage_mode``) was declared but no backend code emits it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
for p in (str(BACKEND), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from showme.engine.functions.misc.alrt import ALRTFunction  # noqa: E402
from showme.manifest.seeds.alrt_seed import alrt  # noqa: E402


@pytest.fixture
def alrt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yield tmp_path


@pytest.mark.asyncio
async def test_every_card_slot_is_emitted_by_the_backend(alrt_home: Path) -> None:
    """A card slot with no producer renders an always-empty badge."""
    listed = (await ALRTFunction().execute(action="list")).data
    slot_keys = {s.key for s in alrt.card_schema.slots}
    missing = slot_keys - set(listed)
    assert not missing, f"card slots with no backend producer: {sorted(missing)}"


def test_semantic_tests_do_not_describe_removed_fields() -> None:
    for test in alrt.semantic_tests:
        text = f"{test.description} {' '.join(test.assertions)}"
        for stale in ("active", "fired_count", "fired_today", "last_fired_at"):
            assert stale not in text, (test.name, stale, text)


def test_semantic_tests_do_not_claim_feed_consumption() -> None:
    """ALRT owns its rule store and consumes no WATCH/QUOTE/TOP output."""
    for test in alrt.semantic_tests:
        assert "ALRT consumes" not in test.description, test.name
        assert "consumes WATCH" not in test.description, test.name
