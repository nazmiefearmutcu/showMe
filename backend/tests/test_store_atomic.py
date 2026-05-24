"""Faz 2 / S6 — Atomic JSON write regression tests for BotStore and
StrategyStore.

What we pin here:

1. The on-disk file is written via temp+replace — never a 0-byte
   midpoint visible to ``list()``.
2. A SIGKILL-equivalent (we simulate by aborting mid-write and leaving a
   ``*.json.tmp`` orphan or a stale 0-byte ``*.json``) keeps the
   *previous* record intact and never raises from ``list()``.
3. ``_iter_files`` ignores ``*.json.tmp`` siblings — these are the
   "in-flight" marker an interrupted ``save`` would leave behind.
4. An accidentally truncated 0-byte ``*.json`` file is logged at WARNING
   and skipped, not silently dropped without trace.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from showme.bots.record import BotRecord
from showme.bots.store import BotStore
from showme.strategies.spec import StrategySpec
from showme.strategies.store import StrategyStore


def _make_bot(symbol: str = "BTC/USDT") -> BotRecord:
    return BotRecord(
        strategy_id="abc123",
        credential_id="def456",
        exchange_id="binance",
        symbol=symbol,
    )


def _make_strategy() -> StrategySpec:
    return StrategySpec(
        name="RSI revert test",
        indicators=[{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
        entry_rules=[{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
        exit_rules=[{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
    )


# ─── BotStore ────────────────────────────────────────────────────────────


def test_bot_save_is_atomic_replace(tmp_path: Path):
    """After ``save`` succeeds the final file is non-empty and contains a
    parseable BotRecord; no ``*.tmp`` sibling is left around."""
    store = BotStore(tmp_path / "bots")
    saved = store.save(_make_bot())
    p = tmp_path / "bots" / f"{saved.id}.json"
    assert p.exists()
    assert p.stat().st_size > 0
    parsed = json.loads(p.read_text())
    assert parsed["id"] == saved.id
    assert parsed["symbol"] == "BTC/USDT"
    # No leftover tmp file.
    assert not (tmp_path / "bots" / f"{saved.id}.json.tmp").exists()


def test_bot_list_skips_tmp_files(tmp_path: Path):
    """An interrupted save leaves ``<id>.json.tmp`` on disk; ``list``
    must ignore it instead of returning a bogus record."""
    store = BotStore(tmp_path / "bots")
    saved = store.save(_make_bot())
    # Simulate a half-finished write of a *different* record:
    orphan = tmp_path / "bots" / "orphan-id.json.tmp"
    orphan.write_text('{"id":"orphan-id","strategy_id":"x"')  # truncated JSON
    metas = store.list()
    assert {m.id for m in metas} == {saved.id}
    # The orphan tmp file is still on disk — we don't delete it, just
    # ignore it. Cleanup can happen later out-of-band.
    assert orphan.exists()


def test_bot_list_skips_empty_file_with_warning(tmp_path: Path, caplog):
    """Simulate a crash that landed an empty *final* file (extremely
    rare with os.replace but still possible if external tooling
    truncates). ``list`` must skip + log WARNING, never crash."""
    store = BotStore(tmp_path / "bots")
    saved = store.save(_make_bot())
    # Drop an empty file as if a crash truncated a record.
    empty = tmp_path / "bots" / "zerobyte.json"
    empty.write_text("")
    with caplog.at_level(logging.WARNING, logger="showme.bots.store"):
        metas = store.list()
    assert {m.id for m in metas} == {saved.id}
    assert any("zerobyte.json" in r.message for r in caplog.records), (
        "expected WARNING about skipped empty file"
    )


def test_bot_crash_mid_write_keeps_previous_version(tmp_path: Path, monkeypatch):
    """Hard-simulate a crash mid-write by raising inside ``open().write``.
    Pre-existing record must remain readable; list() must return the
    pre-crash state and not raise."""
    store = BotStore(tmp_path / "bots")
    saved = store.save(_make_bot(symbol="OG/USDT"))
    p = tmp_path / "bots" / f"{saved.id}.json"
    original = p.read_text()

    # Monkeypatch open() so the next write fails AFTER the tmp file
    # has been created but BEFORE os.replace lands. This is exactly the
    # SIGKILL window S6 worried about.
    real_open = open
    call_count = {"n": 0}

    def flaky_open(path, *args, **kwargs):
        if str(path).endswith(".json.tmp"):
            call_count["n"] += 1
            if call_count["n"] == 1:
                fh = real_open(path, *args, **kwargs)
                fh.write("PARTIAL")  # land a few bytes
                fh.close()
                raise OSError("simulated mid-write crash")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky_open)
    with pytest.raises(OSError):
        store.save(saved.model_copy(update={"symbol": "MUTATED/USDT"}))
    monkeypatch.undo()

    # Final on-disk file is still the original — os.replace never ran.
    assert p.read_text() == original
    # And list() returns the old record, not a corrupt one, no exception.
    metas = store.list()
    assert {m.symbol for m in metas} == {"OG/USDT"}


def test_bot_save_fsync_called(tmp_path: Path, monkeypatch):
    """``save`` must fsync the temp file's fd before os.replace so a
    power loss between os.replace and dirent flush doesn't lose data."""
    seen: list[int] = []

    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        seen.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    store = BotStore(tmp_path / "bots")
    store.save(_make_bot())
    assert seen, "os.fsync was never called on save"


