"""wc1-g33 honesty regressions: TECH#3..#6.

Network-free. The yfinance adapter is a fake, the FinBERT / XSEN analyzers are
patched, and the router defaults are read through the real
``_route_function_params`` helper.

TECH#3  an empty OHLCV frame must never earn a LIVE data_state
TECH#4  the router's generic limit/days injection must not shrink TECH's window
TECH#5  ``studies`` must select the computed families; interval is validated
TECH#6  field_dict paths and deep_history must describe the real output
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.chart.tech import TECHFunction  # noqa: E402

EQ = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _run(coro):
    return asyncio.run(coro)


def _ohlc(n: int, seed: int = 11) -> pd.DataFrame:
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1.0 + rng.gauss(0.0, 0.01)))
    rows = []
    for i, close in enumerate(closes):
        prev = closes[i - 1] if i else close
        opened = prev * (1.0 + rng.gauss(0.0, 0.003))
        high = max(opened, close) * (1.0 + abs(rng.gauss(0.0, 0.006)))
        low = min(opened, close) * (1.0 - abs(rng.gauss(0.0, 0.006)))
        rows.append((opened, high, low, close, 1_000_000.0 + rng.random() * 1e5))
    index = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame(rows, index=index, columns=["open", "high", "low", "close", "volume"])


class _RecordingYfinance:
    def __init__(self, df: pd.DataFrame | None) -> None:
        self._df = df
        self.calls: list[Any] = []

    async def fetch(self, request: Any, *args: Any, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(request)
        return self._df if self._df is not None else pd.DataFrame()


# ── TECH#3 ────────────────────────────────────────────────────────────────


def test_tech_empty_history_never_earns_live_data_state():
    """An empty price history is an outage for that symbol, not live data."""
    from showme import server

    fn = TECHFunction(FunctionDeps(yfinance=_RecordingYfinance(pd.DataFrame())))
    res = _run(fn.execute(instrument=EQ, days=90))
    assert res.data["status"] == "no_price_history"

    payload = server.enforce_live_or_label_synthetic(
        "TECH", {"symbol": "AAPL"}, res.to_dict()
    )
    assert payload["data_state"] != "live", payload["data_state"]
    assert payload["status"] == "empty"


# ── TECH#4 ────────────────────────────────────────────────────────────────


def test_router_defaults_do_not_shrink_tech_window():
    """The generic agent profile injects limit=6 and days=120 for every route.

    TECH reads ``limit`` as its visible-bar tail, so the injected value clamped
    the pane to 60 bars over 3 months. The pane must get the manifest window.
    """
    from showme import server

    routed = server._route_function_params("TECH", {"symbol": "AAPL"})
    assert "limit" not in routed, routed.get("limit")
    assert routed.get("days") in (None, 365), routed.get("days")

    fn = TECHFunction(FunctionDeps(yfinance=_RecordingYfinance(_ohlc(300))))
    res = _run(fn.execute(instrument=EQ, **routed))
    assert res.metadata["days"] == 365
    assert res.metadata["tail"] == 1000
    assert res.data["bar_count"] == 300


def test_explicit_caller_limit_still_sets_tail():
    """A caller-supplied limit is still honoured as the visible-bar tail."""
    from showme import server

    routed = server._route_function_params("TECH", {"symbol": "AAPL", "limit": 80})
    assert routed.get("limit") == 80

    fn = TECHFunction(FunctionDeps(yfinance=_RecordingYfinance(_ohlc(300))))
    res = _run(fn.execute(instrument=EQ, **routed))
    assert res.data["bar_count"] == 80


# ── TECH#5 ────────────────────────────────────────────────────────────────


def test_studies_select_only_requested_families():
    fn = TECHFunction(FunctionDeps(yfinance=_RecordingYfinance(_ohlc(300))))
    res = _run(fn.execute(instrument=EQ, studies=["RSI"]))
    data = res.data
    assert data["status"] == "ok"
    assert set(data["indicators"]) == set(), data["indicators"].keys()
    assert [r["indicator"] for r in data["indicator_rows"]] == ["RSI"]
    row = data["rows"][-1]
    assert row.get("rsi") is not None
    assert "sma_fast" not in row and "macd" not in row and "atr" not in row


def test_studies_absent_keeps_every_family():
    fn = TECHFunction(FunctionDeps(yfinance=_RecordingYfinance(_ohlc(300))))
    res = _run(fn.execute(instrument=EQ))
    keys = set(res.data["indicators"])
    assert {"sma_20", "sma_50", "ema_20", "bb_upper", "stoch_k", "tenkan"} <= keys
    row = res.data["rows"][-1]
    assert row.get("rsi") is not None and row.get("macd") is not None


def test_unknown_study_is_an_input_error_not_silent():
    provider = _RecordingYfinance(_ohlc(300))
    fn = TECHFunction(FunctionDeps(yfinance=provider))
    res = _run(fn.execute(instrument=EQ, studies=["RSI", "NOPE"]))
    assert res.data["status"] == "input_error"
    assert "NOPE" in res.data["reason"]
    assert res.data["rows"] == []


def test_unsupported_interval_is_an_input_error_without_fetch():
    provider = _RecordingYfinance(_ohlc(300))
    fn = TECHFunction(FunctionDeps(yfinance=provider))
    res = _run(fn.execute(instrument=EQ, interval="7m"))
    assert res.data["status"] == "input_error"
    assert "7m" in res.data["reason"]
    assert provider.calls == []


# ── TECH#6 ────────────────────────────────────────────────────────────────


def test_field_dictionary_paths_exist_in_output():
    from showme.manifest import REGISTRY, load_seeds  # noqa: PLC0415

    load_seeds()
    manifest = REGISTRY.get("TECH")
    fn = TECHFunction(FunctionDeps(yfinance=_RecordingYfinance(_ohlc(300))))
    data = _run(fn.execute(instrument=EQ)).data
    indicator_keys = set(data["indicators"])
    row_keys = set(data["rows"][-1])
    for path in manifest.field_dict:
        if path == "ohlcv[]":
            assert data["ohlcv"], path
        elif path.startswith("rows[]."):
            assert path.split(".", 1)[1] in row_keys, path
        elif path.startswith("indicators."):
            assert path.split(".", 1)[1] in indicator_keys, path
        else:
            pytest.fail(f"unrecognised field_dict path {path!r}")


def test_deep_history_follows_fetched_history_not_requested_tail():
    short = TECHFunction(FunctionDeps(yfinance=_RecordingYfinance(_ohlc(100))))
    assert _run(short.execute(instrument=EQ)).data["deep_history"] is False

    long = TECHFunction(FunctionDeps(yfinance=_RecordingYfinance(_ohlc(300))))
    # Only 60 bars are shown, but 300 were fetched: the history is deep.
    assert _run(long.execute(instrument=EQ, tail=60)).data["deep_history"] is True
