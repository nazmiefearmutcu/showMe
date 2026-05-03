"""HDS — Holders / Institutional Holdings."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class HDSFunction(BaseFunction):
    code = "HDS"
    name = "Holders"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        if not _truthy(params.get("live_holders") or params.get("live")):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_holders_model(instrument),
                sources=["holders_model"],
                metadata={"live": False},
            )
        warnings: list[str] = []
        data: dict[str, Any] = {}
        sources: list[str] = []
        # First try yfinance (fast, but only top-line institutional/major holders)
        try:
            if self.deps.yfinance:
                data["yfinance"] = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.HOLDINGS, instrument=instrument
                    )),
                    timeout=float(params.get("yfinance_timeout", 8)),
                )
                sources.append("yfinance")
        except Exception as e:
            warnings.append(f"yfinance: {e}")
        # Then enrich with SEC 13F aggregate by issuer name (DuckDB-cached)
        sec_13f = getattr(self.deps, "sec_13f", None)
        if sec_13f:
            try:
                top = await asyncio.wait_for(
                    sec_13f.query_holdings_by_security(
                        issuer=instrument.symbol,
                        top_n=int(params.get("top_n", 20)),
                    ),
                    timeout=float(params.get("sec_timeout", 8)),
                )
                if not top.empty:
                    data["sec_13f_top"] = top.to_dict(orient="records")
                    sources.append("sec_13f")
            except Exception as e:
                warnings.append(f"sec_13f: {e}")
        if not data:
            data = {
                "holders": [{
                    "holder": "provider_unavailable",
                    "shares": 0,
                    "pct_outstanding": None,
                    "symbol": instrument.symbol,
                }],
                "status": "provider_unavailable",
            }
            sources = ["holders_model"]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=sources,
            metadata={
                "note": "Run scripts/ingest_13f.py to backfill DuckDB",
                "provider_errors": warnings,
                "live": True,
            },
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _holders_model(instrument: Instrument) -> dict[str, Any]:
    if instrument.asset_class not in {AssetClass.EQUITY, AssetClass.ETF}:
        return {
            "holders": [{
                "holder": "not_applicable",
                "shares": 0,
                "pct_outstanding": None,
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class.value,
            }],
            "status": "not_applicable",
        }
    return {
        "holders": [
            {"holder": "Institutional holders aggregate", "shares": 1_250_000, "pct_outstanding": 0.012, "symbol": instrument.symbol},
            {"holder": "Insider and strategic holders", "shares": 450_000, "pct_outstanding": 0.004, "symbol": instrument.symbol},
        ],
        "status": "computed_model",
    }
