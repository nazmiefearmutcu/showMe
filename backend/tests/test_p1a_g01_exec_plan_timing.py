"""P1a-g01 regressions for EXEC action=plan timing (EXEC#2, EXEC#3).

EXEC#2: when no arrival_price is supplied the arrival used to be the close of
the LAST bar of the window, so early slices were measured against an
end-of-window price (look-ahead). Arrival must be the decision price at the
schedule start.

EXEC#3: twelve slices were placed on the last twelve consecutive bars, so a
600 s horizon spanned 55 minutes. Each slice must map to the bar in effect at
its real release instant (schedule start + offset_s), so the rows stay inside
the requested horizon.

The market feed is patched (no network); the SQLite store is isolated per test.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

import showme.chart_history as ch
from showme.engine.functions.trade.exec import EXECFunction
from showme.engine.services import exec_monitor

_T0 = 1_793_995_500  # fixed epoch-s anchor (a bar boundary for both 1m and 5m)
# 600 s horizon / 12 slices = 50 s slot spacing, which selects the finest bars (1m).
_INTERVAL = "1m"


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


def _step_for(interval: str) -> int:
    return 60 if interval == "1m" else 300


def _full_bars(interval: str, n: int = 400) -> list[dict[str, Any]]:
    """Deterministic series with a RISING close so end-of-window != start."""
    step = _step_for(interval)
    out = []
    for i in range(n):
        base = 300.0 + i * 0.2
        out.append({
            "time": _T0 + i * step,
            "open": base,
            "high": base + 0.5,
            "low": base - 0.5,
            "close": base + 0.3,
            "volume": 1000.0 + (i % 17) * 10.0,
        })
    return out


def _patch_feed(monkeypatch) -> None:
    async def _fake_yahoo(**kwargs: Any) -> _History:
        rows = _full_bars(kwargs["interval"])[-int(kwargs["bars"]):]
        return _History(rows, "yahoo_chart")

    async def _fake_binance(**kwargs: Any) -> _History:
        rows = _full_bars(kwargs["interval"])[-int(kwargs["bars"]):]
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


def _bar_containing(bars: list[dict[str, Any]], instant_s: int, step: int) -> dict[str, Any]:
    for bar in bars:
        if bar["time"] <= instant_s < bar["time"] + step:
            return bar
    raise AssertionError(f"no bar contains {instant_s}")


def test_arrival_is_schedule_start_price_not_window_end(monkeypatch) -> None:
    """EXEC#2: the default arrival is the decision price at the schedule start."""
    _patch_feed(monkeypatch)
    res = _plan()
    data = res.data
    assert data["status"] == "ok"
    order = data["orders"][0]
    last_close = _full_bars(_INTERVAL)[-1]["close"]
    # Red today: the arrival equals the last bar close of the replay window.
    assert order["arrival_price"] != pytest.approx(last_close, abs=1e-6), (
        f"arrival {order['arrival_price']} is the end-of-window close {last_close}"
    )
    start_s = data["schedule_start_ms"] // 1000
    bar = _bar_containing(_full_bars(_INTERVAL), start_s, _step_for(_INTERVAL))
    assert order["arrival_price"] == pytest.approx(round(bar["open"], 6), abs=1e-6)


def test_slices_span_the_requested_horizon(monkeypatch) -> None:
    """EXEC#3: 12 slices over 600 s must not be mapped onto a 55-minute span."""
    _patch_feed(monkeypatch)
    res = _plan(horizon_seconds=600, slices=12)
    data = res.data
    assert data["status"] == "ok"
    rows = data["rows"]
    bar_s = _step_for(_INTERVAL)
    ts = [r["ts_ms"] for r in rows]
    span_s = (max(ts) - min(ts)) / 1000.0
    # Red today: span is 3300 s for a 600 s horizon.
    assert span_s <= 600 + bar_s, f"bars span {span_s}s for a 600s horizon"
    assert data["horizon_seconds"] == 600
    release = [r["release_ts_ms"] for r in rows]
    assert release[0] == data["schedule_start_ms"]
    assert release[-1] - release[0] == 550_000  # last slice offset 11 * 50 s
    for r in rows:
        assert r["ts_ms"] <= r["release_ts_ms"] < r["ts_ms"] + bar_s * 1000


def test_coarse_bars_for_fine_slices_are_flagged(monkeypatch) -> None:
    """EXEC#3: slices spaced finer than the bar interval must say so."""
    _patch_feed(monkeypatch)
    res = _plan(horizon_seconds=600, slices=12)
    data = res.data
    assert data["status"] == "ok"
    slot_s = 600 / 12
    assert _step_for(_INTERVAL) > slot_s
    assert any("coarser" in w for w in res.warnings), res.warnings


def _forming_feed(monkeypatch, n: int = 120) -> float:
    """1m feed whose LAST bar is still forming (opened 10 s ago, closes ~50 s out).

    chart_history does not drop an in-progress candle, so the plan must."""
    now = time.time()
    forming_open = int(now) - 10
    rows = [
        {
            "time": forming_open - (n - 1 - i) * 60,
            "open": 300.0 + i * 0.2,
            "high": 300.5 + i * 0.2,
            "low": 299.5 + i * 0.2,
            "close": 300.3 + i * 0.2,
            "volume": 1000.0,
        }
        for i in range(n)
    ]

    async def _fake_yahoo(**kwargs: Any) -> _History:
        return _History(rows[-int(kwargs["bars"]):], "yahoo_chart")

    async def _fake_binance(**kwargs: Any) -> _History:
        return _History(rows[-int(kwargs["bars"]):], "binance_spot")

    monkeypatch.setattr(ch, "fetch_yahoo_history", _fake_yahoo, raising=True)
    monkeypatch.setattr(ch, "fetch_binance_history", _fake_binance, raising=True)
    return float(forming_open)


def test_forming_bar_is_excluded_from_replay(monkeypatch) -> None:
    """EXEC#3 follow-up: an in-progress bar must neither be replayed nor move the
    window end (as_of / window_end_ms) into the future."""
    forming_open = _forming_feed(monkeypatch)
    call_s = time.time()
    res = _plan(horizon_seconds=600, slices=12)
    data = res.data
    assert data["status"] == "ok"
    assert data["window_end_ms"] <= call_s * 1000
    assert data["cards"]["as_of"] <= call_s * 1000
    assert all(r["ts_ms"] < forming_open * 1000 for r in data["rows"]), (
        "a slice was measured against the still-forming bar"
    )


def test_field_dictionary_does_not_claim_live_data(monkeypatch) -> None:
    """EXEC#1: the field dictionary returned with a plan must describe replayed
    historical bars, never a live feed."""
    _patch_feed(monkeypatch)
    res = _plan()
    fd = res.data["field_dictionary"]
    for key in ("bar_close", "execution_mode"):
        assert "live" not in fd[key].lower(), f"{key}: {fd[key]}"
