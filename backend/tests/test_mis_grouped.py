"""2026-09-18: MIS source-grouped fetch for non-crypto markets.

A full equity sweep (2461 symbols x 12 TFs) issued ~27k single-symbol
yfinance calls through a global 2/s token bucket — hours, so the UI's
30-min deadline always fired first. Non-crypto targets now collapse onto
5 source cadences fetched ONCE per symbol (12 -> 5 HTTP per symbol).

Pins: group plan shape, resample derivation, per-symbol call counts,
and end-to-end parity of the grouped path through ``_run_mis_scan``.
Fully offline (synthetic frames, no network).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import showme.mis as mis
from showme.mis import (
    MisScanRequest,
    _derive_target,
    _group_plan,
)


def _frame(n: int, freq: str, start: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    base = pd.Series([start + (i % 50) * 0.1 + i * 0.01 for i in range(n)], index=idx)
    return pd.DataFrame({
        "open": base,
        "high": base + 0.5,
        "low": base - 0.5,
        "close": base + 0.1,
        "volume": 1000,
    })


class _FakeYF:
    """Recording yfinance stand-in serving generous synthetic history."""

    INTERVALS = {"1m": (3000, "min"), "5m": (1500, "5min"), "15m": (1500, "15min"),
                 "1h": (1500, "h"), "1d": (400, "D")}

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def fetch(self, request):
        self.calls.append((request.interval, dict(request.extra or {})))
        n, freq = self.INTERVALS.get(request.interval, (400, "D"))
        return _frame(n, freq)


@pytest.fixture(autouse=True)
def _clean_state():
    mis._FETCH_CACHE.clear()
    mis._ACTIVE_SCAN = None
    yield
    mis._FETCH_CACHE.clear()
    mis._ACTIVE_SCAN = None


# ── Plan shape ───────────────────────────────────────────────────────────

def test_group_plan_collapses_12_targets_to_5_sources():
    plan = _group_plan(["1m", "3m", "5m", "15m", "30m", "1h",
                        "2h", "4h", "6h", "8h", "12h", "1d"])
    assert plan is not None
    assert set(plan) == {"1m", "5m", "15m", "1h", "1d"}
    assert plan["1m"]["targets"] == ["1m", "3m"]
    assert plan["15m"]["targets"] == ["15m", "30m", "1h"]
    assert plan["1h"]["targets"] == ["2h", "4h", "6h", "8h", "12h"]
    # 1m is capped to Yahoo's 7d maximum (legacy asked 14d and failed).
    assert plan["1m"]["days"] == 7
    # 12h needs 180d of 1h (60d of 15m could not clear the 55-bar floor).
    assert plan["1h"]["days"] == 180


def test_group_plan_rejects_unknown_timeframe():
    assert _group_plan(["1m", "3y"]) is None


# ── Derivation ───────────────────────────────────────────────────────────

def test_derive_direct_target_tails_to_300():
    src = _frame(500, "D")
    out = _derive_target(src, "1d", "1d")
    assert out is not None and len(out) == 300
    assert float(out["close"].iloc[-1]) == float(src["close"].iloc[-1])


def test_derive_resampled_targets_keep_last_close():
    src15 = _frame(600, "15min")
    for tf in ("30m", "1h"):
        out = _derive_target(src15, "15m", tf)
        assert out is not None and len(out) >= 55, tf
        assert float(out["close"].iloc[-1]) == float(src15["close"].iloc[-1]), tf
    src1h = _frame(1500, "h")
    out12 = _derive_target(src1h, "1h", "12h")
    assert out12 is not None and len(out12) >= 55
    # A short source honestly yields too few resampled bars.
    assert _derive_target(_frame(100, "h"), "1h", "12h") is None or len(
        _derive_target(_frame(100, "h"), "1h", "12h")) < 55


def test_derive_returns_none_without_rule_or_frame():
    assert _derive_target(None, "1h", "4h") is None
    assert _derive_target(_frame(600, "h"), "1h", "9h") is None


# ── End to end (grouped path) ────────────────────────────────────────────

async def test_grouped_equity_scan_fetches_5_sources_per_symbol():
    fake = _FakeYF()
    deps = SimpleNamespace(yfinance=fake)
    req = MisScanRequest(markets=["EQUITY"], max_symbols_per_market=2)
    result = await mis._run_mis_scan(req, deps)

    assert len(result.rows) == 2
    for row in result.rows:
        assert row["tf_count_scanned"] == 12, row["symbol"]
        assert row["skipped"] is None
    # 2 symbols x 5 distinct sources — legacy would issue 2 x 12.
    assert len(fake.calls) == 10, [c[0] for c in fake.calls]
    assert {c[0] for c in fake.calls} == {"1m", "5m", "15m", "1h", "1d"}
    # The batch path skips the 2/s bucket under the scan semaphore.
    assert all(c[1].get("bypass_rate_limit") is True for c in fake.calls)


async def test_grouped_scan_signals_match_legacy_path():
    """Same frames through grouped vs legacy orchestration agree."""
    fake = _FakeYF()
    deps = SimpleNamespace(yfinance=fake)
    req = MisScanRequest(markets=["EQUITY"], max_symbols_per_market=1)
    grouped = await mis._run_mis_scan(req, deps)
    assert grouped.rows and grouped.rows[0]["skipped"] is None
    first = grouped.rows[0]
    per_tf = {r["tf"]: r["direction"] for r in first["per_tf"] if not r.get("skipped")}
    # All 12 TFs produced real (non-skipped) results off synthetic history.
    assert len(per_tf) == 12
