"""FA#3 — an empty SEC result must fall through to yfinance, not shadow it.

When SEC EDGAR returns ``{}`` (no us-gaap facts, e.g. IFRS / ADR filers) the
function already fetches yfinance, but the SEC branch was selected because
``{}`` is not ``None``. The result was calc_error with empty statements even
though yfinance held data. These tests drive ``FAFunction.execute`` with fake
SEC and yfinance providers (no network).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.fa import FAFunction


def _run(coro):
    return asyncio.run(coro)


class _EmptySec:
    async def standard_fundamentals(self, ticker: str, period: str = "annual") -> dict[str, Any]:
        return {}


class _NoSec:
    async def standard_fundamentals(self, ticker: str, period: str = "annual") -> dict[str, Any]:
        raise RuntimeError("no CIK")


class _Yf:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, request: Any) -> dict[str, pd.DataFrame]:
        self.calls += 1
        cols = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
        income = pd.DataFrame(
            [[100.0, 90.0], [40.0, 36.0], [20.0, 18.0]],
            index=["Total Revenue", "Gross Profit", "Net Income"],
            columns=cols,
        )
        balance = pd.DataFrame(
            [[300.0, 280.0], [150.0, 140.0]],
            index=["Total Assets", "Stockholders Equity"],
            columns=cols,
        )
        cashflow = pd.DataFrame(
            [[30.0, 25.0]],
            index=["Operating Cash Flow"],
            columns=cols,
        )
        return {"income": income, "balance": balance, "cashflow": cashflow}


def _instrument() -> Instrument:
    return Instrument(symbol="TSM", asset_class=AssetClass.EQUITY)


def test_empty_sec_result_uses_yfinance_statements() -> None:
    yf = _Yf()
    fn = FAFunction(deps=FunctionDeps(sec_edgar=_EmptySec(), yfinance=yf))
    result = _run(fn.execute(instrument=_instrument(), period="annual"))
    data = result.data

    assert yf.calls == 1, "empty SEC payload must trigger the yfinance fallback"
    assert data["source"] == "yfinance", "the yfinance data must be the one used"
    assert data["statement_counts"]["income_statement"] > 0
    assert data["status"] == "ok"
    assert result.sources == ["yfinance"], "sources must list only providers that supplied data"


def test_sec_error_still_falls_back_to_yfinance() -> None:
    yf = _Yf()
    fn = FAFunction(deps=FunctionDeps(sec_edgar=_NoSec(), yfinance=yf))
    result = _run(fn.execute(instrument=_instrument(), period="annual"))
    assert result.data["source"] == "yfinance"
    assert result.data["status"] == "ok"


def test_sec_statements_still_preferred_when_present() -> None:
    idx = pd.to_datetime(["2024-12-31", "2025-12-31"])

    class _Sec:
        async def standard_fundamentals(self, ticker: str, period: str = "annual") -> dict[str, pd.Series]:
            return {
                "revenue": pd.Series([100.0, 120.0], index=idx),
                "net_income": pd.Series([18.0, 22.0], index=idx),
                "total_equity": pd.Series([150.0, 180.0], index=idx),
            }

    yf = _Yf()
    fn = FAFunction(deps=FunctionDeps(sec_edgar=_Sec(), yfinance=yf))
    result = _run(fn.execute(instrument=_instrument(), period="annual"))
    assert result.data["source"] == "sec_edgar"
    assert yf.calls == 0, "yfinance must not be fetched when SEC has statements"
    assert result.sources == ["sec_edgar"]


def test_empty_sec_and_empty_yfinance_does_not_list_yfinance() -> None:
    """FA#3: yfinance returned no statements, so it must not be listed as a source."""

    class _EmptyYf:
        async def fetch(self, request: Any) -> dict[str, pd.DataFrame]:
            return {}

    fn = FAFunction(deps=FunctionDeps(sec_edgar=_EmptySec(), yfinance=_EmptyYf()))
    result = _run(fn.execute(instrument=_instrument(), period="annual"))

    assert result.data["status"] == "provider_unavailable"
    assert "yfinance" not in result.sources, result.sources
    assert "sec_edgar" not in result.sources, result.sources
