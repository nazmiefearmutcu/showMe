"""StrategyStore CRUD tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from showme.strategies.spec import IndicatorRef, Rule, StrategySpec
from showme.strategies.store import StrategyStore, UnknownStrategy


def _spec(name="t") -> StrategySpec:
    return StrategySpec(
        name=name,
        indicators=[IndicatorRef(alias="rsi14", id="rsi", params={"period": 14})],
        entry_rules=[Rule(kind="crosses_below", left="rsi14", right="literal:30")],
        exit_rules=[Rule(kind="crosses_above", left="rsi14", right="literal:70")],
    )


@pytest.fixture
def store(tmp_path: Path) -> StrategyStore:
    return StrategyStore(tmp_path / "strategies")


def test_save_and_get(store: StrategyStore):
    s = store.save(_spec())
    got = store.get(s.id)
    assert got.id == s.id
    assert got.name == "t"


def test_list_returns_meta(store: StrategyStore):
    a = store.save(_spec("a"))
    b = store.save(_spec("b"))
    lst = store.list()
    assert {m.id for m in lst} == {a.id, b.id}
    assert {m.name for m in lst} == {"a", "b"}


def test_get_unknown_raises(store: StrategyStore):
    with pytest.raises(UnknownStrategy):
        store.get("missing")


def test_delete_round_trip(store: StrategyStore):
    s = store.save(_spec())
    assert store.delete(s.id) is True
    assert store.delete(s.id) is False
    with pytest.raises(UnknownStrategy):
        store.get(s.id)


def test_save_preserves_created_at_on_update(store: StrategyStore):
    s = store.save(_spec("v1"))
    original_created = s.created_at
    updated_spec = s.model_copy(update={"name": "v2"})
    saved2 = store.save(updated_spec)
    assert saved2.created_at == original_created
    assert saved2.updated_at != original_created
    assert saved2.name == "v2"


def test_fresh_uses_app_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    store = StrategyStore.fresh()
    s = store.save(_spec())
    assert (tmp_path / "strategies" / f"{s.id}.json").exists()