# ─── StrategyStore (mirror coverage) ─────────────────────────────────────


def test_strategy_save_is_atomic_replace(tmp_path: Path):
    store = StrategyStore(tmp_path / "strategies")
    saved = store.save(_make_strategy())
    p = tmp_path / "strategies" / f"{saved.id}.json"
    assert p.exists()
    assert p.stat().st_size > 0
    parsed = json.loads(p.read_text())
    assert parsed["id"] == saved.id
    assert not (tmp_path / "strategies" / f"{saved.id}.json.tmp").exists()


def test_strategy_list_skips_tmp_files(tmp_path: Path):
    store = StrategyStore(tmp_path / "strategies")
    saved = store.save(_make_strategy())
    orphan = tmp_path / "strategies" / "orphan-id.json.tmp"
    orphan.write_text('{"id":"orphan-id","name":"x"')
    metas = store.list()
    assert {m.id for m in metas} == {saved.id}


def test_strategy_list_skips_empty_file_with_warning(tmp_path: Path, caplog):
    store = StrategyStore(tmp_path / "strategies")
    saved = store.save(_make_strategy())
    empty = tmp_path / "strategies" / "zerobyte.json"
    empty.write_text("")
    with caplog.at_level(logging.WARNING, logger="showme.strategies.store"):
        metas = store.list()
    assert {m.id for m in metas} == {saved.id}
    assert any("zerobyte.json" in r.message for r in caplog.records)


def test_strategy_crash_mid_write_keeps_previous_version(tmp_path: Path, monkeypatch):
    store = StrategyStore(tmp_path / "strategies")
    saved = store.save(_make_strategy())
    p = tmp_path / "strategies" / f"{saved.id}.json"
    original = p.read_text()

    real_open = open
    call_count = {"n": 0}

    def flaky_open(path, *args, **kwargs):
        if str(path).endswith(".json.tmp"):
            call_count["n"] += 1
            if call_count["n"] == 1:
                fh = real_open(path, *args, **kwargs)
                fh.write("PARTIAL")
                fh.close()
                raise OSError("simulated mid-write crash")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky_open)
    with pytest.raises(OSError):
        store.save(saved.model_copy(update={"name": "MUTATED"}))
    monkeypatch.undo()
    assert p.read_text() == original
    metas = store.list()
    assert {m.name for m in metas} == {"RSI revert test"}
