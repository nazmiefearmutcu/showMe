"""P1a-g01 regression for PVAR coverage (PVAR#1).

``max_positions`` used to truncate the eligible book BEFORE coverage was
computed, so a 7-position book cut to 3 reported ``coverage_pct = 1.0`` with no
warning. Coverage must be measured against the full eligible book, and every
excluded position must be named in a warning.

Network is patched: PortfolioState and the yfinance download are replaced.
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import pvar as pvar_mod


class _Pos:
    def __init__(self, symbol: str, quantity: float, avg_cost: float) -> None:
        self.instrument = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
        self.quantity = quantity
        self.avg_cost = avg_cost
        self.account = "main"
        self.currency = "USD"


class _Book:
    """Seven-position book in the spirit of the reported defect."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.positions = [
            _Pos("AAPL", 10.0, 100.0),
            _Pos("MSFT", 20.0, 100.0),
            _Pos("NVDA", 8.0, 150.0),
            _Pos("AMZN", 5.0, 120.0),
            _Pos("GOOG", 4.0, 90.0),
            _Pos("META", 3.0, 200.0),
            _Pos("GME", 5.0, 20.0),
        ]

    def import_legacy_crypto(self) -> int:
        return 0


class _ThreePosBook(_Book):
    def __init__(self, *_args, **_kwargs) -> None:
        self.positions = [
            _Pos("MSFT", 20.0, 100.0),
            _Pos("AAPL", 10.0, 100.0),
            _Pos("GME", 5.0, 20.0),
        ]


def _fake_download(symbol, days, timeout):
    idx = pd.date_range(end="2026-09-20", periods=80, freq="D")
    returns = pd.Series([0.001 * ((i % 7) - 3) + 0.0001 * len(symbol) for i in range(80)], index=idx)
    return returns, 105.0


def _run(coro):
    return asyncio.run(coro)


def test_truncated_book_reports_partial_coverage(monkeypatch) -> None:
    """Analysing 2 of 3 eligible positions must not read as full coverage."""
    monkeypatch.setattr(pvar_mod, "PortfolioState", _ThreePosBook)
    monkeypatch.setattr(pvar_mod, "_download_returns", _fake_download)
    res = _run(pvar_mod.PVARFunction().execute(max_positions=2, method="parametric"))
    data = res.data
    assert data["status"] == "ok"
    assert data["positions_analyzed"] == 2
    # Red today: coverage_pct is 1.0 because the denominator is the truncated list.
    assert data["coverage_pct"] == pytest.approx(2 / 3, abs=1e-3), data["coverage_pct"]
    assert data["summary"]["coverage_pct"] == pytest.approx(2 / 3, abs=1e-3)
    assert data["positions_eligible"] == 3
    assert data["excluded_symbols"] == ["GME"]
    assert any("GME" in w and "max_positions" in w for w in res.warnings), res.warnings


def test_full_book_has_full_coverage_and_no_exclusion_warning(monkeypatch) -> None:
    monkeypatch.setattr(pvar_mod, "PortfolioState", _Book)
    monkeypatch.setattr(pvar_mod, "_download_returns", _fake_download)
    res = _run(pvar_mod.PVARFunction().execute(max_positions=12, method="parametric"))
    data = res.data
    assert data["status"] == "ok"
    assert data["coverage_pct"] == pytest.approx(1.0)
    assert data["positions_eligible"] == 7
    assert data["excluded_symbols"] == []
    assert not any("max_positions" in w for w in res.warnings), res.warnings


def test_default_cap_on_seven_position_book_covers_everything(monkeypatch) -> None:
    """The pane sends max_positions=12; a 7-position book is fully analysed."""
    monkeypatch.setattr(pvar_mod, "PortfolioState", _Book)
    monkeypatch.setattr(pvar_mod, "_download_returns", _fake_download)
    res = _run(pvar_mod.PVARFunction().execute())
    assert res.data["positions_analyzed"] == 7
    assert res.data["coverage_pct"] == pytest.approx(1.0)
