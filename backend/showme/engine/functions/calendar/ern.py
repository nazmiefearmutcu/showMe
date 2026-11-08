"""ERN — Earnings calendar (Awareness corporate calendar)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.calendar._common import (
    aw_get,
    data_meta,
    iso_day,
    parse_csv,
    parse_day,
    parse_float,
    parse_int,
    provenance_metadata,
    unavailable_result,
    utc_today,
)

_TIME_OF_DAY = {
    "bmo": "bmo",
    "pre-market": "bmo",
    "premarket": "bmo",
    "amc": "amc",
    "after-hours": "amc",
    "afterhours": "amc",
}


def _time_of_day(raw: Any) -> str:
    return _TIME_OF_DAY.get(str(raw or "").strip().lower(), "unknown")


def _norm_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace(".", "-")


def _earning_row(item: dict[str, Any], watch: set[str]) -> dict[str, Any]:
    fields = item.get("fields") or {}
    symbol = str(item.get("symbol") or "").strip().upper()
    return {
        "date": item.get("date"),
        "time_of_day": _time_of_day(item.get("time_of_day")),
        "symbol": symbol,
        "company": item.get("company"),
        "eps_estimate": fields.get("eps_estimate"),
        "num_estimates": fields.get("num_estimates"),
        "fiscal_quarter": fields.get("fiscal_quarter"),
        "market_cap": fields.get("market_cap"),
        "last_year_eps": fields.get("last_year_eps"),
        "last_year_report_date": fields.get("last_year_report_date"),
        "in_watchlist": _norm_symbol(symbol) in watch,
        "sources": item.get("sources") or [],
    }


@FunctionRegistry.register
class ERNFunction(BaseFunction):
    code = "ERN"
    name = "Earnings Calendar"
    asset_classes = ()
    category = "macro"
    description = (
        "Upcoming and recent company earnings dates with BMO/AMC timing, EPS consensus, "
        "estimate count and market cap, from the Awareness corporate calendar."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        today = utc_today()
        start = parse_day(params.get("from")) or today
        days = parse_int(params.get("days"), default=7, floor=1, ceiling=30)
        end = start + timedelta(days=days)
        symbols = parse_csv(params.get("symbols"))
        min_market_cap = parse_float(params.get("min_market_cap"))
        time_filter = str(params.get("time_of_day") or "").strip().lower()
        if time_filter not in {"", "bmo", "amc"}:
            time_filter = ""

        query: dict[str, Any] = {"from": iso_day(start), "to": iso_day(end), "types": "earnings"}
        if symbols:
            query["symbols"] = ",".join(symbols)
        calendar, error = await aw_get(self, "/calendar/corporate", query)
        if error is not None or calendar is None:
            return unavailable_result("ERN", None, error or "awareness returned no response")

        watch_resp, watch_error = await aw_get(self, "/watchlist")
        watch = {_norm_symbol(sym) for sym in (watch_resp.data if watch_resp and isinstance(watch_resp.data, list) else [])}
        warnings: list[str] = [f"watchlist: {watch_error}"] if watch_error else []

        rows = [_earning_row(item, watch) for item in calendar.data if isinstance(item, dict)]
        if min_market_cap is not None:
            rows = [row for row in rows if (parse_float(row.get("market_cap")) or 0.0) >= min_market_cap]
        if time_filter:
            rows = [row for row in rows if row["time_of_day"] == time_filter]
        rows.sort(key=lambda row: (str(row.get("date") or ""), -(parse_float(row.get("market_cap")) or 0.0)))

        by_day: dict[str, int] = {}
        for row in rows:
            day = str(row.get("date") or "")
            by_day[day] = by_day.get(day, 0) + 1

        responses = [calendar] + ([watch_resp] if watch_resp is not None else [])
        meta = data_meta(responses)
        status = "ok" if rows else "empty"
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": status,
                "rows": rows,
                "by_day": by_day,
                "count": len(rows),
                "watchlist_count": sum(1 for row in rows if row["in_watchlist"]),
                "filters": {
                    "from": iso_day(start),
                    "to": iso_day(end),
                    "days": days,
                    "symbols": symbols,
                    "min_market_cap": min_market_cap,
                    "time_of_day": time_filter or None,
                },
                "meta": meta,
                "methodology": (
                    "ERN lists scheduled earnings reports from the Awareness corporate calendar for the "
                    "requested window. time_of_day is bmo (before market open), amc (after market close) or "
                    "unknown when the provider did not state it. Rows sort by date, then market cap "
                    "descending. in_watchlist marks symbols on the Awareness watchlist. Nothing is estimated."
                ),
                "field_dictionary": {
                    "eps_estimate": "Consensus EPS estimate for the reported quarter.",
                    "num_estimates": "Number of analyst estimates behind the consensus.",
                    "market_cap": "Market capitalisation reported by the provider (USD).",
                    "last_year_eps": "EPS reported for the same quarter last year.",
                },
                "next_actions": [] if rows else ["Widen the window with days or from."],
            },
            sources=["awareness:corporate"] + (["awareness:watchlist"] if watch_resp is not None else []),
            warnings=warnings,
            metadata=provenance_metadata(responses, provider_errors=warnings,
                                         extra={"requested_days": days}),
        )
