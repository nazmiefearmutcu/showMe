"""FTS — SEC EDGAR Full-Text Search.

Plan §26.2 bonus: cross-issuer text search across 10-K, 10-Q, 8-K, S-1 ...
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class FTSFunction(BaseFunction):
    code = "FTS"
    name = "SEC Full-Text Search"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Search SEC EDGAR filings by free text + form type + date range."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sec = getattr(self.deps, "sec_efts", None)
        query = params.get("query") or (instrument.symbol if instrument else "")
        if not query:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=["empty query"])
        live = _truthy(params.get("live_search") or params.get("live_filings") or params.get("live"))
        if not live or sec is None or (instrument and instrument.asset_class.value != "EQUITY"):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_fallback_hits(query, instrument),
                sources=["sec_search_model"],
                metadata={"query": query, "live": False},
            )
        forms = params.get("forms") or None
        try:
            hits = await asyncio.wait_for(
                sec.search(
                    query, forms=forms,
                    start=params.get("start"),
                    end=params.get("end"),
                    limit=int(params.get("limit", 50)),
                ),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception as e:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_fallback_hits(query, instrument),
                                  sources=["sec_search_model"],
                                  metadata={"provider_errors": [f"sec_efts: {e}"]})
        return FunctionResult(code=self.code, instrument=instrument, data=hits,
                              sources=["sec_efts"],
                              metadata={"query": query, "forms": forms,
                                         "count": len(hits)})


def _fallback_hits(query: str, instrument: Instrument | None = None) -> list[dict[str, Any]]:
    status = "local_sec_search_model"
    if instrument is not None and instrument.asset_class.value != "EQUITY":
        status = f"not_applicable_for_{instrument.asset_class.value.lower()}"
    return [{
        "query": query,
        "form": None,
        "company": instrument.symbol if instrument else None,
        "filing_date": None,
        "snippet": "SEC full-text search provider unavailable for this request.",
        "url": None,
        "status": status,
    }]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
