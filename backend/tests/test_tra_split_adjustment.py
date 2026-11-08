"""TRA#2 / TRA#3: a stock split must never read as a loss.

Yahoo reports a split as a jump in the raw close (100 -> 25 after a 4:1 split).
TRA now split-adjusts closes and dividends before compounding, so the TWR,
price return, CAGR, IRR and max drawdown describe the share, not the ticket
count. A window whose split events are unavailable is labelled, not silently
read as a crash.

Offline: the yfinance adapter is a fake that returns a prepared frame, and the
chart-adapter test replaces the Yahoo HTTP client with a canned payload.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter
from showme.engine.functions.portfolio._more import TRAFunction

EQ = Instrument(symbol="ABC", asset_class=AssetClass.EQUITY)
N = 300
SPLIT_BAR = 150


class _Yf:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, request: Any) -> pd.DataFrame:  # noqa: ARG002
        return self._frame


def _frame(closes: list[float], dividends: list[float] | None = None,
           splits: list[float] | None = None) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=len(closes), freq="B", tz="UTC")
    data: dict[str, Any] = {"close": [float(c) for c in closes]}
    if dividends is not None:
        data["dividends"] = [float(x) for x in dividends]
    if splits is not None:
        data["splits"] = [float(x) for x in splits]
    return pd.DataFrame(data, index=idx)


def _run(frame: pd.DataFrame, **params: Any) -> Any:
    return asyncio.run(TRAFunction(FunctionDeps(yfinance=_Yf(frame))).execute(instrument=EQ, **params))


def _split_path(ratio: float = 4.0, pre: float = 100.0,
                post_move: float = 1.0) -> tuple[list[float], list[float]]:
    """Flat share price; the raw close drops by ``ratio`` at SPLIT_BAR."""
    closes = [pre] * SPLIT_BAR + [pre / ratio * post_move] * (N - SPLIT_BAR)
    splits = [0.0] * N
    splits[SPLIT_BAR] = ratio
    return closes, splits


def test_4_to_1_split_on_flat_price_is_not_a_loss() -> None:
    closes, splits = _split_path(ratio=4.0)
    res = _run(_frame(closes, [0.0] * N, splits))
    assert res.data["price_return_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["twr_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["max_drawdown"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["cagr"] == pytest.approx(0.0, abs=1e-9)
    assert res.data["split_adjusted"] is True
    assert res.data["splits_count"] == 1


def test_real_drop_after_a_split_still_shows_up() -> None:
    # The share falls 10% after a 4:1 split: that loss is real and must remain.
    closes, splits = _split_path(ratio=4.0, post_move=0.9)
    res = _run(_frame(closes, [0.0] * N, splits))
    assert res.data["price_return_total"] == pytest.approx(-0.10, rel=1e-9)
    assert res.data["twr_total"] == pytest.approx(-0.10, rel=1e-9)
    assert res.data["max_drawdown"] == pytest.approx(-0.10, rel=1e-9)


def test_reverse_split_is_not_a_gain() -> None:
    # 1:10 reverse split: the raw close rises tenfold on the split bar.
    closes, splits = _split_path(ratio=0.1, pre=10.0)
    res = _run(_frame(closes, [0.0] * N, splits))
    assert res.data["price_return_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["twr_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["max_drawdown"] == pytest.approx(0.0, abs=1e-12)


def test_dividend_after_a_split_is_expressed_in_the_same_share() -> None:
    # After the 4:1 split a share is worth 25; a $0.50 post-split dividend is
    # 2% of the pre-split holding value of 100, so the total return is 2%.
    closes, splits = _split_path(ratio=4.0)
    dividends = [0.0] * N
    dividends[200] = 0.5
    res = _run(_frame(closes, dividends, splits))
    assert res.data["twr_total"] == pytest.approx(0.02, rel=1e-9)
    assert res.data["price_return_total"] == pytest.approx(0.0, abs=1e-12)
    # Dividends stay as paid, per post-split share.
    assert res.data["dividends_total"] == pytest.approx(0.5)


def test_irr_on_a_split_window_is_finite_or_null_and_never_raises() -> None:
    # Same shape that used to overflow Newton's method on raw closes.
    closes, splits = _split_path(ratio=4.0)
    res_split = _run(_frame(closes, [0.0] * N, splits))
    irr_split = res_split.data["irr_annualized"]
    assert irr_split is None or (isinstance(irr_split, float) and math.isfinite(irr_split))
    # Without split events the same input is still labelled, and still returns.
    res_flagged = _run(_frame(closes, [0.0] * N))
    irr_flagged = res_flagged.data["irr_annualized"]
    assert irr_flagged is None or (isinstance(irr_flagged, float) and math.isfinite(irr_flagged))


def test_missing_split_events_are_flagged_not_silent() -> None:
    closes, _ = _split_path(ratio=4.0)
    res = _run(_frame(closes, [0.0] * N))
    assert res.data["split_adjusted"] is False
    assert res.data["splits_count"] is None
    assert any("Split events are unavailable" in w for w in res.warnings)
    # The 4:1-sized one-day drop is named as a possible unconfirmed split.
    assert any("matches a stock split" in w for w in res.warnings)


def test_ordinary_daily_moves_are_not_flagged_as_splits() -> None:
    closes = [100.0, 101.0, 99.5, 98.0, 103.0, 104.0]
    res = _run(_frame(closes, [0.0] * len(closes)))
    assert not any("matches a stock split" in w for w in res.warnings)


def test_chart_split_events_reach_tra_as_adjusted_returns() -> None:
    base = int(datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc).timestamp())
    day = 86400
    ts = [base + i * day for i in range(8)]
    closes = [100.0, 100.0, 100.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    payload = {"chart": {"result": [{
        "timestamp": ts,
        "indicators": {"quote": [{
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [1_000] * len(ts),
        }]},
        "events": {"splits": {str(ts[3]): {
            "date": ts[3], "numerator": 4, "denominator": 1, "splitRatio": "4:1",
        }}},
    }], "error": None}}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    class _Client:
        async def get(self, path: str, params: dict | None = None) -> _Resp:  # noqa: ARG002
            return _Resp()

    adapter = YFinanceAdapter()
    adapter._chart_client = _Client()
    start = datetime.now(tz=timezone.utc) - timedelta(days=400)
    frame = asyncio.run(adapter._fetch_chart_ohlcv("abc", "1d", start, None, None))
    assert "splits" in frame.columns
    assert frame["splits"].iloc[3] == pytest.approx(4.0)
    assert float(frame["splits"].sum()) == pytest.approx(4.0)

    res = asyncio.run(TRAFunction(FunctionDeps(yfinance=adapter)).execute(instrument=EQ, years=2))
    assert res.data["price_return_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["twr_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["max_drawdown"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["split_adjusted"] is True
    assert not any("Split events are unavailable" in w for w in res.warnings)
