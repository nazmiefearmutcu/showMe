"""RV — Relative Valuation vs peer set."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.functions.equity._common import finite, reference_profile


@FunctionRegistry.register
class RVFunction(BaseFunction):
    code = "RV"
    name = "Relative Valuation"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        raw_peers = params.get("peers")
        peers: list[str] = [str(p).strip().upper() for p in raw_peers if str(p).strip()] if isinstance(raw_peers, (list, tuple, set)) else []
        if self.deps.finnhub:
            try:
                if not peers:
                    peers = await asyncio.wait_for(
                        self.deps.finnhub.peers(instrument.symbol),
                        timeout=float(params.get("finnhub_timeout", 8)),
                    )
            except Exception:
                peers = peers or []
        peers = [p for p in peers if p != instrument.symbol][:8]
        if not peers:
            peers = [p for p in reference_profile(instrument.symbol).get("peers", []) if p != instrument.symbol][:6]
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
                    "source_mode": "live_yfinance",
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
                "source_mode": "provider_unavailable",
            }]
        rows = _rank_rows(rows, instrument.symbol)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok" if len(rows) > 1 else "provider_unavailable",
                "rows": rows,
                "peers": peers,
                "methodology": "RV compares the target against a peer set from Finnhub or a labelled sector-reference peer map. Multiples are live yfinance fields when available; rank is computed within returned peers.",
                "field_dictionary": {
                    "pe": "Trailing price/earnings multiple.",
                    "fwd_pe": "Forward price/earnings multiple.",
                    "ev_ebitda": "Enterprise value / EBITDA.",
                    "rank_pe": "Ascending PE rank within peer set.",
                    "percentile_pe": "Peer percentile for PE, lower is cheaper.",
                },
            },
            sources=["finnhub", "yfinance"] if self.deps.yfinance else ["relative_value_model"],
            metadata={"peers": peers},
        )


def _rank_rows(rows: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    valid = sorted(
        [r for r in rows if finite(r.get("pe")) is not None],
        key=lambda r: finite(r.get("pe")) or 0,
    )
    n = max(1, len(valid) - 1)
    ranks = {r["symbol"]: (idx + 1, idx / n if n else 0) for idx, r in enumerate(valid)}
    for row in rows:
        rank = ranks.get(row.get("symbol"))
        if rank:
            row["rank_pe"] = rank[0]
            row["percentile_pe"] = round(rank[1] * 100, 2)
        row["is_target"] = row.get("symbol") == target
    return rows
