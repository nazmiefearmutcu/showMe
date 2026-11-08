"""4h history must be resampled from Yahoo's 60m bars, not returned as hourly.

Yahoo has no native 4h interval, so ``YAHOO_INTERVALS['4h']`` requests 60m
bars. The pre-fix path returned those hourly bars unchanged while the output
still said ``resolution: 4h``. The fix aggregates them into epoch-aligned
4-hour OHLCV buckets (first open, max high, min low, last close, summed
volume), the same as the yfinance adapter's pandas ``resample('4H')``.

The HTTP client is faked: no network.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

import showme.chart_history as chart_history
from showme.chart_history import fetch_longest_history

BUCKET = 4 * 3600


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    payload: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get(self, url: str, params: Any = None) -> _FakeResponse:
        assert params is not None and params["interval"] == "60m"
        return _FakeResponse(_FakeAsyncClient.payload)


def _hourly_payload(hours: int = 120) -> tuple[dict[str, Any], list[dict[str, float]]]:
    now = int(datetime.now(timezone.utc).timestamp())
    start = (now // 3600) * 3600 - hours * 3600
    timestamps = [start + 3600 * i for i in range(hours)]
    bars = []
    for i in range(hours):
        close = 100.0 + i * 0.1 + (0.7 if i % 3 == 0 else -0.4)
        bars.append({
            "time": timestamps[i],
            "open": close - 0.05,
            "high": close + 0.3 + (i % 5) * 0.1,
            "low": close - 0.4 - (i % 4) * 0.1,
            "close": close,
            "volume": 1000.0 + i,
        })
    payload = {
        "chart": {
            "result": [{
                "meta": {"symbol": "AAPL", "currency": "USD"},
                "timestamp": timestamps,
                "indicators": {"quote": [{
                    "open": [b["open"] for b in bars],
                    "high": [b["high"] for b in bars],
                    "low": [b["low"] for b in bars],
                    "close": [b["close"] for b in bars],
                    "volume": [b["volume"] for b in bars],
                }]},
            }],
            "error": None,
        }
    }
    return payload, bars


def _expected_4h(bars: list[dict[str, float]]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for bar in bars:
        key = bar["time"] - bar["time"] % BUCKET
        bucket = out.get(key)
        if bucket is None:
            out[key] = {
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
            }
        else:
            bucket["high"] = max(bucket["high"], bar["high"])
            bucket["low"] = min(bucket["low"], bar["low"])
            bucket["close"] = bar["close"]
            bucket["volume"] += bar["volume"]
    return out


def test_4h_history_is_resampled_to_four_hour_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STOOQ_API_KEY", raising=False)
    payload, bars = _hourly_payload(120)
    _FakeAsyncClient.payload = payload
    monkeypatch.setattr(chart_history.httpx, "AsyncClient", _FakeAsyncClient)

    out = asyncio.run(
        fetch_longest_history(
            symbol="AAPL", asset_class="EQUITY", interval="4h",
            days=30, bars=1500, deep_history=True,
        )
    )

    times = [int(row["time"]) for row in out.rows]
    assert len(times) >= 2
    gaps = {b - a for a, b in zip(times, times[1:])}
    assert gaps == {BUCKET}, f"4h output must not carry 1h spacing, got gaps {sorted(gaps)}"

    expected = _expected_4h(bars)
    by_time = {int(row["time"]): row for row in out.rows}
    for key, want in expected.items():
        if key not in by_time:
            continue
        got = by_time[key]
        assert got["open"] == pytest.approx(want["open"])
        assert got["high"] == pytest.approx(want["high"])
        assert got["low"] == pytest.approx(want["low"])
        assert got["close"] == pytest.approx(want["close"])
        assert got["volume"] == pytest.approx(want["volume"])
    # Every complete 4h bucket in the fixture is present (the last one may be partial).
    assert set(list(expected)[:-1]) <= set(by_time)


def test_4h_metadata_reports_the_60m_source_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STOOQ_API_KEY", raising=False)
    payload, _bars = _hourly_payload(60)
    _FakeAsyncClient.payload = payload
    monkeypatch.setattr(chart_history.httpx, "AsyncClient", _FakeAsyncClient)

    out = asyncio.run(
        fetch_longest_history(
            symbol="AAPL", asset_class="EQUITY", interval="4h",
            days=30, bars=1500, deep_history=True,
        )
    )
    assert out.source == "yahoo_chart"
    assert out.metadata.get("provider_interval") == "60m"
    assert out.metadata.get("resampled_from") == "60m"
    assert out.metadata.get("resampled_to") == "4h"
