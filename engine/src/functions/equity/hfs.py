"""HFS — Holder search (13F reverse lookup).

For an issuer ticker / company / CUSIP: which filers held it last quarter,
how many shares, total notional, ranked.

Backed by `data_sources/equity/sec_13f_adapter.py` DuckDB store.
Run `python scripts/ingest_13f.py` first to populate.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class HFSFunction(BaseFunction):
    code = "HFS"
    name = "Holder Search"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "13F reverse lookup — list filers holding a given issuer / CUSIP."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        issuer = params.get("issuer") or (instrument.symbol if instrument else None)
        if not _truthy(params.get("live_holders") or params.get("live")):
            rows = _holder_search_template(issuer, instrument)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=rows,
                sources=["holder_search_model"],
                metadata={"issuer": issuer, "rows": len(rows), "live": False},
            )
        sec = getattr(self.deps, "sec_13f", None)
        if sec is None:
            rows = _holder_search_template(issuer, instrument)
            return FunctionResult(code=self.code, instrument=instrument, data=rows,
                                  sources=["holder_search_model"])
        cusip = params.get("cusip")
        quarter = params.get("quarter")
        top_n = int(params.get("top_n", 30))
        try:
            df = await asyncio.wait_for(
                sec.query_holdings_by_security(
                    cusip=cusip, issuer=issuer, quarter=quarter, top_n=top_n,
                ),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception as e:
            rows = [{"filer": "No local 13F match", "issuer": issuer,
                     "shares": 0, "market_value": 0, "status": "provider_unavailable"}]
            return FunctionResult(code=self.code, instrument=instrument, data=rows,
                                  sources=["holder_search_model"],
                                  metadata={"provider_errors": [f"sec_13f: {e}"]})
        rows: list[dict[str, Any]] = []
        if hasattr(df, "to_dict") and not df.empty:
            rows = df.to_dict(orient="records")
        if not rows:
            rows = [{"filer": "No local 13F match", "issuer": issuer,
                     "shares": 0, "market_value": 0}]
        return FunctionResult(
            code=self.code, instrument=instrument, data=rows,
            sources=["sec_13f"],
            metadata={"cusip": cusip, "issuer": issuer,
                       "quarter": quarter, "rows": len(rows),
                       "note": "Run scripts/ingest_13f.py to backfill DuckDB.",
                       "live": True},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _holder_search_template(issuer: str | None, instrument: Instrument | None) -> list[dict[str, Any]]:
    asset_class = instrument.asset_class.value if instrument else "UNKNOWN"
    if instrument and instrument.asset_class not in {AssetClass.EQUITY, AssetClass.ETF}:
        return [{
            "filer": "not_applicable",
            "issuer": issuer,
            "shares": 0,
            "market_value": 0,
            "asset_class": asset_class,
        }]
    return [
        {"filer": "Sample institutional filer", "issuer": issuer, "shares": 1200000, "market_value": 185000000},
        {"filer": "Sample long-only manager", "issuer": issuer, "shares": 760000, "market_value": 117000000},
    ]
