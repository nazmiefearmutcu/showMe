"""DVD — Dividends for one symbol.

Upcoming dividend events come from the Awareness corporate calendar. Dividend
history comes from the live Yahoo event series. The fabricated template default
has been removed: when neither source has rows the result is ``empty``.
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
    parse_bool,
    parse_float,
    provenance_metadata,
    unavailable_result,
    utc_today,
)
from showme.engine.functions.equity._common import series_rows

_UPCOMING_DAYS = 365
_FREQUENCY = {1: "annual", 2: "semi-annual", 4: "quarterly", 12: "monthly"}
_METHODOLOGY = (
    "DVD lists upcoming cash dividends from the Awareness corporate calendar (ex-date, record, pay and "
    "announcement dates, amount per share and annualised amount as published) and the dividend history "
    "from the live Yahoo event series. summary.annual_amount sums history over the last 12 months; "
    "frequency_guess counts those payments. Nothing is estimated; empty sources stay empty."
)
_FIELD_DICTIONARY = {
    "date": "Ex-dividend date.",
    "amount": "Cash dividend per share.",
    "annual_amount": "Annualised amount as published by the calendar.",
    "record_date": "Record date.",
    "pay_date": "Payment date.",
    "source": "Provider the row came from.",
}


def _history_rows(events: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    rows = []
    for row in series_rows(events.get("dividends"), value_key="amount", limit=80):
        if row.get("amount"):
            rows.append({"symbol": symbol, "date": row.get("date"), "amount": row.get("amount"), "source": "yfinance"})
    rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return rows


def _upcoming_row(item: dict[str, Any]) -> dict[str, Any]:
    fields = item.get("fields") or {}
    return {
        "date": item.get("date"),
        "symbol": item.get("symbol"),
        "amount": fields.get("amount"),
        "annual_amount": fields.get("annual_amount"),
        "record_date": fields.get("record_date"),
        "pay_date": fields.get("pay_date"),
        "announcement_date": fields.get("announcement_date"),
        "status": item.get("status"),
        "source": "awareness:corporate",
    }


def _summary(history: list[dict[str, Any]], upcoming: list[dict[str, Any]], today_text: str) -> dict[str, Any]:
    last_year = [r for r in history if str(r.get("date") or "")[:10] > (utc_today() - timedelta(days=365)).isoformat()]
    annual = round(sum(parse_float(r.get("amount")) or 0.0 for r in last_year), 6) if last_year else None
    if annual is None and upcoming:
        annual = parse_float(upcoming[0].get("annual_amount"))
    last = history[0] if history else None
    frequency = _FREQUENCY.get(len(last_year), "irregular") if last_year else None
    return {
        "annual_amount": annual,
        "last_amount": parse_float(last.get("amount")) if last else None,
        "last_ex_date": str(last.get("date") or "")[:10] if last else None,
        "next_ex_date": next((r["date"] for r in upcoming if str(r.get("date") or "")[:10] >= today_text), None),
        "frequency_guess": frequency,
        "payments_last_12m": len(last_year),
    }


@FunctionRegistry.register
class DVDFunction(BaseFunction):
    code = "DVD"
    name = "Dividends"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"
    description = (
        "Upcoming cash dividends with record, pay and annualised amounts from the Awareness calendar, "
        "plus the live dividend history and a summary of payment frequency."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbol = str(params.get("symbol") or (instrument.symbol if instrument else "") or "").strip().upper()
        if not symbol:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={"status": "input_required", "reason": "DVD needs a symbol.", "rows": [], "history": []},
                sources=["no_live_source"],
                metadata={"fallback": True, "live": False, "data_mode": "provider_unavailable"},
            )
        if instrument is None:
            instrument = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
        # ``live`` / ``live_dividends`` are the pane's legacy toggle for the live history; the
        # template ("model") mode they used to select is gone, so off simply means no history.
        legacy_live = params.get("live_dividends", params.get("live"))
        want_history = parse_bool(params.get("history"), default=parse_bool(legacy_live, default=True))
        today = utc_today()
        window = {"from": iso_day(today), "to": iso_day(today + timedelta(days=_UPCOMING_DAYS))}

        corporate, corporate_error = await aw_get(
            self, "/calendar/corporate", {**window, "types": "dividend", "symbols": symbol}
        )
        warnings: list[str] = []
        history_events: dict[str, Any] = {}
        if want_history and self.deps.yfinance:
            try:
                history_events = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.EVENTS,
                        instrument=instrument,
                        extra={"timeout": float(params.get("provider_timeout", 8))},
                    )),
                    timeout=float(params.get("timeout", 10)),
                )
            except Exception as exc:  # noqa: BLE001 - history is a supplement; error is surfaced
                warnings.append(f"yfinance: {type(exc).__name__}: {exc}".rstrip(": "))
        history = _history_rows(history_events, symbol) if want_history else []
        if want_history and self.deps.yfinance and not history and not warnings:
            # A silent empty answer (cold Yahoo session) is not "this stock pays no dividend".
            warnings.append("yfinance: the Yahoo event series returned no dividend history.")

        if corporate is None:
            return unavailable_result(
                self.code, instrument, corporate_error or "awareness returned no response",
                extra={"symbol": symbol, "history": history},
            )
        upcoming = [_upcoming_row(item) for item in corporate.data or [] if isinstance(item, dict)]
        upcoming.sort(key=lambda r: str(r.get("date") or ""))
        today_text = today.isoformat()
        has_rows = bool(upcoming or history)
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok" if has_rows else "empty",
                "symbol": symbol,
                "rows": upcoming + history,
                "upcoming": upcoming,
                "history": history,
                "summary": _summary(history, upcoming, today_text),
                "meta": data_meta([corporate]),
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "reason": None if has_rows else (
                    f"No upcoming dividend for {symbol} in the Awareness calendar (next "
                    f"{_UPCOMING_DAYS} days)"
                    + (" and no dividend history from Yahoo." if want_history else ".")
                ),
            },
            sources=["awareness:corporate"] + (["yfinance"] if history else []),
            warnings=warnings,
            metadata=provenance_metadata([corporate], provider_errors=warnings, extra={
                "symbol": symbol,
                "history_requested": want_history,
            }),
        )
