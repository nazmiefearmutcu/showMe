"""ALRT atomicity + silent-corruption regression tests.

Locks in S15 BugHunt fixes for `backend/showme/engine/functions/misc/alrt.py`:

1. Concurrent `add` calls do not lose alerts (was: load→append→save race
   would drop one of two simultaneous adds).
2. A corrupted `alerts.json` surfaces a warning instead of silently
   returning an empty list (was: bare `except Exception: return []`).
3. Save is atomic via `os.replace` so a half-written file cannot be
   left behind by a crashing writer.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from showme.engine.functions.misc.alrt import (  # noqa: E402
    ALRTFunction,
    _load_alerts,
    _save_alerts,
    _store,
)


@pytest.fixture
def alrt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yield tmp_path


@pytest.mark.asyncio
async def test_alrt_corrupted_store_emits_warning(alrt_home: Path) -> None:
    store = _store()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{ this is not valid json")

    fn = ALRTFunction()
    result = await fn.execute(action="list")

    assert result.data["count"] == 0
    assert any("unreadable" in w for w in result.warnings), (
        f"expected unreadable warning, got {result.warnings!r}"
    )


@pytest.mark.asyncio
async def test_alrt_concurrent_adds_do_not_drop(alrt_home: Path) -> None:
    fn = ALRTFunction()

    async def add(condition: str) -> None:
        await fn.execute(action="add", condition=condition)

    await asyncio.gather(*(add(f"AAPL.price > {200 + i}") for i in range(8)))

    listing = await fn.execute(action="list")
    assert listing.data["count"] == 8, (
        f"expected 8 alerts after 8 concurrent adds, got "
        f"{listing.data['count']}: {listing.data['alerts']!r}"
    )


@pytest.mark.asyncio
async def test_alrt_save_is_atomic_no_tmp_leftover(alrt_home: Path) -> None:
    fn = ALRTFunction()
    await fn.execute(action="add", condition="MSFT.price > 400")

    # After a successful save, only the canonical file should exist —
    # no .tmp residue, no half-written variants.
    store_dir = _store().parent
    leftovers = [p.name for p in store_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], f"unexpected tmp files leaked: {leftovers!r}"

    # And the store should parse as valid JSON list of dicts.
    payload = json.loads(_store().read_text())
    assert isinstance(payload, list)
    assert payload and payload[0]["condition"] == "MSFT.price > 400"


def test_alrt_load_returns_tuple(alrt_home: Path) -> None:
    alerts, warning = _load_alerts()
    assert alerts == []
    assert warning is None

    # Now write a corrupted store and confirm the warning path.
    store = _store()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("[{\"missing_required_id_field\": true}]")
    alerts, warning = _load_alerts()
    assert alerts == []
    assert warning is not None
    assert "unreadable" in warning


def test_alrt_save_round_trips(alrt_home: Path) -> None:
    from showme.engine.functions.misc.alrt import Alert

    alerts = [
        Alert(id="abc12345", condition="BTC.price > 80000"),
        Alert(id="def67890", condition="ETH.price < 2500", cooldown_seconds=120),
    ]
    _save_alerts(alerts)
    loaded, warning = _load_alerts()
    assert warning is None
    assert {a.id for a in loaded} == {"abc12345", "def67890"}
    assert {a.condition for a in loaded} == {
        "BTC.price > 80000",
        "ETH.price < 2500",
    }
