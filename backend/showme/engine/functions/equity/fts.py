"""FTS — SEC EDGAR Full-Text Search.

Plan §26.2 bonus: cross-issuer text search across 10-K, 10-Q, 8-K, S-1 ...
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class FTSFunction(BaseFunction):
    code = "FTS"
    name = "SEC Full-Text Search"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Search SEC EDGAR filings by free text + form type + date range."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sec = getattr(self.deps, "sec_efts", None)
        base_query = params.get("query") or params.get("search") or "risk factors"
        query = f"{instrument.symbol} {base_query}".strip() if instrument and instrument.symbol.upper() not in str(base_query).upper() else str(base_query)
        if not query:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=["empty query"])
        live = _truthy(params.get("live_search") or params.get("live_filings") or params.get("live"))
        if not live or sec is None or (instrument and instrument.asset_class.value != "EQUITY"):
            reason = (
                "SEC EDGAR full-text search adapter is not configured for this asset class."
                if instrument and instrument.asset_class.value != "EQUITY"
                else "SEC EDGAR full-text search is offline; enable live=true with a configured sec_efts adapter."
            )
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={"status": "provider_unavailable", "rows": [], "query": query,
                      "reason": reason,
                      "next_actions": [
                          "Set live_search=true (or live=true) once the SEC EDGAR adapter is configured.",
                          "Verify the symbol is an EQUITY before requesting full-text search.",
                      ],
                      "methodology": "FTS searches SEC full-text filings by query, optional form list, and date range. Query is symbol-scoped when a symbol is open.",
                      "field_dictionary": {"score": "Provider relevance score when available.", "snippet": "Matched filing text excerpt.", "form": "SEC form type."}},
                sources=["no_live_source"],
                metadata={"query": query, "live": False},
            )
        forms = _parse_forms(params.get("forms")) or None
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
                                  data={"status": "provider_unavailable", "rows": [], "query": query,
                                        "reason": f"sec_efts adapter raised: {e}",
                                        "next_actions": ["Retry once the SEC EDGAR provider recovers.", "Open Raw payload to inspect the provider error."],
                                        "methodology": "FTS searches SEC full-text filings by query, optional form list, and date range. Provider errors are shown instead of unrelated hits.",
                                        "field_dictionary": {"score": "Provider relevance score when available.", "snippet": "Matched filing text excerpt.", "form": "SEC form type."}},
                                  sources=["no_live_source"],
                                  metadata={"provider_errors": [f"sec_efts: {e}"]})
        limit = max(1, min(int(params.get("limit", 50) or 50), 100))
        rows = _normalise_hits(hits, instrument)[:limit]
        status = "ok" if rows else "empty"
        return FunctionResult(code=self.code, instrument=instrument, data={
                              "status": status,
                              "rows": rows,
                              "query": query,
                              "forms": forms,
                              "methodology": "FTS searches SEC full-text filings by query, optional form list, and date range. The visible rows include company, form, filing date, accession/link, score, and snippet evidence.",
                              "field_dictionary": {"score": "Provider relevance score when available.", "snippet": "Matched filing text excerpt.", "form": "SEC form type."}},
                              sources=["sec_efts"],
                              metadata={"query": query, "forms": forms,
                                         "count": len(rows)})


def _normalise_hits(hits: Any, instrument: Instrument | None) -> list[dict[str, Any]]:
    raw_rows = hits if isinstance(hits, list) else []
    rows: list[dict[str, Any]] = []
    symbol = instrument.symbol.upper() if instrument else None
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        company = item.get("company") or item.get("companyName") or item.get("entity")
        snippet = item.get("snippet") or item.get("snippets") or item.get("description")
        if isinstance(snippet, list):
            snippet = " | ".join(str(s) for s in snippet[:2])
        row = {
            "symbol": symbol,
            "company": company,
            "form": item.get("form") or item.get("formType"),
            "filing_date": item.get("filing_date") or item.get("filedAt") or item.get("filingDate"),
            "accession": item.get("accession") or item.get("adsh") or item.get("accessionNumber"),
            "url": item.get("url") or item.get("filingUrl") or item.get("linkToFilingDetails"),
            "score": item.get("score") or item.get("rank") or item.get("relevance"),
            "snippet": snippet,
            "source_mode": "sec_efts",
        }
        if symbol and (symbol not in str(company or "").upper()) and (symbol not in str(snippet or "").upper()):
            row["symbol_match"] = "query_scoped_not_direct_snippet"
        rows.append(row)
    return rows


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_forms(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [p.strip().upper() for p in raw.split(",") if p.strip()]
    if isinstance(raw, (list, tuple, set)):
        return [str(p).strip().upper() for p in raw if str(p).strip()]
    return []
