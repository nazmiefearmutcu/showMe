"""WC1-g15 review follow-ups for EXEC (EXEC#7 open path, EXEC#8 seed column).

EXEC#7: the monitor action=open recorded any algo tag verbatim (MARKET, ARRIVAL,
POV), although nothing schedules those algos. The seed now offers only
TWAP/VWAP/ICEBERG/SNIPER, so open must refuse other tags explicitly and must not
store them.

EXEC#8: a plan row reports schedule_pct, so the seed's table must expose that
column; pace_pct stays for monitor rows.

The SQLite store is isolated per test; no market feed is touched.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.trade.exec import EXECFunction
from showme.engine.services import exec_monitor


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    assert exec_monitor.list_parents() == []


def _open(parent_id: str, **overrides):
    args = dict(action="open", parent_id=parent_id, symbol="AAPL", side="BUY", target_qty=100)
    args.update(overrides)
    return asyncio.run(EXECFunction().execute(**args))


# --- EXEC#7: open refuses algos the engine does not schedule ------------------

@pytest.mark.parametrize("algo", ["MARKET", "ARRIVAL", "POV"])
def test_open_refuses_unscheduled_algo_and_stores_nothing(algo) -> None:
    res = _open("P-REFUSE", algo=algo)
    assert res.data["status"] == "unsupported_algo", res.data
    assert set(res.data["supported_algos"]) == {"TWAP", "VWAP", "ICEBERG", "SNIPER"}
    assert exec_monitor.get_parent("P-REFUSE") is None


@pytest.mark.parametrize("algo", ["TWAP", "VWAP", "ICEBERG", "SNIPER"])
def test_open_accepts_supported_algo(algo) -> None:
    res = _open("P-OK-" + algo, algo=algo)
    assert "status" not in res.data or res.data["status"] == "ok", res.data
    parent = exec_monitor.get_parent("P-OK-" + algo)
    assert parent is not None
    assert parent["algo"] == algo


def test_open_normalises_lowercase_algo_to_canonical_tag() -> None:
    _open("P-LOWER", algo="vwap")
    assert exec_monitor.get_parent("P-LOWER")["algo"] == "VWAP"


def test_open_without_algo_defaults_to_twap() -> None:
    _open("P-DEFAULT")
    assert exec_monitor.get_parent("P-DEFAULT")["algo"] == "TWAP"


# --- EXEC#8: the seed table exposes the plan's schedule column ----------------

def test_seed_table_exposes_schedule_pct_and_keeps_pace_pct_for_monitor() -> None:
    from showme.manifest.seeds.exec_seed import exec_

    keys = [c.key for c in exec_.table_schema.columns]
    assert "schedule_pct" in keys
    assert "pace_pct" in keys
