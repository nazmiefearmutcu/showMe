"""BotStore CRUD tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from showme.bots.record import BotRecord, SignalEntry
from showme.bots.store import BotStore, UnknownBot


def _bot(symbol: str = "BTC/USDT") -> BotRecord:
    return BotRecord(strategy_id="s", credential_id="c", exchange_id="binance",
                     symbol=symbol)


@pytest.fixture
def store(tmp_path: Path) -> BotStore:
    return BotStore(tmp_path / "bots")


def test_save_and_get(store: BotStore):
    b = store.save(_bot())
    got = store.get(b.id)
    assert got.id == b.id
    assert got.symbol == "BTC/USDT"


def test_list_returns_meta(store: BotStore):
    a = store.save(_bot("AAA/USDT"))
    b = store.save(_bot("BBB/USDT"))
    lst = store.list()
    assert {m.id for m in lst} == {a.id, b.id}
    assert {m.symbol for m in lst} == {"AAA/USDT", "BBB/USDT"}


def test_get_unknown_raises(store: BotStore):
    with pytest.raises(UnknownBot):
        store.get("missing")


def test_delete_round_trip(store: BotStore):
    b = store.save(_bot())
    assert store.delete(b.id) is True
    assert store.delete(b.id) is False
    with pytest.raises(UnknownBot):
        store.get(b.id)


def test_save_preserves_created_at(store: BotStore):
    b = store.save(_bot())
    original = b.created_at
    updated = b.model_copy(update={"symbol": "ETH/USDT"})
    b2 = store.save(updated)
    assert b2.created_at == original
    assert b2.symbol == "ETH/USDT"


def test_save_persists_signal_log(store: BotStore):
    b = _bot()
    b = b.append_signal(SignalEntry(bar_index=1, bar_time="t1", kind="entry",
                                    price=100.0, action="shadow"))
    saved = store.save(b)
    got = store.get(saved.id)
    assert len(got.signal_log) == 1
    assert got.last_processed_event is not None


def test_fresh_uses_app_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    store = BotStore.fresh()
    b = store.save(_bot())
    assert (tmp_path / "bots" / f"{b.id}.json").exists()
