"""FORM4 — SEC Form 4 (insider transactions) calendar."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import date_label, finite, frame_rows


@FunctionRegistry.register
class FORM4Function(BaseFunction):
    code = "FORM4"
    name = "Insider Transactions"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Recent SEC Form 4 (insider) filings for the given ticker."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (instrument.symbol if instrument else
               params.get("symbol") or "").upper()
        if not sym:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["symbol required"])
        yfin_rows: list[dict[str, Any]] = []
        try:
            if self.deps.yfinance:
                holdings = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.HOLDINGS, instrument=instrument)),
                    timeout=float(params.get("yfinance_timeout", 5)),
                )
                yfin_rows = _insider_rows_from_yfinance(sym, holdings)
        except Exception:
            yfin_rows = []
        if not self.deps.sec_edgar:
            data = _fallback_form4(sym)
            if yfin_rows:
                data["rows"] = yfin_rows
                data["filings"] = yfin_rows
                data["status"] = "ok"
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=data,
                                  sources=["yfinance"] if yfin_rows else ["form4_model"])
        try:
            rows = await asyncio.wait_for(
                self.deps.sec_edgar.form4_filings(sym, limit=int(params.get("limit", 40))),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception as e:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_fallback_form4(sym),
                                  sources=["form4_model"],
                                  metadata={"provider_errors": [f"sec_edgar: {e}"]})
        # Aggregate counts
        by_month: dict[str, int] = {}
        for r in rows:
            d = (r.get("filingDate") or "")[:7]   # YYYY-MM
            if d:
                by_month[d] = by_month.get(d, 0) + 1
        parsed_rows = yfin_rows or _filing_rows(sym, rows)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok" if parsed_rows else "provider_unavailable",
                "symbol": sym,
                "n": len(parsed_rows),
                "rows": parsed_rows,
                "filings": rows,
                "by_month": [
                    {"month": k, "count": v}
                    for k, v in sorted(by_month.items(), reverse=True)
                ],
                "methodology": "FORM4 prefers parsed insider-transaction tables from Yahoo holdings data and keeps SEC Form 4 filing links as evidence. If XML transaction parsing is unavailable, rows are labelled as filing metadata instead of pretending to be parsed trades.",
                "field_dictionary": {
                    "insider": "Reporting owner or insider name.",
                    "transaction": "Transaction description/code when parsed.",
                    "shares": "Shares transacted or reported.",
                    "value": "Reported transaction value when available.",
                    "filing_url": "SEC primary document URL or provider link.",
                },
            },
            sources=["yfinance", "sec_edgar"] if yfin_rows else ["sec_edgar"],
        )


def _fallback_form4(symbol: str) -> dict[str, Any]:
    return {
        "status": "provider_unavailable",
        "symbol": symbol,
        "n": 0,
        "rows": [{"filingDate": None, "insider": None, "transaction": None, "shares": None, "value": None, "status": "provider_unavailable"}],
        "filings": [{"filingDate": None, "reportingOwner": None, "status": "provider_unavailable"}],
        "by_month": [],
        "methodology": "SEC Form 4 or provider insider transaction data is required.",
    }


def _insider_rows_from_yfinance(symbol: str, holdings: Any) -> list[dict[str, Any]]:
    frame = (holdings or {}).get("insider_transactions") if isinstance(holdings, dict) else None
    rows: list[dict[str, Any]] = []
    for item in frame_rows(frame, limit=40):
        shares = finite(item.get("Shares") or item.get("shares"))
        value = finite(item.get("Value") or item.get("value"))
        rows.append({
            "symbol": symbol,
            "filingDate": date_label(item.get("Start Date") or item.get("startDate") or item.get("Date") or item.get("index")),
            "insider": item.get("Insider") or item.get("insider") or item.get("Person"),
            "position": item.get("Position") or item.get("position"),
            "transaction": item.get("Transaction") or item.get("transaction"),
            "shares": shares,
            "value": value,
            "ownership": item.get("Ownership") or item.get("ownership"),
            "source_mode": "yfinance_insider_transactions",
        })
    return [r for r in rows if r.get("insider") or r.get("transaction") or r.get("shares")]


def _filing_rows(symbol: str, filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in filings[:40]:
        rows.append({
            "symbol": symbol,
            "filingDate": item.get("filingDate"),
            "insider": item.get("reportingOwner") or item.get("ownerName"),
            "transaction": "Form 4 filing document",
            "shares": None,
            "value": None,
            "filing_url": item.get("primaryDocument") or item.get("url"),
            "accession": item.get("accessionNumber"),
            "source_mode": "sec_form4_filing_metadata",
        })
    return rows
