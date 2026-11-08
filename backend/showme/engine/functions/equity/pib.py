"""PIB — Public Information Book (recent SEC filings from EDGAR).

Filters (months, form_types) are applied server-side to the EDGAR filing list
before the row cap. Each row links to the primary EDGAR document when the CIK
is known. The AI summary is not implemented: include_summary reports
summary_status "not_implemented" instead of attaching text.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import frame_rows

ROW_LIMIT = 50
DEFAULT_MONTHS = 6


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
        months = _months(params.get("months"))
        form_types = _form_types(params.get("form_types"))
        include_summary = _truthy(params.get("include_summary"))
        filings = pd.DataFrame()
        cik: str | None = None
        try:
            if self.deps.sec_edgar:
                timeout = float(params.get("timeout", 8))
                filings = await asyncio.wait_for(
                    self.deps.sec_edgar.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=timeout,
                )
                if isinstance(filings, pd.DataFrame) and not filings.empty:
                    cik = await asyncio.wait_for(
                        self.deps.sec_edgar.cik_for(instrument.symbol), timeout=timeout,
                    )
        except Exception as e:
            warnings.append(f"sec_edgar: {e}")
        has_feed = isinstance(filings, pd.DataFrame) and not filings.empty
        matched = _filter_filings(filings, months, form_types) if has_feed else pd.DataFrame()
        rows = _pib_rows(instrument.symbol, matched, cik)

        summary: Any = None
        summary_status = "not_requested"
        if include_summary:
            summary_status = "not_implemented"
            warnings.append(
                "include_summary requested, but the AI summary is not implemented; no summary is attached"
            )

        if rows:
            data: dict[str, Any] = {
                "status": "ok",
                "rows": rows,
                "sections": [
                    {"section": "profile", "status": "available_via_DES", "function": "DES"},
                    {"section": "financials", "status": "available_via_FA", "function": "FA"},
                    {"section": "filings", "status": "included", "count": len(rows)},
                    {"section": "holders", "status": "available_via_HDS", "function": "HDS"},
                    {"section": "news", "status": "available_via_CN_TOP", "function": "CN/TOP"},
                ],
                "filings": rows,
                "window": {"months": months, "form_types": form_types or "all"},
                "summary": summary,
                "summary_status": summary_status,
                "methodology": (
                    f"PIB lists the issuer's SEC EDGAR filings filed in the last {months} month(s)"
                    f"{' restricted to ' + ', '.join(form_types) if form_types else ''}, newest first, "
                    f"capped at {ROW_LIMIT} rows. Each row is linked to its primary EDGAR document."
                ),
                "field_dictionary": {
                    "section": "Public-info-book section.",
                    "form": "SEC form type.",
                    "filingDate": "SEC filing date.",
                    "url": "Absolute EDGAR primary-document URL (built from CIK, accession and document name).",
                },
            }
            sources = ["sec_edgar"]
        elif has_feed:
            data = {
                "status": "empty",
                "rows": [],
                "filings": [],
                "sections": [
                    {"section": "filings", "status": "empty", "function": "PIB"},
                ],
                "window": {"months": months, "form_types": form_types or "all"},
                "summary": summary,
                "summary_status": summary_status,
                "reason": (
                    f"No SEC filings for {instrument.symbol} in the last {months} month(s)"
                    f"{' matching ' + ', '.join(form_types) if form_types else ''}."
                ),
                "next_actions": ["Widen the months window or clear the form filter."],
            }
            sources = ["sec_edgar"]
        else:
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
                "summary": summary,
                "summary_status": summary_status,
                "methodology": "PIB requires public filings plus linked profile/financial/news sections.",
                "next_actions": ["Retry SEC EDGAR or open DES/FA/CN for the linked public-info sections."],
            }
            sources = ["pib_model"]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=sources,
            warnings=warnings,
            metadata={"provider_errors": warnings},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _months(value: Any) -> int:
    try:
        months = int(value) if value not in (None, "") else DEFAULT_MONTHS
    except (TypeError, ValueError):
        months = DEFAULT_MONTHS
    return min(max(months, 1), 24)


def _form_types(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = [value]
    return [str(v).strip().upper() for v in value if str(v).strip()]


def _filter_filings(frame: pd.DataFrame, months: int, form_types: list[str]) -> pd.DataFrame:
    if "filingDate" not in frame.columns:
        return pd.DataFrame()
    dates = pd.to_datetime(frame["filingDate"], errors="coerce")
    cutoff = pd.Timestamp(datetime.now(timezone.utc).date()) - pd.DateOffset(months=months)
    mask = dates >= cutoff
    if form_types and "form" in frame.columns:
        mask &= frame["form"].astype(str).str.upper().isin(form_types)
    out = frame.loc[mask.fillna(False)].copy()
    out["_filed"] = dates[out.index]
    return out.sort_values("_filed", ascending=False).drop(columns="_filed").reset_index(drop=True)


def _edgar_document_url(cik: str | None, accession: Any, document: Any) -> str | None:
    if not cik or not accession or not document:
        return None
    try:
        cik_int = int(str(cik).strip())
    except ValueError:
        return None
    acc = str(accession).replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/{document}"


def _pib_rows(symbol: str, filings: pd.DataFrame, cik: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for item in frame_rows(filings, limit=ROW_LIMIT):
        rows.append({
            "symbol": symbol,
            "section": "filing",
            "form": item.get("form"),
            "filingDate": item.get("filingDate"),
            "reportDate": item.get("reportDate"),
            "accession": item.get("accessionNumber"),
            "url": _edgar_document_url(cik, item.get("accessionNumber"), item.get("primaryDocument")),
            "source_mode": "sec_edgar_filing_metadata",
        })
    return rows
