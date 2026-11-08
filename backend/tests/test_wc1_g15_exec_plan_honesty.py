"""WC1-g15 regressions for EXEC action=plan (EXEC#2-RQ, EXEC#3-RQ, EXEC#5..#8).

EXEC#2-RQ / EXEC#3-RQ: a slice release or the schedule start that falls in a gap
of the stored bars was silently stamped with the previous stored bar (stale
price, false ts_ms provenance). It must return an explicit no-bar state instead.

EXEC#5: the benchmark is the bar's typical price (H+L+C)/3, not a volume-weighted
VWAP. The labels must not claim volume weighting.

EXEC#6: a missing or non-positive target_qty must return needs_input, not a
silent 100-unit plan.

EXEC#7: algos the engine cannot schedule (MARKET, ARRIVAL, POV) must be refused,
not silently replaced by TWAP or VWAP.

EXEC#8: plan rows report the SCHEDULE (cumulative scheduled / target), not a
fill. filled_qty stays zero because nothing was executed.

The market feed is patched (no network); the SQLite store is isolated per test.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import showme.chart_history as ch
from showme.engine.functions.trade.exec import EXECFunction
from showme.engine.services import exec_monitor

_T0 = 1_793_995_500  # 1m bar boundary, epoch seconds


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


def _contiguous(n: int = 400, step: int = 60) -> list[dict[str, Any]]:
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


def _gapped() -> list[dict[str, Any]]:
    """1m bars for minutes 0-4 and 15-19 only (10-14 missing)."""
    minutes = list(range(0, 5)) + list(range(15, 20))
    out = []
    for i, m in enumerate(minutes):
        base = 300.0 + i * 0.2
        out.append({
            "time": _T0 + m * 60,
            "open": base,
            "high": base + 0.5,
            "low": base - 0.5,
            "close": base + 0.3,
            "volume": 1000.0,
        })
    return out


def _patch_feed(monkeypatch, rows: list[dict[str, Any]] | None = None) -> None:
    feed = rows if rows is not None else _contiguous()

    async def _fake_yahoo(**kwargs: Any) -> _History:
        return _History(feed[-int(kwargs["bars"]):], "yahoo_chart")

    async def _fake_binance(**kwargs: Any) -> _History:
        return _History(feed[-int(kwargs["bars"]):], "binance_spot")

    monkeypatch.setattr(ch, "fetch_yahoo_history", _fake_yahoo, raising=True)
    monkeypatch.setattr(ch, "fetch_binance_history", _fake_binance, raising=True)


def _plan(**overrides: Any):
    args: dict[str, Any] = dict(
        action="plan", symbol="AAPL", algo="TWAP", target_qty=100,
        horizon_seconds=600, slices=12, side="BUY",
    )
    args.update(overrides)
    return asyncio.run(EXECFunction().execute(**args))


# --- EXEC#2-RQ / EXEC#3-RQ: gaps in stored bars --------------------------------

def test_release_in_bar_gap_is_not_stamped_with_a_stale_bar(monkeypatch) -> None:
    """EXEC#3-RQ: a slice released where no stored bar exists must not borrow the
    previous bar's ts_ms / close. Each row with a bar must contain its release."""
    _patch_feed(monkeypatch, _gapped())
    res = _plan(horizon_seconds=600, slices=12)
    data = res.data
    assert data["status"] == "ok", data
    rows = data["rows"]
    assert len(rows) == 12
    for r in rows:
        if r["ts_ms"] is not None:
            # Red today: the 600 s release is stamped with the 240 s bar.
            assert r["ts_ms"] <= r["release_ts_ms"] < r["ts_ms"] + 60_000, r
        else:
            assert r["bar_close"] is None and r["benchmark_px"] is None, r
    gap_rows = [r for r in rows if r["release_ts_ms"] < (_T0 + 900) * 1000]
    assert gap_rows and all(r["ts_ms"] is None for r in gap_rows), gap_rows
    assert any("no stored bar" in w for w in res.warnings), res.warnings


def test_schedule_start_in_bar_gap_does_not_borrow_an_old_open(monkeypatch) -> None:
    """EXEC#2-RQ: with no supplied arrival, an arrival taken from a gap is a stale
    price with false provenance. It must be null, not the open of an older bar."""
    _patch_feed(monkeypatch, _gapped())
    res = _plan(horizon_seconds=600, slices=12)
    data = res.data
    start_s = data["schedule_start_ms"] // 1000
    assert start_s == _T0 + 600  # the schedule starts inside the 10-14 min gap
    # Red today: arrival is the open of the 240 s bar (the last bar before the gap).
    assert data["orders"][0]["arrival_price"] is None, data["orders"][0]
    assert any("arrival" in w and "no stored bar" in w for w in res.warnings), res.warnings


