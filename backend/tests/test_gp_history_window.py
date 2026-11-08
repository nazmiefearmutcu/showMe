"""GP price graph: window honesty (GP#2), warm-up overlays (GP#4), seed/pane parity (GP#8).

The price-history fetch is replaced by a fake that honours ``days`` and ``bars``
the way ``fetch_longest_history`` does (suffix of the window, capped by bars).
No network is used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from showme import server
from showme.chart_history import DeepHistoryResult
from showme.engine.core.base_function import FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


def _now() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def _series(step_seconds: int, count: int) -> list[dict[str, Any]]:
    end = int(_now())
    end -= end % step_seconds
    rows: list[dict[str, Any]] = []
    for i in range(count):
        ts = end - (count - 1 - i) * step_seconds
        close = 100.0 + i * 0.05
        rows.append(
            {
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "time": ts,
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000.0 + i,
            }
        )
    return rows


def _fake_history(
    monkeypatch: pytest.MonkeyPatch, full_rows: list[dict[str, Any]], seen: dict[str, Any]
) -> None:
    """Replace fetch_longest_history: keep rows inside ``days``, then cap by ``bars``."""

    async def _fake(**kwargs: Any) -> DeepHistoryResult:
        seen.update(kwargs)
        cutoff = _now() - kwargs["days"] * 86_400
        window = [r for r in full_rows if r["time"] >= cutoff]
        rows = window[-kwargs["bars"]:]
        return DeepHistoryResult(rows=rows, source="yahoo_chart", warnings=[], metadata={})

    monkeypatch.setattr(server, "fetch_longest_history", _fake)


def _run(code: str, params: dict[str, Any]) -> Any:
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(
        server._execute_price_history_alias(
            code,
            params,
            instrument,
            SimpleNamespace(deps=None),
            SimpleNamespace(FunctionResult=FunctionResult),
            object(),
        )
    )


def test_gp_warns_when_intraday_span_is_shorter_than_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1000 one-minute bars cover well under a day, but the header asks for 1Y.
    _fake_history(monkeypatch, _series(60, 1_000), {})
    result = _run("GP", {"days": 365, "range": "1Y", "interval": "1m", "bars": 1000})

    span = result.data["span_days"]
    assert span is not None and span < 1.0
    assert result.data["requested_days"] == 365
    assert any("spans" in w and "shorter" in w for w in result.warnings), result.warnings


def test_gp_has_no_short_span_warning_when_window_is_covered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_history(monkeypatch, _series(86_400, 400), {})
    result = _run("GP", {"days": 365, "range": "1Y", "interval": "1d", "bars": 1500})

    assert not any("shorter" in w for w in result.warnings), result.warnings
    assert result.data["span_days"] >= 360


def test_gp_fetch_is_widened_by_warmup_and_display_is_clipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    _fake_history(monkeypatch, _series(86_400, 400), seen)
    result = _run("GP", {"days": 30, "range": "1M", "interval": "1d", "bars": 1000})

    # The provider is asked for more history than the 1M window (warm-up).
    assert seen["days"] > 30
    assert seen["bars"] > 1000
    # The pane still receives only the 1M window.
    assert len(result.data["ohlcv"]) <= 31
    assert result.data["bar_count"] == len(result.data["ohlcv"])
    # Overlays are computed on the warm-up history, so the window is fully covered.
    indicators = result.data["indicators"]
    assert len(indicators["sma_50"]) == len(result.data["ohlcv"])
    assert len(indicators["sma_20"]) == len(result.data["ohlcv"])
    assert result.data["indicator_warmup_bars"] > 0
    first_display = result.data["ohlcv"][0]["time"]
    assert all(p["time"] >= first_display for p in indicators["sma_20"])


def test_gp_warmup_count_excludes_in_window_rows_trimmed_by_bar_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 2200 daily rows; the provider cap (1200 fetched bars) leaves no row before
    # the 5Y window, and the 1000-bar display cap trims in-window rows only.
    # No warm-up bar exists, so the warm-up count must be 0, not the trimmed 200.
    seen: dict[str, Any] = {}
    _fake_history(monkeypatch, _series(86_400, 2_200), seen)
    result = _run("GP", {"days": 1825, "range": "5Y", "interval": "1d", "bars": 1000})

    assert len(result.data["ohlcv"]) == 1000
    assert result.data["indicator_warmup_bars"] == 0
    # The shortfall is still reported as a window-span warning.
    assert any("shorter" in w for w in result.warnings), result.warnings


def test_non_gp_alias_fetch_is_not_widened(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    _fake_history(monkeypatch, _series(86_400, 400), seen)
    _run("HP", {"days": 30, "range": "1M", "interval": "1d", "bars": 1000})
    assert seen["days"] == 30
    assert seen["bars"] == 1000


