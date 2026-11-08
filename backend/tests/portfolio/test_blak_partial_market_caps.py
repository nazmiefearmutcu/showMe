"""BLAK#2 regression: partial market-cap coverage must never read as real.

Before the fix ``_resolve_market_caps`` reported ``market_cap_data_state``
"real" as soon as ONE symbol resolved. The unresolved names then got a
weight of exactly 0 (their market cap was 0) with no warning, so for
AAPL+SPY+QQQ the prior was 100% AAPL while the label said "real".

These tests pin the honest contract:

* partial coverage is labelled ``partial`` and the prior falls back to the
  labelled equal-weight prior with a warning naming the unresolved symbols;
* fund AUM (``totalAssets`` for ETF / mutual-fund quote types only) is a real
  keyless market-value proxy and is used when present;
* an operating company's ``totalAssets`` (balance-sheet assets) is NEVER
  used as a market cap.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.blak import BLAKFunction


@dataclass
class _Ref:
    market_cap: float | None = None
    extras: dict = field(default_factory=dict)


class _Yf:
    """REFDATA-only yfinance stub keyed by symbol."""

    def __init__(self, table: dict[str, _Ref]) -> None:
        self._table = table

    async def fetch(self, request: Any) -> Any:
        return self._table.get(request.instrument.symbol.upper(), _Ref())


def _run(symbols: list[str], table: dict[str, _Ref]):
    func = BLAKFunction(deps=FunctionDeps(yfinance=_Yf(table)))
    return asyncio.run(func.execute(symbols=symbols))


def test_partial_market_caps_are_not_reported_real() -> None:
    table = {"AAPL": _Ref(market_cap=3.9e12, extras={"raw": {"quoteType": "EQUITY"}})}
    result = _run(["AAPL", "SPY", "QQQ"], table)

    # Unresolved ETFs must not be silently zeroed under a "real" label.
    assert result.data["market_cap_data_state"] == "approximate"
    weights = result.data["market_weights"]
    for sym in ("AAPL", "SPY", "QQQ"):
        assert abs(weights[sym] - 1 / 3) < 1e-9
    assert any("SPY" in w and "QQQ" in w for w in result.warnings)
    assert result.data["market_cap_coverage"] == {
        "resolved": 1,
        "requested": 3,
        "missing": ["SPY", "QQQ"],
    }


def test_fund_aum_is_used_as_labelled_market_value_proxy() -> None:
    table = {
        "AAPL": _Ref(market_cap=3.9e12, extras={"raw": {"quoteType": "EQUITY"}}),
        "SPY": _Ref(extras={"raw": {"quoteType": "ETF", "totalAssets": 7.9e11}}),
    }
    result = _run(["AAPL", "SPY"], table)

    assert result.data["market_cap_data_state"] == "real"
    assert "yfinance_fund_aum" in result.sources
    expected_spy = 7.9e11 / (3.9e12 + 7.9e11)
    assert abs(result.data["market_weights"]["SPY"] - expected_spy) < 1e-9


def test_equity_total_assets_is_never_used_as_market_cap() -> None:
    table = {
        "AAPL": _Ref(market_cap=3.9e12, extras={"raw": {"quoteType": "EQUITY"}}),
        # Balance-sheet total assets of an operating company, not a market value.
        "JPM": _Ref(extras={"raw": {"quoteType": "EQUITY", "totalAssets": 4.0e12}}),
    }
    result = _run(["AAPL", "JPM"], table)

    assert result.data["market_cap_data_state"] == "approximate"
    assert result.data["market_cap_coverage"]["missing"] == ["JPM"]
