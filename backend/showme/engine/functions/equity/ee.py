"""EE — Earnings & Estimates."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import date_label, finite, frame_rows


@FunctionRegistry.register
class EEFunction(BaseFunction):
    code = "EE"
    name = "Earnings & Estimates"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Historical earnings (actual vs consensus) + surprise % + next report date."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("EE requires instrument")
        history = int(params.get("history", 8))
        # Default-polarity flip (2026-09-08): EE pulls live earnings by
        # default. ``reference=true`` used to serve an invented FY-quarter
        # template; that is never shown as data (DATA POLICY). It now returns
        # an explicit empty state with no figures.
        if _truthy(params.get("reference")):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_reference_empty(instrument),
                sources=[],
                warnings=[
                    "reference mode ships no earnings figures; nothing was modelled or fabricated"
                ],
                metadata={"live": False, "data_mode": "empty"},
            )
        warnings: list[str] = []
        sources: list[str] = []
        finnhub_data = None
        try:
            if self.deps.finnhub:
                finnhub_data = await asyncio.wait_for(
                    self.deps.finnhub._get("/stock/earnings", symbol=instrument.symbol),
                    timeout=float(params.get("finnhub_timeout", 8)),
                )
        except Exception as e:
            warnings.append(f"finnhub: {e}")
        yf_data = None
        try:
            if self.deps.yfinance:
                from showme.engine.core.base_data_source import DataKind, DataRequest
                yf_data = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument,
                    )),
                    timeout=float(params.get("yfinance_timeout", 8)),
                )
        except Exception as e:
            warnings.append(f"yfinance: {e}")
        candidate_rows = _earnings_rows(instrument.symbol, finnhub_data, yf_data, history + 4)
        # Honesty (EE#3/EE#4): the placeholder is decided by whether any real
        # provider row exists. Provider errors are never cleared, and a
        # provider is listed in ``sources`` only once it has returned rows.
        placeholder = all(r.get("source_mode") == _UNAVAILABLE_MODE for r in candidate_rows)
        if finnhub_data:
            sources.append("finnhub")
        if _yf_has_data(yf_data):
            sources.append("yfinance")
        reported_rows, table_next = _split_upcoming(candidate_rows, date.today())
        reported_rows = reported_rows[:history]
        next_report = _reconcile_next_report(
            instrument.symbol, table_next, yf_data, date.today(), warnings
        )
        if placeholder:
            sources.append("earnings_calendar_model")
            # Honesty (2026-09-08): never wipe provider errors on the
            # fallback — the placeholder row must be visibly labelled, not
            # passed off as reported figures.
            warnings.append(
                "No earnings history from any provider; rows are labelled "
                "unavailable rather than reported figures."
            )
        metadata = (
            {"live": False, "fallback": True, "data_mode": "modeled"}
            if placeholder
            else {
                "live": True,
                "data_mode": "live_official" if finnhub_data else "live_yfinance",
            }
        )
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "provider_unavailable" if placeholder else "ok",
                "rows": reported_rows,
                "next_report": next_report,
                "earnings": (finnhub_data or [])[:history] if isinstance(finnhub_data, list) else finnhub_data,
                "calendar": (yf_data or {}).get("calendar") if yf_data else None,
                "earnings_dates": (yf_data or {}).get("earnings_dates") if yf_data else None,
                "methodology": "EE merges Finnhub historical earnings with Yahoo earnings-date tables. Visible rows show actual EPS, consensus/estimate EPS, surprise percent, and source mode when available.",
                "field_dictionary": {
                    "actual": "Reported EPS.",
                    "estimate": "Consensus EPS estimate before report.",
                    "surprisePercent": "(actual - estimate) / abs(estimate) * 100.",
                    "next_report": "Next known earnings date or provider calendar item.",
                },
            },
            sources=sources, warnings=warnings, metadata=metadata,
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_period_date(period: Any) -> date | None:
    text = str(period or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


_UNAVAILABLE_MODE = "earnings_calendar_unavailable"


def _yf_has_data(yf_data: Any) -> bool:
    """True only when the yfinance leg returned a calendar or earnings table."""
    if not isinstance(yf_data, dict):
        return False
    calendar = yf_data.get("calendar")
    if isinstance(calendar, dict) and calendar:
        return True
    return bool(frame_rows(yf_data.get("earnings_dates"), limit=1))


def _calendar_next_date(yf_data: Any, today: date) -> date | None:
    """Earliest forward date in the yfinance calendar's ``Earnings Date``."""
    if not isinstance(yf_data, dict) or not isinstance(yf_data.get("calendar"), dict):
        return None
    raw = yf_data["calendar"].get("Earnings Date")
    if raw is None:
        return None
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    upcoming = [
        when for when in (_parse_period_date(date_label(v)) for v in values)
        if when is not None and when > today
    ]
    return min(upcoming) if upcoming else None


