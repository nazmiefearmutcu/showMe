"""TRA#2 / TRA#3: a stock split must never read as a loss or a gain.

Yahoo's chart and the yfinance ticker history both return closes and dividends
already split-adjusted to the latest share basis. Verified against the Yahoo
chart endpoint (read-only, AAPL, 7:1 split on 2014-06-09): the close moves
23.056 -> 23.425 -> 23.563 across the split, and the 0.1175 dividend is the
pre-split 0.82 divided by 7. TRA must use those series as delivered. Multiplying
them again by the split ratio read every split as a large gain (TRA#2 follow-up).

Where the source closes still show a ratio-sized one-day move, TRA names the
bar in its warnings instead of adjusting it silently. A window whose split
events are unavailable is labelled, not silently read as a crash.

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
    """Split-adjusted closes for a flat share price (source basis = post-split shares).

    The pre-split bars are already divided by the split ratio, exactly as the
    source delivers them, so the series is continuous across the split bar.
    """
    pre_adj = pre / ratio
    closes = [pre_adj] * SPLIT_BAR + [pre_adj * post_move] * (N - SPLIT_BAR)
    splits = [0.0] * N
    splits[SPLIT_BAR] = ratio
    return closes, splits


def test_4_to_1_split_on_flat_price_is_not_a_loss_or_gain() -> None:
    closes, splits = _split_path(ratio=4.0)
    res = _run(_frame(closes, [0.0] * N, splits))
    assert res.data["price_return_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["twr_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["max_drawdown"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["cagr"] == pytest.approx(0.0, abs=1e-9)
    assert res.data["split_adjusted"] is True
    assert res.data["splits_count"] == 1
    assert not any("matches a stock split" in w for w in res.warnings)


def test_real_drop_after_a_split_still_shows_up() -> None:
    # The share falls 10% after a 4:1 split: that loss is real and must remain.
    closes, splits = _split_path(ratio=4.0, post_move=0.9)
    res = _run(_frame(closes, [0.0] * N, splits))
    assert res.data["price_return_total"] == pytest.approx(-0.10, rel=1e-9)
    assert res.data["twr_total"] == pytest.approx(-0.10, rel=1e-9)
    assert res.data["max_drawdown"] == pytest.approx(-0.10, rel=1e-9)


def test_reverse_split_is_not_a_gain() -> None:
    # 1:10 reverse split: the source-adjusted pre-split closes are divided by 0.1.
    closes, splits = _split_path(ratio=0.1, pre=10.0)
    res = _run(_frame(closes, [0.0] * N, splits))
    assert res.data["price_return_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["twr_total"] == pytest.approx(0.0, abs=1e-12)
    assert res.data["max_drawdown"] == pytest.approx(0.0, abs=1e-12)


def test_dividend_after_a_split_is_expressed_in_the_same_share() -> None:
    # After the 4:1 split a share is worth 25; a $0.50 post-split dividend on
    # that share is 2% of the price, so the total return is 2%.
    closes, splits = _split_path(ratio=4.0)
    dividends = [0.0] * N
    dividends[200] = 0.5
    res = _run(_frame(closes, dividends, splits))
    assert res.data["twr_total"] == pytest.approx(0.02, rel=1e-9)
    assert res.data["price_return_total"] == pytest.approx(0.0, abs=1e-12)
    # Dividends stay as delivered, per post-split share.
    assert res.data["dividends_total"] == pytest.approx(0.5)


def test_real_aapl_split_window_from_source_basis_is_not_inflated() -> None:
    # Real Yahoo chart values, read-only, AAPL 2014-06-06, 06-09 (7:1 split), 06-10.
    # The source delivers them split-adjusted, so the return is the ~2.2% price move.
    closes = [23.05607032775879, 23.424999237060547, 23.5625]
    frame = _frame(closes, [0.0, 0.0, 0.0], [0.0, 7.0, 0.0])
    res = _run(frame)
    assert res.data["price_return_total"] == pytest.approx(23.5625 / 23.05607032775879 - 1, rel=1e-9)
    assert res.data["price_return_total"] < 0.05
    assert res.data["splits_count"] == 1


def test_irr_on_a_split_window_is_finite_or_null_and_never_raises() -> None:
    closes, splits = _split_path(ratio=4.0)
    res_split = _run(_frame(closes, [0.0] * N, splits))
    irr_split = res_split.data["irr_annualized"]
    assert irr_split is None or (isinstance(irr_split, float) and math.isfinite(irr_split))
    # Without split events the same input is still labelled, and still returns.
    res_flagged = _run(_frame(closes, [0.0] * N))
    irr_flagged = res_flagged.data["irr_annualized"]
    assert irr_flagged is None or (isinstance(irr_flagged, float) and math.isfinite(irr_flagged))


def test_missing_split_events_are_labelled_and_suspected_splits_named() -> None:
    # Unadjusted closes with no split event: the 4:1-sized one-day drop is named.
    closes = [100.0] * SPLIT_BAR + [25.0] * (N - SPLIT_BAR)
    res = _run(_frame(closes, [0.0] * N))
    assert res.data["split_adjusted"] is False
    assert res.data["splits_count"] is None
    assert any("matches a stock split" in w for w in res.warnings)


def test_unadjusted_drop_at_a_reported_split_is_named_not_hidden() -> None:
    # A split event is reported but the closes still show the raw 4:1 drop
    # (a source that failed to adjust). TRA must name the bar, not hide it.
    closes = [100.0] * SPLIT_BAR + [25.0] * (N - SPLIT_BAR)
    splits = [0.0] * N
    splits[SPLIT_BAR] = 4.0
    res = _run(_frame(closes, [0.0] * N, splits))
    assert res.data["split_adjusted"] is True
    assert any("matches a stock split ratio even though" in w for w in res.warnings)


def test_frames_without_split_column_and_no_split_sized_move_stay_quiet() -> None:
    # Mocked or template frames without a split column are labelled through
    # split_adjusted, and carry no warning when no move looks like a split.
    closes = [100.0, 101.0, 99.5, 98.0, 103.0, 104.0]
    res = _run(_frame(closes, [0.0] * len(closes)))
    assert res.warnings == []
    assert res.data["split_adjusted"] is False


def test_ordinary_daily_moves_are_not_flagged_as_splits() -> None:
    closes = [100.0, 101.0, 99.5, 98.0, 103.0, 104.0]
    res = _run(_frame(closes, [0.0] * len(closes)))
    assert not any("matches a stock split" in w for w in res.warnings)


def test_chart_split_events_reach_tra_as_source_adjusted_returns() -> None:
    base = int(datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc).timestamp())
    day = 86400
    ts = [base + i * day for i in range(8)]
    # Yahoo's chart closes are already on the post-split basis: no step at the split.
    closes = [25.0] * 8
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
    assert res.data["splits_count"] == 1
    assert not any("Split events are unavailable" in w for w in res.warnings)
