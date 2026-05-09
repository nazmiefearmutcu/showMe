"""PIB — Public Information Book (recent SEC filings + AI summary stub)."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import frame_rows


@FunctionRegistry.register
class PIBFunction(BaseFunction):
    code = "PIB"
    name = "Public Information Book"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        filings = pd.DataFrame()
        try:
            if self.deps.sec_edgar:
                filings = await asyncio.wait_for(
                    self.deps.sec_edgar.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=float(params.get("timeout", 8)),
                )
                if isinstance(filings, pd.DataFrame) and not filings.empty:
                    filings = filings.head(50)
        except Exception as e:
            warnings.append(f"sec_edgar: {e}")
        rows = _pib_rows(instrument.symbol, filings)
        data = {
            "status": "ok" if rows else "provider_unavailable",
            "rows": rows,
            "sections": [
                {"section": "profile", "status": "available_via_DES", "function": "DES"},
                {"section": "financials", "status": "available_via_FA", "function": "FA"},
                {"section": "filings", "status": "included", "count": len(rows)},
                {"section": "holders", "status": "available_via_HDS", "function": "HDS"},
                {"section": "news", "status": "available_via_CN_TOP", "function": "CN/TOP"},
            ],
            "filings": rows,
            "methodology": "PIB is a public information book index: it combines company profile, financials, filings, holders, news, and events as sections, with filing rows used as evidence links.",
            "field_dictionary": {
                "section": "Public-info-book section.",
                "form": "SEC form type.",
                "filingDate": "SEC filing date.",
                "url": "Primary SEC document or filing detail link when available.",
            },
        }
        sources = ["sec_edgar"]
        if not isinstance(filings, pd.DataFrame) or filings.empty:
            data = {
                "status": "provider_unavailable",
                "rows": [{
                    "symbol": instrument.symbol,
                    "section": "filing",
                    "form": None,
                    "filingDate": None,
                    "source_mode": "sec_edgar_unavailable",
                }],
                "sections": [
                    {"section": "profile", "status": "available_via_DES", "function": "DES"},
                    {"section": "financials", "status": "available_via_FA", "function": "FA"},
                    {"section": "filings", "status": "provider_unavailable", "function": "PIB"},
                ],
                "reason": "SEC filing feed returned no rows.",
                "methodology": "PIB requires public filings plus linked profile/financial/news sections.",
                "next_actions": ["Retry SEC EDGAR or open DES/FA/CN for the linked public-info sections."],
            }
            sources = ["pib_model"]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=sources,
            metadata={"note": "AI summary via LLM router (Phase 7)", "provider_errors": warnings},
        )


def _pib_rows(symbol: str, filings: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for item in frame_rows(filings, limit=50):
        rows.append({
            "symbol": symbol,
            "section": "filing",
            "form": item.get("form"),
            "filingDate": item.get("filingDate"),
            "reportDate": item.get("reportDate"),
            "accession": item.get("accessionNumber"),
            "url": item.get("primaryDocument"),
            "source_mode": "sec_edgar_filing_metadata",
        })
    return rows
