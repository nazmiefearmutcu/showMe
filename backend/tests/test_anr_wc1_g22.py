"""ANR review fixes (wave wc1-g22): ANR#2, ANR#3, ANR#4, ANR#5, ANR#6.

Offline: yfinance and finnhub are replaced by in-test fakes, so no network runs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.anr import (
    ANRFunction,
    _consensus_label,
    _rsi,
    _signal_bucket_rows,
)


_PERIODS = [
    {"period": "0m", "strongBuy": 10, "buy": 12, "hold": 8, "sell": 1, "strongSell": 0},
    {"period": "-1m", "strongBuy": 9, "buy": 11, "hold": 9, "sell": 1, "strongSell": 0},
    {"period": "-2m", "strongBuy": 9, "buy": 10, "hold": 9, "sell": 2, "strongSell": 0},
    {"period": "-3m", "strongBuy": 8, "buy": 10, "hold": 10, "sell": 2, "strongSell": 0},
]

_TARGETS = {
    "targetHighPrice": 280.0,
    "targetLowPrice": 180.0,
    "targetMeanPrice": 240.0,
    "targetMedianPrice": 238.0,
}


class _FakeYFinance:
    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    async def fetch(self, request: Any) -> Any:  # noqa: ARG002 - adapter protocol
        return SimpleNamespace(extras={"raw": self._raw})


class _FakeFinnhub:
    def __init__(self, recs: list[dict[str, Any]], target: dict[str, Any]) -> None:
        self._recs = recs
        self._target = target

    async def recommendations(self, symbol: str) -> list[dict[str, Any]]:  # noqa: ARG002
        return self._recs

    async def price_target(self, symbol: str) -> dict[str, Any]:  # noqa: ARG002
        return self._target


def _run(raw: dict[str, Any], finnhub: Any = None, **params: Any) -> Any:
    deps = FunctionDeps(yfinance=_FakeYFinance(raw), finnhub=finnhub)
    fn = ANRFunction(deps=deps)
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=instrument, **params))


# ── ANR#2 months drives a real per-period trend ─────────────────────────────

def _raw_with_targets() -> dict[str, Any]:
    return {"currentPrice": 200.0, "recommendations_summary": [dict(p) for p in _PERIODS], **_TARGETS}


def test_months_window_limits_trend_to_provider_periods() -> None:
    # Six periods of provider history so a 3-month window visibly cuts the rest.
    raw = _raw_with_targets()
    raw["recommendations_summary"] = [
        {**p, "period": f"-{n}m"} if n else dict(p)
        for n, p in enumerate(raw["recommendations_summary"])
    ] + [
        {"period": f"-{n}m", "strongBuy": 5, "buy": 5, "hold": 5, "sell": 5, "strongSell": 5}
        for n in (4, 5, 6)
    ]
    result = _run(raw, months=3)
    assert [row["months_back"] for row in result.data["trend"]] == [0, 1, 2, 3]
    assert result.data["trend_months"] == 3


def test_months_below_manifest_minimum_is_clamped_and_reported() -> None:
    result = _run(_raw_with_targets(), months=2)
    assert result.data["trend_months"] == 3


def test_months_beyond_provider_history_warns_and_keeps_available_periods() -> None:
    result = _run(_raw_with_targets(), months=36)
    assert [row["months_back"] for row in result.data["trend"]] == [0, 1, 2, 3]
    assert result.data["trend_oldest_provider_months_back"] == 3
    assert any("Provider history reaches 3 month(s) back" in w for w in result.warnings)


def test_trend_rows_carry_bucket_counts_score_and_consensus_flag() -> None:
    result = _run(_raw_with_targets(), months=12)
    newest = result.data["trend"][0]
    assert newest["period"] == "0m"
    assert newest["strongBuy"] == 10 and newest["sell"] == 1
    assert newest["total"] == 31
    assert newest["in_consensus"] is True
    assert result.data["current_score"] == newest["score"]


# ── ANR#3 no price target is ever derived from spot ─────────────────────────

def test_missing_provider_target_is_not_derived_from_spot() -> None:
    raw = {"currentPrice": 200.0, "recommendations_summary": [dict(p) for p in _PERIODS]}
    result = _run(raw)
    target = result.data["price_target"]
    assert target["targetMean"] is None
    assert target["targetHigh"] is None
    assert target["targetLow"] is None
    assert target["targetMedian"] is None
    assert target["source_mode"] == "price_target_unavailable"
    assert result.data["target_rows"] == []
    assert result.data["target_price_source"]["mode"] == "target_price_unavailable"
    assert "analyst_target_reference" not in result.sources
    assert result.data["spot"] == 200.0


# ── ANR#4 a Finnhub payload without targets does not hide yfinance targets ──

def test_empty_finnhub_target_falls_back_to_yfinance_targets() -> None:
    finnhub = _FakeFinnhub(recs=[{"period": "2026-10-01", "strongBuy": 3, "buy": 2, "hold": 1,
                                   "sell": 0, "strongSell": 0}], target={})
    raw = _raw_with_targets()
    result = _run(raw, finnhub=finnhub)
    assert result.data["price_target"]["targetMean"] == 240.0
    assert result.data["target_price_source"]["mode"] == "live_analyst_targets"
    assert "yfinance_targets" in result.sources


# ── ANR#5 RSI is Wilder's smoothed RSI ──────────────────────────────────────

def test_rsi_uses_wilder_smoothing_not_a_plain_window_mean() -> None:
    # Hand-computed Wilder RSI(3): avg gain 94/81, avg loss 26/81 -> RSI = 235/3.
    # A plain mean over the last three changes would give 80.0 instead.
    closes = pd.Series([10.0, 11.0, 12.0, 11.0, 13.0, 12.0, 14.0])
    assert abs(_rsi(closes, period=3) - 235.0 / 3.0) < 1e-6


# ── ANR#6 one threshold table for label and signal buckets ──────────────────

_LABEL_TO_BUCKET = {
    "Strong Buy": "Strong Buy",
    "Buy-leaning": "Buy",
    "Neutral": "Hold",
    "Sell-leaning": "Sell",
    "Strong Sell": "Strong Sell",
}


def test_signal_bucket_agrees_with_consensus_label_for_every_score() -> None:
    for score in (4.2, 4.3, 4.45, 3.6, 2.8, 2.2, 2.1, 2.0):
        rows = _signal_bucket_rows([{"score": score}])
        filled = [row["bucket"] for row in rows if row["count"] == 1]
        assert filled == [_LABEL_TO_BUCKET[_consensus_label(score)]], score
