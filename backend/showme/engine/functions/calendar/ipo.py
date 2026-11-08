"""IPO — IPO calendar: priced, upcoming, filed and withdrawn offerings (Awareness)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.calendar._common import (
    aw_get,
    data_meta,
    iso_day,
    parse_int,
    provenance_metadata,
    unavailable_result,
    utc_today,
)

SECTIONS = ("priced", "upcoming", "filed", "withdrawn")
_REGISTRATION_PREFIXES = ("S-1", "F-1")
_WITHDRAWAL_FORMS = ("RW", "RW/A", "RW-A")
_STATUS_TO_SECTION = {
    "priced": "priced",
    "withdrawn": "withdrawn",
    "upcoming": "upcoming",
    "scheduled": "upcoming",
    "expected": "upcoming",
    "filed": "filed",
}


def _section_for_ipo(item: dict[str, Any]) -> str:
    return _STATUS_TO_SECTION.get(str(item.get("status") or "").strip().lower(), "upcoming")


def _section_for_filing(item: dict[str, Any]) -> str | None:
    form = str((item.get("fields") or {}).get("form") or "").strip().upper()
    if form in _WITHDRAWAL_FORMS:
        return "withdrawn"
    if form.startswith(_REGISTRATION_PREFIXES):
        return "filed"
    return None


def _row(item: dict[str, Any], section: str) -> dict[str, Any]:
    fields = item.get("fields") or {}
    return {
        "date": item.get("date"),
        "symbol": item.get("symbol"),
        "company": item.get("company"),
        "exchange": item.get("exchange"),
        "price": fields.get("price"),
        "price_range": fields.get("price_range") or fields.get("range"),
        "shares_offered": fields.get("shares_offered") or fields.get("shares"),
        "deal_size_usd": fields.get("deal_size_usd") or fields.get("deal_size"),
        "status": section,
        "form": fields.get("form"),
        "sources": item.get("sources") or [],
    }


@FunctionRegistry.register
class IPOFunction(BaseFunction):
    code = "IPO"
    name = "IPO Calendar"
    asset_classes = ()
    category = "macro"
    description = (
        "IPO calendar: recently priced, upcoming, newly filed (S-1/F-1) and withdrawn offerings "
        "from the Awareness corporate calendar and SEC filings."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        today = utc_today()
        days_back = parse_int(params.get("days_back"), default=30, floor=0, ceiling=365)
        days_ahead = parse_int(params.get("days_ahead"), default=60, floor=0, ceiling=365)
        start = today - timedelta(days=days_back)
        end = today + timedelta(days=days_ahead)
        wanted = str(params.get("status") or "").strip().lower()
        if wanted and wanted not in SECTIONS:
            wanted = ""

        window = {"from": iso_day(start), "to": iso_day(end)}
        ipo_call, filing_call = await asyncio.gather(
            aw_get(self, "/calendar/corporate", {**window, "types": "ipo"}),
            aw_get(self, "/calendar/corporate", {**window, "types": "filing"}),
        )
        ipo_resp, ipo_error = ipo_call
        filing_resp, filing_error = filing_call
        if ipo_resp is None and filing_resp is None:
            return unavailable_result("IPO", None, ipo_error or filing_error or "awareness returned no response")

        sections: dict[str, list[dict[str, Any]]] = {name: [] for name in SECTIONS}
        warnings: list[str] = []
        for label, error in (("ipo", ipo_error), ("filing", filing_error)):
            if error is not None:
                warnings.append(f"{label}: {error}")
        responses = [resp for resp in (ipo_resp, filing_resp) if resp is not None]
        for item in (ipo_resp.data if ipo_resp is not None else []) or []:
            if isinstance(item, dict):
                section = _section_for_ipo(item)
                sections[section].append(_row(item, section))
        for item in (filing_resp.data if filing_resp is not None else []) or []:
            if isinstance(item, dict):
                section = _section_for_filing(item)
                if section is not None:
                    sections[section].append(_row(item, section))

        for name in SECTIONS:
            sections[name].sort(key=lambda row: str(row.get("date") or ""), reverse=name != "upcoming")
        if wanted:
            sections = {name: (rows if name == wanted else []) for name, rows in sections.items()}
        total = sum(len(rows) for rows in sections.values())

        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok" if total else "empty",
                "sections": sections,
                "counts": {name: len(rows) for name, rows in sections.items()},
                "count": total,
                "filters": {"days_back": days_back, "days_ahead": days_ahead,
                            "from": window["from"], "to": window["to"], "status": wanted or None},
                "meta": data_meta(responses),
                "methodology": (
                    "IPO groups Awareness IPO calendar rows by their status (priced, upcoming, withdrawn) and "
                    "SEC registration filings (S-1 and F-1 variants) as filed; RW filings count as withdrawn. "
                    "Rows are never estimated. Price and deal fields are shown only when the provider states them."
                ),
                "field_dictionary": {
                    "price": "Offer price per share when priced.",
                    "price_range": "Marketed price range when the filing states one.",
                    "shares_offered": "Shares offered in the deal.",
                    "deal_size_usd": "Gross deal size in USD when reported.",
                    "form": "SEC form behind a filed or withdrawn row.",
                },
                "next_actions": [] if total else ["Widen days_back or days_ahead."],
            },
            sources=["awareness:corporate"],
            warnings=warnings,
            metadata=provenance_metadata(responses, provider_errors=warnings),
        )
