"""BLAK#1 regression: the prior uses the declared lookback, not 120 days.

The router's generic agent profile injected ``days=120`` and ``range=3M`` into
every routed BLAK call, so the Black-Litterman prior was estimated on about 83
observations while the seed declared a 1Y window. These tests pin:

* the routed BLAK call carries no injected ``days`` or ``range``;
* the default history start is the seeded 1Y window (365 calendar days);
* an explicit ``window`` (180d, 1Y, 2Y, 5Y) is honoured and reported;
* an explicit ``days`` still wins, and an unknown window is refused;
* the effective lookback is disclosed in the payload.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.blak import BLAKFunction

_SYMBOLS = ["AAPL", "MSFT", "SPY"]
_CAPS = {"AAPL": 3.9e12, "MSFT": 3.5e12, "SPY": 7.9e11}


@dataclass
class _Ref:
    market_cap: float | None = None
    extras: dict = field(default_factory=dict)


def _frame(n_rows: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n_rows, freq="B")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, size=n_rows)))
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": 1_000_000},
        index=idx,
    )


class _RecordingYf:
    """Records each OHLCV request's start date and serves a fixed history."""

    def __init__(self) -> None:
        self.starts: list[datetime] = []
        self._frames = {sym: _frame(120, seed=i + 1) for i, sym in enumerate(_SYMBOLS)}

    async def fetch(self, request: Any) -> Any:
        sym = request.instrument.symbol.upper()
        if request.kind == DataKind.REFDATA:
            return _Ref(market_cap=_CAPS.get(sym))
        self.starts.append(request.start)
        return self._frames[sym]


def _run(yf: _RecordingYf, **params: Any):
    func = BLAKFunction(deps=FunctionDeps(yfinance=yf))
    return asyncio.run(func.execute(symbols=_SYMBOLS, live=True, **params))


def _age_days(start: datetime) -> int:
    return (datetime.now(timezone.utc) - start).days


def test_router_injects_no_days_or_range_for_blak() -> None:
    from showme.server_routes._agent_runtime import _route_function_params

    routed = _route_function_params("BLAK", {"symbols": _SYMBOLS, "live": True})
    assert "days" not in routed
    assert "range" not in routed


def test_default_lookback_is_the_seeded_one_year() -> None:
    yf = _RecordingYf()
    result = _run(yf)
    assert yf.starts, "live run must request history"
    assert 364 <= _age_days(yf.starts[0]) <= 366
    assert result.data["window"] == "1Y"
    assert result.data["lookback_days"] == 365
    assert result.data["summary"]["window"] == "1Y"


def test_explicit_window_is_honoured_and_reported() -> None:
    yf = _RecordingYf()
    result = _run(yf, window="2Y")
    assert 729 <= _age_days(yf.starts[0]) <= 731
    assert result.data["window"] == "2Y"
    assert result.data["lookback_days"] == 730


def test_explicit_days_still_wins_over_the_window() -> None:
    yf = _RecordingYf()
    result = _run(yf, days=504)
    assert 503 <= _age_days(yf.starts[0]) <= 505
    assert result.data["window"] == "504d"
    assert result.data["lookback_days"] == 504


def test_unknown_window_is_refused_explicitly() -> None:
    yf = _RecordingYf()
    result = _run(yf, window="3M")
    assert result.data["status"] == "input_error"
    assert "prior_covariance" not in result.data
    assert yf.starts == []


def test_routed_pane_payload_with_window_reaches_the_engine() -> None:
    """BLAK#1 follow-up: the pane sends ``window`` and no ``days``.

    The router used to keep the generic profile's injected ``days=120`` when a
    ``window`` was present, so the seeded 1Y selector was silently overridden.
    The routed payload must carry no injected days, and the engine must start
    history 1Y back.
    """
    from showme.server_routes._agent_runtime import _route_function_params

    pane_params = {
        "symbols": _SYMBOLS,
        "window": "1Y",
        "live": True,
        "tau": 0.05,
        "delta": 2.5,
        "views_text": "",
    }
    routed = _route_function_params("BLAK", pane_params)
    assert "days" not in routed
    assert "range" not in routed
    assert routed["window"] == "1Y"

    yf = _RecordingYf()
    func = BLAKFunction(deps=FunctionDeps(yfinance=yf))
    result = asyncio.run(func.execute(**routed))
    assert yf.starts, "routed live run must request history"
    assert 364 <= _age_days(yf.starts[0]) <= 366
    assert result.data["window"] == "1Y"
    assert result.data["lookback_days"] == 365


def test_routed_pane_payload_with_explicit_days_keeps_days() -> None:
    """A caller-supplied ``days`` is an explicit day count and must survive routing."""
    from showme.server_routes._agent_runtime import _route_function_params

    routed = _route_function_params("BLAK", {"symbols": _SYMBOLS, "days": 504, "live": True})
    assert routed["days"] == 504

    yf = _RecordingYf()
    func = BLAKFunction(deps=FunctionDeps(yfinance=yf))
    result = asyncio.run(func.execute(**routed))
    assert 503 <= _age_days(yf.starts[0]) <= 505
    assert result.data["lookback_days"] == 504
