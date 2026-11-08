"""Regression tests for the wb1-g02 TCA findings (TCA#2..#8, TCA-R1).

All network access is patched: benchmark fetchers are replaced by fakes, so
the suite never reaches Binance or Yahoo.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.bots.record import BotRecord, SignalEntry
from showme.bots.store import BotStore


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _use_temp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setattr(
        "showme.engine.services.order_history.runtime_path",
        lambda name: tmp_path / "runtime" / name,
    )
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# TCA#8 — the seed must describe the summary mean as count-weighted, which is
# what tca.py computes (sum / len), not notional-weighted.
# ---------------------------------------------------------------------------
def test_tca_seed_describes_avg_slippage_as_count_weighted():
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    desc = REGISTRY.get("TCA").field_dict["summary.avg_slippage_bps"].description.lower()
    assert "notional" not in desc, desc
    assert "count" in desc, desc
