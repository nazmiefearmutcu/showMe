"""F7 — HP/GP price-history alias: identity / 52w emission + GP overlays.

Covers the chart fix lane (audit A1·HP + A6·GP):
    * Yahoo chart meta (long/short name, exchange, 52-week levels) is parsed
      and forwarded by ``fetch_longest_history`` metadata + the alias payload,
      so HP's name/exchange pills and both panes' 52w rail rows can populate.
    * The alias emits ``indicators`` (SMA 20/50, EMA 20, Bollinger 20±2) for
      GP, whose pane renders ``data.indicators`` as overlay lines + legend.
    * The adapter-fallback payload stays honest: null identity, no overlays,
      no fabricated numbers.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from showme import server
from showme.chart_history import (
    DeepHistoryResult,
    _meta_from_yahoo_chart,
    compute_chart_indicators,
)
from showme.engine.core.base_function import FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


def _rows(count: int = 60) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(count):
        close = 100.0 + index
        rows.append(
            {
                "date": f"2026-01-{(index % 28) + 1:02d}T00:00:00+00:00",
                "time": 1_767_225_600 + index * 86_400,
                "open": close - 1.0,
                "high": close + 2.0,
                "low": close - 2.0,
                "close": close,
                "volume": 1_000.0 + index,
            }
        )
    return rows


def _run_alias(
    code: str,
    *,
    history: DeepHistoryResult | None = None,
    error: Exception | None = None,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    if error is not None:

        async def _boom(**_: Any) -> Any:
            raise error

        monkeypatch.setattr(server, "fetch_longest_history", _boom)
    else:
        assert history is not None

        async def _fake(**_: Any) -> DeepHistoryResult:
            return history

        monkeypatch.setattr(server, "fetch_longest_history", _fake)
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(
        server._execute_price_history_alias(
            code,
            {"days": 365, "interval": "1d", "bars": 1000},
            instrument,
            SimpleNamespace(deps=None),
            SimpleNamespace(FunctionResult=FunctionResult),
            object(),
        )
    )


# ── Yahoo meta parsing ───────────────────────────────────────────────────


def test_meta_from_yahoo_chart_extracts_identity_and_levels() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "longName": "Apple Inc.",
                        "shortName": "Apple",
                        "exchangeName": "NMS",
                        "fullExchangeName": "NasdaqGS",
                        "currency": "USD",
                        "fiftyTwoWeekHigh": 260.1,
                        "fiftyTwoWeekLow": 164.08,
                        "regularMarketPrice": 210.0,
                    }
                }
            ]
        }
    }
    assert _meta_from_yahoo_chart(payload) == {
        "long_name": "Apple Inc.",
        "short_name": "Apple",
        "exchange": "NMS",
        "full_exchange_name": "NasdaqGS",
        "currency": "USD",
        "fifty_two_week_high": 260.1,
        "fifty_two_week_low": 164.08,
    }


def test_meta_from_yahoo_chart_tolerates_missing_or_blank_meta() -> None:
    assert _meta_from_yahoo_chart({}) == {}
    assert _meta_from_yahoo_chart({"chart": {"result": [{}]}}) == {}
    assert (
        _meta_from_yahoo_chart({"chart": {"result": [{"meta": {"longName": "   "}}]}})
        == {}
    )
    # Non-finite 52w values must be dropped, not zero-filled.
    assert (
        _meta_from_yahoo_chart(
            {"chart": {"result": [{"meta": {"fiftyTwoWeekHigh": None}}]}}
        )
        == {}
    )


# ── GP overlay indicators ────────────────────────────────────────────────


def test_compute_chart_indicators_matches_rolling_mean_and_bands() -> None:
    rows = _rows(60)
    out = compute_chart_indicators(rows)
    assert set(out) == {
        "sma_20",
        "sma_50",
        "ema_20",
        "bb_upper",
        "bb_mid",
        "bb_lower",
    }
    closes = [row["close"] for row in rows]
    assert len(out["sma_20"]) == 41  # 60 - 20 + 1
    assert len(out["sma_50"]) == 11
    assert len(out["ema_20"]) == 60
    last = out["sma_20"][-1]
    assert last["time"] == rows[-1]["time"]
    assert last["value"] == pytest.approx(sum(closes[-20:]) / 20, abs=1e-9)
    upper = out["bb_upper"][-1]["value"]
    mid = out["bb_mid"][-1]["value"]
    lower = out["bb_lower"][-1]["value"]
    assert upper > mid > lower
    assert upper - mid == pytest.approx(mid - lower, abs=1e-9)


def test_compute_chart_indicators_needs_a_full_window() -> None:
    assert compute_chart_indicators(_rows(19)) == {}
    partial = compute_chart_indicators(_rows(20))
    assert set(partial) == {"sma_20", "ema_20", "bb_upper", "bb_mid", "bb_lower"}
    assert "sma_50" not in partial


# ── alias payload shape ──────────────────────────────────────────────────


def test_price_history_alias_emits_identity_and_52w(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = DeepHistoryResult(
        rows=_rows(30),
        source="yahoo_chart",
        warnings=[],
        metadata={
            "long_name": "Apple Inc.",
            "short_name": "Apple",
            "exchange": "NMS",
            "fifty_two_week_high": 260.1,
            "fifty_two_week_low": 164.08,
            "sources_considered": [
                {"name": "yahoo", "ok": True, "bars_available": 30}
            ],
        },
    )
    result = _run_alias("HP", history=history, monkeypatch=monkeypatch)
    data = result.data
    assert data["long_name"] == "Apple Inc."
    assert data["short_name"] == "Apple"
    assert data["exchange"] == "NMS"
    assert data["fifty_two_week_high"] == 260.1
    assert data["fifty_two_week_low"] == 164.08
    assert data["bar_count"] == 30
    # HP draws its studies client-side from the toggle menu; the alias must
    # not ship a second copy of them.
    assert "indicators" not in data


def test_price_history_alias_exchange_falls_back_to_full_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = DeepHistoryResult(
        rows=_rows(25),
        source="yahoo_chart",
        metadata={"full_exchange_name": "NasdaqGS"},
    )
    result = _run_alias("HP", history=history, monkeypatch=monkeypatch)
    assert result.data["exchange"] == "NasdaqGS"


def test_price_history_alias_gp_emits_indicator_overlays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = DeepHistoryResult(rows=_rows(60), source="yahoo_chart", metadata={})
    result = _run_alias("GP", history=history, monkeypatch=monkeypatch)
    indicators = result.data["indicators"]
    assert set(indicators) == {
        "sma_20",
        "sma_50",
        "ema_20",
        "bb_upper",
        "bb_mid",
        "bb_lower",
    }
    assert len(indicators["sma_20"]) == 41
    assert len(indicators["sma_50"]) == 11
    assert indicators["ema_20"][-1]["time"] == history.rows[-1]["time"]


def test_price_history_alias_fallback_stays_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_alias(
        "GP", error=RuntimeError("all providers down"), monkeypatch=monkeypatch
    )
    data = result.data
    assert data["rows"] == []
    assert data["long_name"] is None
    assert data["short_name"] is None
    assert data["exchange"] is None
    assert data["fifty_two_week_high"] is None
    assert data["fifty_two_week_low"] is None
    assert "indicators" not in data
    assert result.metadata["deep_history"] is False
    assert any("no price history" in warning for warning in result.warnings)
