"""RV — Relative Valuation vs peer set."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class RVFunction(BaseFunction):
    code = "RV"
    name = "Relative Valuation"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        peers: list[str] = []
        if self.deps.finnhub:
            try:
                peers = await asyncio.wait_for(
                    self.deps.finnhub.peers(instrument.symbol),
                    timeout=float(params.get("finnhub_timeout", 8)),
                )
            except Exception:
                peers = []
        peers = [p for p in peers if p != instrument.symbol][:8]
        full = [instrument.symbol] + peers
        rows: list[dict[str, Any]] = []
        if self.deps.yfinance:
            from src.core.base_data_source import DataKind, DataRequest
            from src.core.instrument import Instrument as I
            tasks = [asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA,
                    instrument=I(symbol=s, asset_class=AssetClass.EQUITY, exchange="NASDAQ"),
                )),
                timeout=float(params.get("yfinance_timeout", 8)),
            ) for s in full]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for sym, r in zip(full, results):
                if isinstance(r, Exception) or r is None:
                    continue
                raw = (r.extras or {}).get("raw", {}) if hasattr(r, "extras") else {}
                rows.append({
                    "symbol": sym,
                    "marketCap": r.market_cap or raw.get("marketCap"),
                    "pe": raw.get("trailingPE"),
                    "fwd_pe": raw.get("forwardPE"),
                    "pb": raw.get("priceToBook"),
                    "ps": raw.get("priceToSalesTrailing12Months"),
                    "ev_ebitda": raw.get("enterpriseToEbitda"),
                    "roe": raw.get("returnOnEquity"),
                    "roa": raw.get("returnOnAssets"),
                    "debt_equity": raw.get("debtToEquity"),
                    "div_yield": raw.get("dividendYield"),
                })
        if not rows:
            rows = [{
                "symbol": instrument.symbol,
                "marketCap": None,
                "pe": None,
                "fwd_pe": None,
                "pb": None,
                "ps": None,
                "ev_ebitda": None,
                "roe": None,
                "roa": None,
                "debt_equity": None,
                "div_yield": None,
                "status": "provider_unavailable",
            }]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=pd.DataFrame(rows),
            sources=["finnhub", "yfinance"] if self.deps.yfinance else ["relative_value_model"],
            metadata={"peers": peers},
        )