def _reconcile_next_report(
    symbol: str,
    table_next: dict[str, Any] | None,
    yf_data: Any,
    today: date,
    warnings: list[str],
) -> dict[str, Any] | None:
    """One next-report date, with its source.

    The yfinance calendar's forward ``Earnings Date`` is the reconciled date
    when present; the earnings-dates or Finnhub upcoming row supplies the
    estimate only when both name the same day. A disagreement is a warning,
    never a silently chosen date.
    """
    cal_day = _calendar_next_date(yf_data, today)
    if cal_day is None:
        return table_next
    estimate = None
    if table_next is not None:
        if table_next.get("date") == cal_day.isoformat():
            estimate = table_next.get("estimate")
        else:
            warnings.append(
                f"yfinance calendar next report {cal_day.isoformat()} differs from "
                f"the {table_next.get('source')} date {table_next.get('date')}; "
                "showing the calendar date."
            )
    return {
        "symbol": symbol,
        "date": cal_day.isoformat(),
        "estimate": estimate,
        "actual": None,
        "source_mode": "yfinance_calendar",
        "source": "yfinance_calendar",
        "status": "scheduled",
    }


def _split_upcoming(rows: list[dict[str, Any]], today: date) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Separate the not-yet-reported quarter from the reported history.

    A row with no actual EPS whose period lies after ``today`` is the next
    scheduled report: it is surfaced as ``next_report`` and kept out of the
    reported rows, so "last actual" can never read an unreported quarter.
    """
    reported: list[dict[str, Any]] = []
    upcoming: list[tuple[date, dict[str, Any]]] = []
    for row in rows:
        when = _parse_period_date(row.get("period") or row.get("date"))
        if row.get("actual") is None and when is not None and when > today:
            upcoming.append((when, row))
        else:
            reported.append(row)
    if not upcoming:
        return reported, None
    when, row = min(upcoming, key=lambda item: item[0])
    next_report = {
        "symbol": row.get("symbol"),
        "date": when.isoformat(),
        "estimate": row.get("estimate"),
        "actual": None,
        "source_mode": row.get("source_mode"),
        "source": row.get("source_mode"),
        "status": "scheduled",
    }
    return reported, next_report


def _reference_empty(instrument: Instrument) -> dict[str, Any]:
    return {
        "status": "empty",
        "rows": [],
        "earnings": [],
        "calendar": None,
        "earnings_dates": None,
        "next_report": None,
        "methodology": (
            "Reference mode is kept for layout only and carries no earnings figures. "
            "Turn MODE to live to see reported EPS, consensus and surprise."
        ),
        "reason": "reference_mode_has_no_figures",
        "symbol": instrument.symbol,
        "next_actions": ["Switch MODE to live", "Pick another ticker"],
    }


def _earnings_rows(symbol: str, finnhub_data: Any, yf_data: Any, history: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(finnhub_data, list):
        for item in finnhub_data[:history]:
            actual = finite(item.get("actual"))
            estimate = finite(item.get("estimate"))
            surprise = finite(item.get("surprisePercent"))
            if surprise is None and actual is not None and estimate not in (None, 0):
                surprise = (actual - estimate) / abs(estimate) * 100
            rows.append({
                "symbol": symbol,
                "period": item.get("period") or item.get("quarter") or item.get("date"),
                "date": item.get("period") or item.get("date"),
                "actual": actual,
                "estimate": estimate,
                "surprisePercent": surprise,
                "source_mode": "finnhub_earnings",
            })
    if not rows and yf_data:
        for item in frame_rows((yf_data or {}).get("earnings_dates"), limit=history):
            actual = finite(item.get("Reported EPS") or item.get("reportedEPS") or item.get("actual"))
            estimate = finite(item.get("EPS Estimate") or item.get("epsEstimate") or item.get("estimate"))
            # HNT-02 fix: the Yahoo ``Surprise(%)`` column is already in
            # percent units. The old |v| <= 1 → *100 heuristic multiplied
            # routine sub-1% EPS surprises by 100 (a %0.67 beat rendered as
            # %67). The value is used exactly as the provider reports it.
            surprise = finite(item.get("Surprise(%)") or item.get("surprisePercent"))
            rows.append({
                "symbol": symbol,
                "period": date_label(item.get("Earnings Date") or item.get("index") or item.get("date")),
                "date": date_label(item.get("Earnings Date") or item.get("index") or item.get("date")),
                "actual": actual,
                "estimate": estimate,
                "surprisePercent": surprise,
                "source_mode": "yfinance_earnings_dates",
            })
    return rows[:history] or [{
        "symbol": symbol,
        "period": "provider_unavailable",
        "actual": None,
        "estimate": None,
        "surprisePercent": None,
        "source_mode": "earnings_calendar_unavailable",
    }]
