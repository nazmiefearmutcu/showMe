"""ALRT honesty regressions (p2a-g02).

Covers the ALRT function's data-honesty defects:

* ALRT#1 — a rule stored by ``add`` must not report success as if it fires;
  the response says it is stored but not armed (no evaluator in this build).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from showme.engine.functions.misc.alrt import ALRTFunction, _store  # noqa: E402


@pytest.fixture
def alrt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yield tmp_path


@pytest.mark.asyncio
async def test_add_reports_stored_not_armed(alrt_home: Path) -> None:
    """ALRT#1: add must say the rule is not armed, not a plain success."""
    fn = ALRTFunction()
    res = await fn.execute(action="add", condition="AAPL.price > 200")

    assert res.data["armed"] is False, res.data
    assert res.data["status"] == "stored_not_armed", res.data
    assert any("not armed" in w for w in res.warnings), res.warnings


async def _listed_count(fn: ALRTFunction) -> int:
    return (await fn.execute(action="list")).data["count"]


@pytest.mark.asyncio
async def test_add_builds_condition_from_seed_inputs(alrt_home: Path) -> None:
    """ALRT#2: the seed's symbol/field/direction/threshold/note are honoured."""
    fn = ALRTFunction()
    res = await fn.execute(
        action="add",
        symbol="AAPL",
        field="price",
        direction="above",
        threshold=200,
        note="breakout",
    )

    assert res.data.get("status") != "input_required", res.data
    assert res.data["condition"] == "AAPL.price > 200", res.data
    assert res.data["note"] == "breakout", res.data


@pytest.mark.asyncio
async def test_add_rejects_cross_direction_it_cannot_store(alrt_home: Path) -> None:
    """ALRT#2: cross_up/cross_down are not representable; refuse, do not store."""
    fn = ALRTFunction()
    res = await fn.execute(
        action="add", symbol="AAPL", field="price", direction="cross_up", threshold=200
    )

    assert res.data["status"] == "input_error", res.data
    assert await _listed_count(fn) == 0


@pytest.mark.asyncio
async def test_add_rejects_non_finite_threshold(alrt_home: Path) -> None:
    fn = ALRTFunction()
    res = await fn.execute(
        action="add", symbol="AAPL", field="price", direction="above", threshold="Infinity"
    )

    assert res.data["status"] == "input_error", res.data
    assert await _listed_count(fn) == 0


@pytest.mark.asyncio
async def test_add_rejects_unparseable_condition(alrt_home: Path) -> None:
    """ALRT#3: a condition the evaluator cannot parse is refused, not stored."""
    fn = ALRTFunction()
    res = await fn.execute(action="add", condition="zzz ??? not a rule")

    assert res.data["status"] == "input_error", res.data
    assert await _listed_count(fn) == 0


_CORRUPT_STORE = '[{"id": "old1", "condition": "AAPL.price > 100"'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"action": "add", "condition": "MSFT.price > 400"},
        {"action": "remove", "id": "old1"},
        {"action": "toggle", "id": "old1"},
    ],
    ids=["add", "remove", "toggle"],
)
async def test_mutations_do_not_overwrite_unreadable_store(alrt_home: Path, params: dict) -> None:
    """ALRT#4: an unreadable alerts.json must survive a later write intact."""
    store = _store()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(_CORRUPT_STORE)

    fn = ALRTFunction()
    res = await fn.execute(**params)

    assert res.data["status"] == "input_error", res.data
    assert store.read_text() == _CORRUPT_STORE, "unreadable store was overwritten"
    assert any("unreadable" in w for w in res.warnings), res.warnings


@pytest.mark.asyncio
async def test_add_accepts_documented_condition_forms(alrt_home: Path) -> None:
    fn = ALRTFunction()
    for cond in ("AAPL.price > 200", "BTCUSDT.price < 80000", "NEWS(AAPL).importance >= 70"):
        res = await fn.execute(action="add", condition=cond)
        assert res.data.get("status") != "input_error", (cond, res.data)
        assert res.data["condition"] == cond
    assert await _listed_count(fn) == 3
