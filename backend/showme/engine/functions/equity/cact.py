"""CACT — Corporate actions for one symbol.

Merges dividends and splits (Awareness corporate calendar, plus the live Yahoo
event series as a supplement) with material 8-K filings (Awareness filings).
Duplicates across providers are removed on (action type, date, value).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.calendar._common import (
    aw_get,
    data_meta,
    iso_day,
    parse_float,
    parse_int,
    provenance_metadata,
    unavailable_result,
    utc_today,
)
from showme.engine.functions.equity._common import FIELD_DICTIONARIES, series_rows

_FILINGS_MAX_DAYS = 90
_METHODOLOGY = (
    "CACT merges dividends and splits from the Awareness corporate calendar (Yahoo event series as a "
    "supplement) with 8-K filings from the Awareness SEC index. Rows carry their source; duplicates across "
    "providers are dropped on (action type, date, value). Dividend and split values are as published."
)


def _corporate_row(item: dict[str, Any]) -> dict[str, Any] | None:
    fields = item.get("fields") or {}
    kind = item.get("type")
    if kind == "dividend":
        value = parse_float(fields.get("amount"))
        unit = "cash/share"
    elif kind == "split":
        # "1:30" means one old share becomes thirty new: value is new shares per old share.
        to_units = parse_float(fields.get("ratio_to"))
        from_units = parse_float(fields.get("ratio_from"))
        value = (to_units / from_units) if to_units and from_units else None
        unit = str(fields.get("ratio") or "split ratio")
    else:
        return None
    if value is None:
        return None
    return {
        "action_type": kind,
        "event_date": str(item.get("date") or "")[:10],
        "value": value,
        "unit": unit,
        "ratio": fields.get("ratio") if kind == "split" else None,
        "source": "awareness:corporate",
    }


def _yahoo_rows(events: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in series_rows(events.get("dividends"), value_key="value", limit=40):
        value = parse_float(row.get("value"))
        if value:
            rows.append({"action_type": "dividend", "event_date": row.get("date"), "value": value,
                         "unit": "cash/share", "source": "yfinance"})
    for row in series_rows(events.get("splits"), value_key="value", limit=20):
        value = parse_float(row.get("value"))
        if value:
            rows.append({"action_type": "split", "event_date": row.get("date"), "value": value,
                         "unit": "split ratio", "source": "yfinance"})
    return rows


def _filing_row(item: dict[str, Any]) -> dict[str, Any]:
    fields = item.get("fields") or {}
    return {
        "action_type": "8-K",
        "event_date": str(item.get("date") or "")[:10],
        "value": None,
        "unit": None,
        "form": fields.get("form"),
        "accession": fields.get("accession"),
        "url": fields.get("url"),
        "source": "awareness:filings",
    }


def _dedupe(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        value = row.get("value")
        key = (row.get("action_type"), row.get("event_date"),
               round(value, 4) if isinstance(value, float) else value)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        out.append(row)
    return out, dropped


@FunctionRegistry.register
class CACTFunction(BaseFunction):
    code = "CACT"
    name = "Corporate Actions"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"
    description = (
        "Dividends, splits and material 8-K filings for one equity, merged from the Awareness calendar and "
        "SEC index with cross-provider duplicates removed."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbol = str(params.get("symbol") or (instrument.symbol if instrument else "") or "").strip().upper()
        if not symbol:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={"status": "input_required", "reason": "CACT needs a symbol.", "rows": []},
                sources=["no_live_source"],
                metadata={"fallback": True, "live": False, "data_mode": "provider_unavailable"},
            )
        if instrument is None:
            instrument = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
        days_back = parse_int(params.get("days_back"), default=365, floor=0, ceiling=3650)
        days_ahead = parse_int(params.get("days_ahead"), default=90, floor=0, ceiling=365)
        today = utc_today()
        window = {"from": iso_day(today - timedelta(days=days_back)), "to": iso_day(today + timedelta(days=days_ahead))}

        corporate_call = aw_get(self, "/calendar/corporate", {**window, "types": "dividend,split", "symbols": symbol})
        filings_call = aw_get(self, "/filings", {
            "symbols": symbol,
            "forms": "8-K",
            "days": min(max(days_back, 1), _FILINGS_MAX_DAYS),
            "limit": 200,
        })
        (corporate, corporate_error), (filings, filings_error) = await asyncio.gather(corporate_call, filings_call)
        if corporate is None and filings is None:
            return unavailable_result(self.code, instrument, corporate_error or filings_error or "awareness returned no response",
                                      extra={"symbol": symbol})

        warnings: list[str] = []
        if corporate_error:
            warnings.append(f"corporate: {corporate_error}")
        if filings_error:
            warnings.append(f"filings: {filings_error}")

        rows: list[dict[str, Any]] = []
        responses = []
        if corporate is not None:
            responses.append(corporate)
            rows.extend(r for r in (_corporate_row(i) for i in corporate.data or [] if isinstance(i, dict)) if r)
        if filings is not None:
            responses.append(filings)
            for item in filings.data or []:
                if isinstance(item, dict) and str(((item.get("fields") or {}).get("form")) or "").startswith("8-K"):
                    rows.append(_filing_row(item))

        yahoo_error: str | None = None
        if self.deps.yfinance:
            try:
                events = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.EVENTS, instrument=instrument)),
                    timeout=max(1.0, min(float(params.get("yfinance_timeout", 3)), 5.0)),
                )
                rows.extend(_yahoo_rows(events or {}))
            except Exception as exc:  # noqa: BLE001 - supplement only; surfaced as a warning
                yahoo_error = str(exc) or type(exc).__name__
                warnings.append(f"yfinance: {yahoo_error}")

        in_window = [r for r in rows if r.get("event_date") and window["from"] <= str(r["event_date"])[:10] <= window["to"]]
        unique, dropped = _dedupe(in_window)
        unique.sort(key=lambda r: str(r.get("event_date") or ""), reverse=True)
        unique = unique[:200]
        status = "ok" if unique else "empty"
        sources = []
        if corporate is not None:
            sources.append("awareness:corporate")
        if filings is not None:
            sources.append("awareness:filings")
        if yahoo_error is None and self.deps.yfinance and any(r.get("source") == "yfinance" for r in unique):
            sources.append("yfinance")
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": status,
                "symbol": symbol,
                "rows": unique,
                "timeline": unique,
                "counts": {
                    "dividend": sum(1 for r in unique if r["action_type"] == "dividend"),
                    "split": sum(1 for r in unique if r["action_type"] == "split"),
                    "8-K": sum(1 for r in unique if r["action_type"] == "8-K"),
                },
                "duplicates_dropped": dropped,
                "meta": data_meta(responses),
                "window": window,
                "methodology": _METHODOLOGY,
                "field_dictionary": FIELD_DICTIONARIES["corporate_actions"],
                "reason": None if unique else f"No dividend, split or 8-K rows for {symbol} in this window.",
            },
            sources=sources or ["no_live_source"],
            warnings=warnings,
            metadata=provenance_metadata(responses, provider_errors=warnings, extra={"symbol": symbol}),
        )
