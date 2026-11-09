"""EVTS — Corporate events for one symbol (Awareness corporate calendar and SEC filings).

Earnings, dividends, splits, IPO rows and SEC filings for a symbol inside a
window around today. Rows are split into ``upcoming`` (ascending) and
``recent`` (descending); ``rows`` is upcoming followed by recent.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.calendar._common import (
    aw_get,
    data_meta,
    iso_day,
    parse_bool,
    parse_csv,
    parse_int,
    provenance_metadata,
    unavailable_result,
    utc_today,
)

ALL_TYPES = ("earnings", "dividend", "split", "ipo", "filing")
_LABELS = {
    "earnings": "Earnings report",
    "dividend": "Dividend",
    "split": "Stock split",
    "ipo": "IPO",
    "filing": "SEC filing",
}
_FILING_WINDOW_MAX_DAYS = 90


def _event_row(item: dict[str, Any], symbol: str, event_type: str) -> dict[str, Any]:
    fields = item.get("fields") or {}
    label = _LABELS.get(event_type, event_type)
    if event_type == "filing" and fields.get("form"):
        label = f"SEC filing {fields.get('form')}"
    return {
        "date": str(item.get("date") or "")[:10],
        "datetime_utc": item.get("datetime_utc"),
        "type": event_type,
        "event": label,
        "symbol": item.get("symbol") or symbol,
        "company": item.get("company"),
        "time_of_day": item.get("time_of_day"),
        "status": item.get("status"),
        "details": fields,
        "sources": item.get("sources") or [],
    }


@FunctionRegistry.register
class EVTSFunction(BaseFunction):
    code = "EVTS"
    name = "Corporate Events"
    asset_classes = (AssetClass.EQUITY,)
    category = "news"
    description = (
        "Dated corporate events for one equity: earnings, dividends, splits, IPOs and SEC filings "
        "from the Awareness corporate calendar, split into upcoming and recent."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbol = str(params.get("symbol") or (instrument.symbol if instrument else "") or "").strip().upper()
        if not symbol:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={"status": "input_required", "reason": "EVTS needs a symbol.", "rows": [], "symbol": ""},
                sources=["no_live_source"],
                metadata={"fallback": True, "live": False, "data_mode": "provider_unavailable"},
            )
        if parse_bool(params.get("reference")):
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": "reference event template removed — data is live from Awareness",
                    "rows": [],
                    "symbol": symbol,
                },
                sources=["no_live_source"],
                metadata={"fallback": True, "live": False, "data_mode": "provider_unavailable"},
            )
        days_back = parse_int(params.get("days_back"), default=90, floor=0, ceiling=730)
        days_ahead = parse_int(params.get("days_ahead"), default=180, floor=0, ceiling=730)
        requested = [t for t in parse_csv(params.get("types"), upper=False) if t in ALL_TYPES] or list(ALL_TYPES)
        today = utc_today()
        window = {"from": iso_day(today - timedelta(days=days_back)), "to": iso_day(today + timedelta(days=days_ahead))}

        corporate_types = [t for t in requested if t != "filing"]
        calls: list[Any] = []
        if corporate_types:
            calls.append(aw_get(self, "/calendar/corporate", {**window, "types": ",".join(corporate_types), "symbols": symbol}))
        filings_requested = "filing" in requested
        if filings_requested and days_back > 0:
            calls.append(aw_get(self, "/filings", {"symbols": symbol, "days": min(days_back, _FILING_WINDOW_MAX_DAYS), "limit": 200}))
        answers = await asyncio.gather(*calls) if calls else []

        responses = []
        warnings: list[str] = []
        if filings_requested and days_back == 0:
            warnings.append("filings skipped: days_back=0 leaves no filing window")
        rows: list[dict[str, Any]] = []
        answered = 0
        index = 0
        if corporate_types:
            resp, error = answers[index]
            index += 1
            if resp is None:
                return unavailable_result("EVTS", instrument, error or "awareness returned no response",
                                          extra={"symbol": symbol, "rows": []})
            answered += 1
            responses.append(resp)
            for item in resp.data or []:
                if isinstance(item, dict) and item.get("type") in corporate_types:
                    rows.append(_event_row(item, symbol, str(item.get("type"))))
        if filings_requested and days_back > 0:
            resp, error = answers[index]
            if resp is None:
                warnings.append(f"filings: {error}")
            else:
                answered += 1
                responses.append(resp)
                for item in resp.data or []:
                    if isinstance(item, dict):
                        rows.append(_event_row(item, symbol, "filing"))
        if calls and answered == 0:
            return unavailable_result("EVTS", instrument, "awareness returned no response",
                                      extra={"symbol": symbol, "rows": []})

        today_text = today.isoformat()
        # A row without a usable date cannot be placed in upcoming or recent, so it gets its own list.
        dated = [r for r in rows if r["date"]]
        undated = [r for r in rows if not r["date"]]
        upcoming = sorted((r for r in dated if r["date"] >= today_text), key=lambda r: (r["date"], r["type"]))
        recent = sorted((r for r in dated if r["date"] < today_text), key=lambda r: (r["date"], r["type"]), reverse=True)
        ordered = upcoming + recent + undated
        status = "ok" if ordered else "empty"
        sources = [f"awareness:{area}" for area in (["corporate"] if corporate_types else []) + (["filings"] if filings_requested and days_back > 0 else [])]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": status,
                "symbol": symbol,
                "rows": ordered,
                "upcoming": upcoming,
                "recent": recent,
                "undated": undated,
                "event_count": len(ordered),
                "filters": {**window, "days_back": days_back, "days_ahead": days_ahead, "types": requested},
                "meta": data_meta(responses),
                "methodology": (
                    "EVTS lists earnings, dividend, split, IPO and SEC filing rows for the symbol from the "
                    "Awareness corporate calendar and filings index. Upcoming rows (date today or later) sort "
                    "ascending; recent rows sort descending; rows without a date are listed separately as undated "
                    "and never placed in recent. Nothing is estimated."
                ),
                "reason": None if ordered else f"No {', '.join(requested)} events for {symbol} in this window.",
            },
            sources=sources,
            warnings=warnings,
            metadata=provenance_metadata(responses, provider_errors=warnings, extra={"symbol": symbol}),
        )
