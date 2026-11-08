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


# ---------------------------------------------------------------------------
# TCA#7 — an FX pair such as EURUSD ends in "USD" but is not crypto, so its
# benchmark must not be requested from Binance.
# ---------------------------------------------------------------------------
class _CountingBinance:
    def __init__(self):
        self.calls: list[str] = []

    async def klines(self, symbol, interval="5m", limit=288, **kwargs):
        self.calls.append(symbol)
        return [{"high": 1.1, "low": 1.1, "close": 1.1, "volume": 10.0}]


def test_fx_pair_ending_in_usd_is_not_routed_to_binance(tmp_path, monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.trade.tca import TCAFunction

    _use_temp_home(tmp_path, monkeypatch)
    yf_calls: list[str] = []

    async def _fake_yf(self, symbol, *args, **kwargs):
        yf_calls.append(symbol)
        return []

    monkeypatch.setattr(TCAFunction, "_yfinance_intraday", _fake_yf)
    binance = _CountingBinance()
    _seed_fx = BotStore.fresh()
    _seed_fx.save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol="EURUSD", timeframe="1h", mode="live", enabled=True,
        signal_log=[SignalEntry(
            bar_index=0, bar_time="2026-06-01T00:00:00Z", kind="entry",
            price=1.10, action="placed", order_id="fx1",
            fill_price=1.11, qty=1000.0,
        )],
    ))

    res = _run(TCAFunction(deps=FunctionDeps(binance=binance)).execute(
        symbol="EURUSD", benchmark="VWAP"))

    assert binance.calls == [], binance.calls
    assert yf_calls == ["EURUSD"], yf_calls
    assert res.data["rows"][0]["benchmark_source"] == "arrival"