# --- EXEC#5: benchmark is a typical price, not volume-weighted ----------------

def test_benchmark_is_described_as_typical_price_not_volume_weighted(monkeypatch) -> None:
    _patch_feed(monkeypatch)
    res = _plan()
    data = res.data
    assert data["status"] == "ok"
    fd = data["field_dictionary"]
    assert "weighted by" not in fd["benchmark_px"].lower(), fd["benchmark_px"]
    assert "typical" in fd["benchmark_px"].lower(), fd["benchmark_px"]
    # The methodology may say "NOT volume-weighted"; it must not claim weighting by volume.
    assert "weighted by bar volume" not in data["methodology"].lower()
    assert "not volume-weighted" in data["methodology"].lower()
    # The misleadingly named duplicate key is gone; benchmark_px is the one field.
    assert "interval_vwap" not in data["rows"][0]
    assert data["rows"][0]["benchmark_px"] is not None


# --- EXEC#6: missing target_qty ----------------------------------------------

@pytest.mark.parametrize("target", [None, 0, -5])
def test_missing_or_non_positive_target_qty_needs_input(monkeypatch, target) -> None:
    """EXEC#6: no silent 100-unit plan when the quantity is absent or non-positive."""
    _patch_feed(monkeypatch)
    args: dict[str, Any] = dict(
        action="plan", symbol="AAPL", algo="TWAP", horizon_seconds=600, slices=12, side="BUY",
    )
    if target is not None:
        args["target_qty"] = target
    res = asyncio.run(EXECFunction().execute(**args))
    data = res.data
    # Red today: status is "ok" with a 100-unit schedule.
    assert data["status"] == "needs_input", data
    assert "target_qty" in data["missing_fields"], data
    assert data["rows"] == [] and data["orders"] == []


# --- EXEC#7: unsupported algos are refused, not substituted -------------------

@pytest.mark.parametrize("algo", ["MARKET", "ARRIVAL", "POV"])
def test_unsupported_algo_is_refused_not_substituted(monkeypatch, algo) -> None:
    """EXEC#7: the engine cannot schedule these; reporting TWAP/VWAP would be a
    silent substitution of the algo the user chose."""
    _patch_feed(monkeypatch)
    res = _plan(algo=algo)
    data = res.data
    # Red today: status "ok" and resolved algo "TWAP" (MARKET/ARRIVAL) or "VWAP" (POV).
    assert data["status"] == "unsupported_algo", data
    assert data["rows"] == [] and data["orders"] == []
    assert set(data["supported_algos"]) == {"TWAP", "VWAP", "ICEBERG", "SNIPER"}


@pytest.mark.parametrize("algo", ["TWAP", "VWAP", "ICEBERG", "SNIPER"])
def test_supported_algo_is_scheduled_as_requested(monkeypatch, algo) -> None:
    _patch_feed(monkeypatch)
    res = _plan(algo=algo)
    assert res.data["status"] == "ok", res.data
    assert res.data["orders"][0]["algo"] == algo


# --- EXEC#8: schedule, not fill ------------------------------------------------

def test_plan_reports_schedule_not_fill(monkeypatch) -> None:
    """EXEC#8: nothing is executed in a plan, so filled_qty is zero and the progress
    figure is the schedule. pace_pct (filled / scheduled) must not appear."""
    _patch_feed(monkeypatch)
    res = _plan()
    data = res.data
    assert data["status"] == "ok"
    order = data["orders"][0]
    # Red today: filled_qty is 100.0 and pace_pct is 100.0 for an unexecuted plan.
    assert order["filled_qty"] == 0.0, order
    assert order["scheduled_qty"] == pytest.approx(100.0), order
    assert "pace_pct" not in order, order
    assert order["schedule_pct"] == pytest.approx(100.0), order
    for r in data["rows"]:
        assert "pace_pct" not in r, r
        assert r["schedule_pct"] is not None
    assert data["rows"][-1]["schedule_pct"] == pytest.approx(100.0)
    assert "pace" not in data["series"]
    assert "schedule" in data["series"]
    assert data["field_dictionary"]["schedule_pct"]
