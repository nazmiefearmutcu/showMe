"""P1a-g03 IVOL#1 — solver-failure implied vols must not reach the surface.

A deep in-the-money SPY put whose quoted mid sits below intrinsic has no real
implied vol. The provider reports iv ~ 0 (1e-5 here), and the engine used to
keep it as a 0.001 percent surface cell. These tests drive IVOLFunction.execute
through a fake option-chain adapter (no network).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative._stubs import IVOLFunction

SPOT = 735.29
EXPIRY = "2026-11-09"

# (strike, iv, bid, ask) — puts and calls for one expiry.
# Invalid cells: put 750 (iv 1e-5, mid below intrinsic 14.71),
# put 745 (iv 0.40 but mid 9.2 below intrinsic 9.71),
# put 760 (iv 0.0, mid below intrinsic), call 720 (iv 0.0).
PUTS = [
    (750, 1e-5, 14.14, 14.40),
    (745, 0.40, 8.80, 9.60),
    (760, 0.0, 23.46, 24.32),
    (735, 0.18, 9.00, 9.40),
    (700, 0.20, 2.00, 2.20),
]
CALLS = [
    (720, 0.0, 22.00, 22.60),
    (735, 0.17, 10.00, 10.40),
    (760, 0.19, 3.10, 3.30),
]
INVALID_STRIKES = {("PUT", 750.0), ("PUT", 745.0), ("PUT", 760.0), ("CALL", 720.0)}


class _ChainYF:
    async def fetch(self, request: DataRequest) -> Any:
        assert request.kind == DataKind.OPTIONS_CHAIN
        if not request.extra or "expiry" not in request.extra:
            return {"underlyingPrice": SPOT, "expiries": [EXPIRY]}
        calls = pd.DataFrame({
            "strike": [c[0] for c in CALLS],
            "impliedVolatility": [c[1] for c in CALLS],
            "bid": [c[2] for c in CALLS],
            "ask": [c[3] for c in CALLS],
            "lastPrice": [(c[2] + c[3]) / 2 for c in CALLS],
            "volume": [10] * len(CALLS),
            "openInterest": [100] * len(CALLS),
        })
        puts = pd.DataFrame({
            "strike": [p[0] for p in PUTS],
            "impliedVolatility": [p[1] for p in PUTS],
            "bid": [p[2] for p in PUTS],
            "ask": [p[3] for p in PUTS],
            "lastPrice": [(p[2] + p[3]) / 2 for p in PUTS],
            "volume": [10] * len(PUTS),
            "openInterest": [100] * len(PUTS),
        })
        return {"calls": calls, "puts": puts}


class _Deps:
    def __init__(self, yfinance: Any = None) -> None:
        self.yfinance = yfinance

    def __getattr__(self, item: str) -> Any:  # pragma: no cover
        return None


def _run() -> Any:
    fn = IVOLFunction(deps=_Deps(yfinance=_ChainYF()))
    return asyncio.run(fn.execute(Instrument(symbol="SPY", asset_class=AssetClass.ETF)))


def test_no_solver_failure_cell_reaches_the_surface() -> None:
    result = _run()
    surface = result.data["surface"]
    # RED before fix: the 1e-5 and 0.0 cells were kept as 0.001% / 0% IV.
    assert surface, "valid cells must still produce a surface"
    assert all(row["vol"] >= 0.01 for row in surface), [
        (row["label"], row["vol"]) for row in surface if row["vol"] < 0.01
    ]


def test_mid_below_intrinsic_cells_are_dropped() -> None:
    result = _run()
    kept = {(row["option_type"], float(row["strike"])) for row in result.data["surface"]}
    # RED before fix: put 750 (mid 14.27 < intrinsic 14.71) and put 745 stayed in.
    assert ("PUT", 750.0) not in kept
    assert ("PUT", 745.0) not in kept
    assert ("PUT", 760.0) not in kept
    assert ("CALL", 720.0) not in kept


def test_valid_cells_are_kept_and_dropped_count_is_reported() -> None:
    result = _run()
    kept = {(row["option_type"], float(row["strike"])) for row in result.data["surface"]}
    assert ("PUT", 735.0) in kept
    assert ("PUT", 700.0) in kept
    assert ("CALL", 735.0) in kept
    assert ("CALL", 760.0) in kept
    assert kept.isdisjoint(INVALID_STRIKES)
    assert result.data["summary"]["dropped_invalid_iv"] == len(INVALID_STRIKES)
    assert result.data["summary"]["contracts"] == len(PUTS) + len(CALLS) - len(INVALID_STRIKES)
