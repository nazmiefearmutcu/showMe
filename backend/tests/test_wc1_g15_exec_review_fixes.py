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


# --- EXEC#5: no VWAP label for the typical-price benchmark ---------------------

def test_benchmark_input_hint_does_not_claim_vwap() -> None:
    """The benchmark is the bar typical price (H+L+C)/3, not a volume-weighted VWAP."""
    from showme.manifest.seeds.exec_seed import exec_

    spec = next(i for i in exec_.inputs if i.name == "benchmark_px")
    assert "vwap" not in (spec.description or "").lower(), spec.description


def test_seed_module_doc_does_not_claim_live_vwap_or_broker_feed() -> None:
    from showme.manifest.seeds import exec_seed

    doc = exec_seed.__doc__ or ""
    assert "Live VWAP" not in doc
    assert "LIVE_EXCHANGE" not in doc


# --- EXEC#8: the monitor pace is documented as what it computes ----------------

def test_monitor_pace_pct_is_fill_progress_minus_time_progress() -> None:
    """Monitor pace_pct = (filled/target - elapsed/horizon) * 100, in percentage
    points. 25 of 100 filled at half the horizon is 25 points behind."""
    from showme.engine.services.exec_monitor import compute_metrics

    parent = dict(
        target_qty=100.0, arrival_price=300.0, side="BUY", started_at=1000,
        horizon_seconds=600, ended_at=1300, status="live",
    )
    slices = [{"slice_idx": 0, "ts": 1100, "qty": 25.0, "avg_px": 300.0,
               "benchmark_px": None, "vwap_running": None}]
    metrics = compute_metrics(parent, slices)
    assert metrics["pace_pct"] == pytest.approx(-25.0)


def test_seed_pace_documentation_matches_the_computed_pace() -> None:
    """The seed must not document pace as filled/scheduled, which is not what the
    monitor computes and not the figure plan mode reports (schedule_pct)."""
    from showme.manifest.seeds.exec_seed import exec_

    pace = exec_.formula_dict["Pace"]
    assert "scheduled_qty" not in pace.variables, pace.variables
    assert "elapsed_s" in pace.variables and "horizon_s" in pace.variables, pace.variables
    assert "cumulative_volume_fraction" not in exec_.methodology
    assert "percentage points" in exec_.field_dict["orders[].pace_pct"].description
