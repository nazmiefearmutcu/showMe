"""CACT — Corporate Actions (8-K, splits, M&A, name change)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class CACTFunction(BaseFunction):
    code = "CACT"
    name = "Corporate Actions"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        sec_filings = None
        events_8k: list[dict[str, Any]] = []
        try:
            if self.deps.sec_edgar:
                sec_timeout = max(1.0, min(float(params.get("sec_timeout", 3)), 5.0))
                sec_filings = await asyncio.wait_for(
                    self.deps.sec_edgar.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=sec_timeout,
                )
                # Categorize last N 8-K filings by Item code
                if hasattr(sec_filings, "to_dict") and "form" in sec_filings.columns:
                    max_documents = int(params.get("max_documents", 3))
                    eight_k_rows = sec_filings[
                        sec_filings["form"].astype(str).str.startswith("8-K")
                    ].head(max_documents)
                    for _, row in eight_k_rows.iterrows():
                        events_8k.append({
                            "category": "8-k",
                            "form": row.get("form"),
                            "filing_date": row.get("filingDate"),
                            "report_date": row.get("reportDate"),
                            "accession": row.get("accessionNumber"),
                            "document": row.get("primaryDocument"),
                        })
                    if params.get("fetch_documents") or params.get("deep"):
                        cik = await asyncio.wait_for(
                            self.deps.sec_edgar.cik_for(instrument.symbol),
                            timeout=sec_timeout,
                        )
                        if cik:
                            from src.core.sec_taxonomy import categorize_8k_text
                            for _, row in eight_k_rows.iterrows():
                                try:
                                    # Best-effort deep mode: fetch primary document text.
                                    doc = row.get("primaryDocument")
                                    acc = (row.get("accessionNumber") or "").replace("-", "")
                                    if not doc or not acc:
                                        continue
                                    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
                                    async with __import__("httpx").AsyncClient(
                                        timeout=sec_timeout,
                                        headers={"User-Agent": "ShowMe dev showme@example.com"},
                                    ) as cli:
                                        r = await cli.get(url)
                                        if r.status_code == 200:
                                            text = __import__("re").sub(r"<[^>]+>", " ", r.text)
                                            for cat in categorize_8k_text(text)[:5]:
                                                cat["filing_date"] = row.get("filingDate")
                                                events_8k.append(cat)
                                except Exception:
                                    continue
        except Exception as e:
            warnings.append(f"sec_edgar: {e}")
        yfin = {}
        try:
            if self.deps.yfinance:
                yfin = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=max(1.0, min(float(params.get("yfinance_timeout", 3)), 5.0)),
                )
        except Exception as e:
            # Corporate actions still has SEC filings when Yahoo events are slow
            # or throttled; keep the pane usable instead of timing out.
            yfin = {"status": "unavailable", "reason": str(e) or type(e).__name__}
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "sec_filings": sec_filings if sec_filings is not None else [],
                "events_8k": events_8k or [{
                    "category": "corporate_actions",
                    "symbol": instrument.symbol,
                    "status": "provider_unavailable",
                }],
                "yfinance_events": yfin,
            },
            sources=["sec_edgar", "yfinance"] if not warnings else ["corporate_actions_model", "yfinance"],
            metadata={"provider_errors": warnings} if warnings else {},
        )
