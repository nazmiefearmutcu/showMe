"""P1a-g01 regressions for EXEC action=plan labelling (EXEC#1) and monitor cards (EXEC#4).

EXEC#1: the plan path replays historical intraday bars but used to stamp
``cards.data_mode = "live_exchange"``. It must say ``historical_replay``.

EXEC#4: the plan path hard-coded ``open_parents = 1`` and ``needs_close = 0``
without reading the monitor store. The cards must reflect the real store.

The market feed is patched (no network); the SQLite store is isolated per test.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import showme.chart_history as ch
from showme.engine.functions.trade.exec import EXECFunction
from showme.engine.services import exec_monitor


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    assert exec_monitor.list_parents() == []


class _History:
    def __init__(self, rows: list[dict[str, Any]], source: str) -> None:
        self.rows = rows
        self.source = source
        self.warnings: list[str] = []
        self.metadata: dict[str, Any] = {}


def _bars(n: int, step: int, t0: int = 1_793_995_500) -> list[dict[str, Any]]:
    out = []
    for i in range(n):
        base = 340.0 + i * 0.05
        out.append({
            "time": t0 + i * step,
            "open": base,
            "high": base + 0.5,
            "low": base - 0.5,
            "close": base + 0.2,
            "volume": 1000.0 + i,
        })
    return out


def _patch_feed(monkeypatch, n: int = 240) -> None:
    async def _fake_yahoo(**kwargs: Any) -> _History:
        step = 60 if kwargs["interval"] == "1m" else 300
        rows = _bars(n, step)[-int(kwargs["bars"]):]
        return _History(rows, "yahoo_chart")

    async def _fake_binance(**kwargs: Any) -> _History:
        step = 60 if kwargs["interval"] == "1m" else 300
        rows = _bars(n, step)[-int(kwargs["bars"]):]
        return _History(rows, "binance_spot")

    monkeypatch.setattr(ch, "fetch_yahoo_history", _fake_yahoo, raising=True)
    monkeypatch.setattr(ch, "fetch_binance_history", _fake_binance, raising=True)


def _plan(**overrides: Any):
    args: dict[str, Any] = dict(
        action="plan", symbol="AAPL", algo="TWAP", target_qty=100,
        horizon_seconds=600, slices=12, side="BUY",
    )
    args.update(overrides)
    return asyncio.run(EXECFunction().execute(**args))


def test_plan_data_mode_is_historical_replay_not_live(monkeypatch) -> None:
    """EXEC#1: a schedule replayed over stored bars is not a live exchange feed."""
    _patch_feed(monkeypatch)
    res = _plan()
    data = res.data
    assert data["status"] == "ok"
    assert data["cards"]["execution_mode"] == "planned"
    assert data["cards"]["data_mode"] == "historical_replay", data["cards"]["data_mode"]
    # The bar dates the replay used are visible in the payload.
    assert isinstance(data.get("schedule_start_ms"), int)
    assert isinstance(data.get("window_end_ms"), int)
    assert data["window_end_ms"] > data["schedule_start_ms"]


def test_plan_open_parents_is_zero_when_store_is_empty(monkeypatch) -> None:
    """EXEC#4: with no monitored parent the plan card must not claim one exists."""
    _patch_feed(monkeypatch)
    res = _plan()
    cards = res.data["cards"]
    assert cards["open_parents"] == 0, cards
    assert cards["needs_close"] == 0, cards


def test_plan_open_parents_counts_real_store_parents(monkeypatch) -> None:
    """EXEC#4: the card counts parents actually held by the monitor store."""
    exec_monitor.open_parent(
        parent_id="P1A-LIVE-1", symbol="AAPL", side="BUY", target_qty=100.0,
    )
    _patch_feed(monkeypatch)
    res = _plan()
    cards = res.data["cards"]
    assert cards["open_parents"] == 1, cards
    assert cards["needs_close"] == 0, cards
