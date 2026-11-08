"""TRA — dividends must come from the source, never a silent zero.

Finding TRA#1: the Yahoo chart request asks for ``events=div,splits`` but the
parser kept only OHLCV, so TRA reported 0 dividends for dividend payers. When
the dividend series is unavailable TRA must return null with a warning.

Offline: the Yahoo chart HTTP client is replaced by a fake that returns a
chart payload with dividend events.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter  # noqa: E402
from showme.engine.functions.portfolio._more import TRAFunction  # noqa: E402

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)

_BASE = int(datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc).timestamp())
_DAY = 86400
_TS = [_BASE + i * _DAY for i in range(8)]
_CLOSE = [100.0 + i for i in range(8)]


def _chart_payload(with_events: bool = True) -> dict:
    result: dict = {
        "timestamp": _TS,
        "indicators": {"quote": [{
            "open": _CLOSE, "high": _CLOSE, "low": _CLOSE, "close": _CLOSE,
            "volume": [1_000] * len(_TS),
        }]},
    }
    if with_events:
        result["events"] = {"dividends": {
            str(_TS[2]): {"amount": 0.24, "date": _TS[2]},
            str(_TS[5]): {"amount": 0.25, "date": _TS[5]},
        }}
    return {"chart": {"result": [result], "error": None}}


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _ChartClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def get(self, path: str, params: dict | None = None) -> _Resp:
        return _Resp(self._payload)


def _adapter(payload: dict) -> YFinanceAdapter:
    adapter = YFinanceAdapter()
    adapter._chart_client = _ChartClient(payload)
    return adapter


def _run(coro):
    return asyncio.run(coro)


def test_chart_events_land_on_the_dividend_bars() -> None:
    adapter = _adapter(_chart_payload(with_events=True))
    start = datetime.now(tz=timezone.utc) - timedelta(days=400)
    frame = _run(adapter._fetch_chart_ohlcv("aapl", "1d", start, None, None))
    # Before the fix the frame had no dividends column at all.
    assert "dividends" in frame.columns
    assert frame["dividends"].iloc[2] == pytest.approx(0.24)
    assert frame["dividends"].iloc[5] == pytest.approx(0.25)
    assert (frame["dividends"] > 0).sum() == 2
    assert frame["dividends"].sum() == pytest.approx(0.49)


def test_chart_without_events_reports_zero_dividends_for_the_window() -> None:
    # The chart was requested with events=div, so an absent events block means
    # no dividend occurred in the window; that is a real zero, not a gap.
    adapter = _adapter(_chart_payload(with_events=False))
    start = datetime.now(tz=timezone.utc) - timedelta(days=400)
    frame = _run(adapter._fetch_chart_ohlcv("aapl", "1d", start, None, None))
    assert "dividends" in frame.columns
    assert float(frame["dividends"].sum()) == 0.0


def test_tra_reports_dividends_from_chart_events() -> None:
    deps = FunctionDeps(yfinance=_adapter(_chart_payload(with_events=True)))
    result = _run(TRAFunction(deps).execute(instrument=AAPL))
    # Before the fix: dividends_count 0 and dividends_total 0.0.
    assert result.data["dividends_count"] == 2
    assert result.data["dividends_total"] == pytest.approx(0.49)
    assert result.metadata.get("data_mode") == "live_yfinance"


def test_tra_dividends_are_null_when_the_dividend_series_is_unavailable() -> None:
    # Live feed fails, so TRA serves the labelled template: it has no
    # dividend series, and must say so instead of reporting zero.
    deps = FunctionDeps(yfinance=None)
    result = _run(TRAFunction(deps).execute(instrument=AAPL))
    assert result.metadata.get("fallback") is True
    # Before the fix: dividends_count 0 and dividends_total 0.0.
    assert result.data["dividends_count"] is None
    assert result.data["dividends_total"] is None
    assert result.data["summary"]["dividends_total"] is None
    assert any("dividend" in w.lower() for w in result.warnings)
