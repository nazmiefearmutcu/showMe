"""Default-seed tests: KAOS Multibot is THE default bot everywhere.

lifespan seed (first run, empty store), templates.yml first template, and
config/default.yaml bot defaults.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from showme.bots.store import BotStore


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    return tmp_path


def test_seed_on_empty_store(home):
    from showme.bots.kaos.config import DEFAULT_KAOS_BOT_NAME
    from showme.bots.lifespan import _seed_default_kaos_bot

    store = BotStore.fresh()
    saved = _seed_default_kaos_bot(store)
    assert saved is not None
    assert saved.engine == "kaos"
    assert saved.mode == "shadow"          # forced — existing rule
    assert saved.enabled is False          # same clamp as POST /api/bots
    assert saved.tick_interval_seconds == 60
    assert saved.timeframe == "15m"
    assert [v.id for v in saved.venues] == ["crypto", "nasdaq"]
    assert [v.market for v in saved.venues] == ["crypto-futures", "us-equities"]
    assert len(saved.venues[0].symbols) == 20
    assert len(saved.venues[1].symbols) == 20
    # The frozen default bot name lives on the bound strategy spec
    # (BotRecord is name-less; the UI surfaces the strategy name).
    from showme.strategies.store import StrategyStore
    spec = StrategyStore.fresh().get(saved.strategy_id)
    assert spec.name == DEFAULT_KAOS_BOT_NAME


def test_no_seed_when_bots_exist(home):
    from showme.bots.lifespan import _seed_default_kaos_bot
    from showme.bots.record import BotRecord

    store = BotStore.fresh()
    store.save(BotRecord(strategy_id="s", credential_id="c",
                         exchange_id="e", symbol="BTC/USDT"))
    assert _seed_default_kaos_bot(store) is None
    assert len(store.list()) == 1  # only the pre-existing bot


def test_seed_idempotent(home):
    from showme.bots.lifespan import _seed_default_kaos_bot

    store = BotStore.fresh()
    first = _seed_default_kaos_bot(store)
    assert first is not None
    assert _seed_default_kaos_bot(store) is None
    assert len(store.list()) == 1


def test_seeded_bot_survives_a_record_roundtrip(home):
    """Old runner/store code paths (list/get/save) accept the new fields."""
    from showme.bots.lifespan import _seed_default_kaos_bot

    store = BotStore.fresh()
    _seed_default_kaos_bot(store)
    meta = store.list()[0]
    assert meta.engine == "kaos"
    rec = store.get(meta.id)
    assert rec.engine == "kaos"
    again = store.save(rec)
    assert again.engine == "kaos"
    assert len(again.venues) == 2


def test_startup_seeds_default_bot(home):
    """The real lifespan startup path seeds + replays without spawning
    the seeded bot (enabled=False)."""
    import asyncio

    from showme.bots import lifespan

    asyncio.run(lifespan.startup())
    store = BotStore.fresh()
    metas = store.list()
    assert len(metas) == 1
    assert metas[0].engine == "kaos"
    assert metas[0].enabled is False
    assert not lifespan.get_runner().is_running(metas[0].id)
    # idempotent across boots
    asyncio.run(lifespan.startup())
    assert len(BotStore.fresh().list()) == 1


def test_templates_first_entry_is_kaos_multibot():
    from showme.templates.loader import load_template_catalog

    backend = Path(__file__).resolve().parents[1]
    cat = load_template_catalog(
        backend / "showme" / "templates" / "catalog" / "templates.yml",
    )
    first = cat.entries[0]
    assert first.id == "kaos-multibot"
    assert first.name == "KAOS Multibot"
    assert first.engine == "kaos"
    assert [v["id"] for v in first.venues] == ["crypto", "nasdaq"]
    # spec-rule templates keep the byte-compatible default
    assert cat.entries[1].engine == "spec"
    assert cat.entries[1].venues == ()


def test_config_default_yaml_bot_defaults():
    backend = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load(
        (backend / "config" / "default.yaml").read_text(encoding="utf-8"),
    )
    bots = cfg["bots"]
    assert bots["default_engine"] == "kaos"
    assert bots["default_name"] == "KAOS Multibot"
    assert bots["default_mode"] == "shadow"
    assert bots["default_timeframe"] == "15m"
    assert bots["default_tick_interval_seconds"] == 60
    venues = {v["id"]: v for v in bots["venues"]}
    assert set(venues) == {"crypto", "nasdaq"}
    assert venues["crypto"]["exchange_id"] == "binanceusdm"
    assert venues["nasdaq"]["exchange_id"] == "alpaca"
    assert len(venues["crypto"]["symbols"]) == 20
    assert len(venues["nasdaq"]["symbols"]) == 20
