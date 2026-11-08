"""BLAK#4 regression: a slow ETF reference lookup must still yield the AUM proxy.

yfinance reports ``marketCap`` as None for ETFs, and the real market value is
``totalAssets`` (fund AUM, labelled as a proxy). The REFDATA call for SPY took
about 4.4 s live, while BLAK cancelled it at 4 s. The proxy never arrived, so
every default ETF universe silently fell back to an equal-weight prior.

The stub below answers after 4.5 s, just past the old cap, and the test pins
the proxy weight and its ``proxy`` label.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.blak import BLAKFunction

_SLOW_REFDATA_S = 4.5  # just past the former 4 s budget, inside the 8 s budget


@dataclass
class _Ref:
    market_cap: float | None = None
    extras: dict = field(default_factory=dict)


class _SlowEtfYf:
    async def fetch(self, request: Any) -> Any:
        sym = request.instrument.symbol.upper()
        if request.kind != DataKind.REFDATA:
            raise AssertionError("market-cap test must not request price history")
        if sym == "SPY":
            await asyncio.sleep(_SLOW_REFDATA_S)
            return _Ref(extras={"raw": {"quoteType": "ETF", "totalAssets": 7.9e11}})
        return _Ref(market_cap=3.9e12, extras={"raw": {"quoteType": "EQUITY"}})


def test_slow_etf_refdata_still_yields_fund_aum_proxy() -> None:
    func = BLAKFunction(deps=FunctionDeps(yfinance=_SlowEtfYf()))
    result = asyncio.run(func.execute(symbols=["AAPL", "SPY"]))

    assert result.data["market_cap_data_state"] == "proxy"
    assert "yfinance_fund_aum" in result.sources
    expected_spy = 7.9e11 / (3.9e12 + 7.9e11)
    assert abs(result.data["market_weights"]["SPY"] - expected_spy) < 1e-9
    assert any("fund AUM" in w and "SPY" in w for w in result.warnings)
    assert result.data["market_cap_coverage"]["missing"] == []
