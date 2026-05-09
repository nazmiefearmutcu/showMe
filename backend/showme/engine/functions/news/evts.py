"""EVTS — Corporate Events Calendar."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if getattr(value, "empty", False):
        return True
    if isinstance(value, dict):
        return not value or all(_is_empty(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return not value or all(_is_empty(item) for item in value)
    return False


@FunctionRegistry.register
class EVTSFunction(BaseFunction):
    code = "EVTS"
    name = "Corporate Events"
    asset_classes = (AssetClass.EQUITY,)
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        events: dict[str, Any] = {}
        warnings: list[str] = []
        live = _truthy(params.get("live_events") or params.get("live"))
        if live and self.deps.yfinance:
            try:
                timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
                events = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.EVENTS,
                        instrument=instrument,
                        extra={"timeout": timeout},
                    )),
                    timeout=timeout + 1,
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"yfinance: {exc}")
        rows = _event_rows(events, instrument.symbol)
        if not rows:
            reason = "No dated corporate events were returned for this symbol."
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable" if live else "empty",
                    "reason": reason,
                    "rows": [],
                    "symbol": instrument.symbol,
                    "next_actions": [
                        "Retry with another equity symbol or a longer provider timeout.",
                        "Open Raw function payload to inspect event provider errors.",
                    ],
                },
                sources=["yfinance" if live and self.deps.yfinance else "no_live_source"],
                metadata={"live": live, "provider_errors": warnings or [reason]},
            )
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": rows,
                "symbol": instrument.symbol,
                "event_count": len(rows),
            },
            sources=["yfinance" if live and self.deps.yfinance else "corporate_events_model"],
            metadata={"live": live, "provider_errors": warnings},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _event_rows(events: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    calendar = events.get("calendar") if isinstance(events, dict) else None
    if isinstance(calendar, dict):
        for key, value in calendar.items():
            if _is_empty(value):
                continue
            rows.append({
                "symbol": symbol,
                "event": _human_label(str(key)),
                "date": _date_value(value),
                "value": _scalar_value(value),
                "source_section": "calendar",
            })
    elif isinstance(calendar, list):
        for item in calendar:
            if isinstance(item, dict) and not _is_empty(item):
                rows.append({"symbol": symbol, "source_section": "calendar", **item})
    earnings = events.get("earnings_dates") if isinstance(events, dict) else None
    rows.extend(_frame_rows(earnings, symbol, "earnings"))
    actions = events.get("actions") if isinstance(events, dict) else None
    rows.extend(_frame_rows(actions, symbol, "action"))
    for section in ("dividends", "splits"):
        series = events.get(section) if isinstance(events, dict) else None
        if isinstance(series, pd.Series) and not series.empty:
            for idx, value in series.tail(12).items():
                rows.append({
                    "symbol": symbol,
                    "event": section[:-1],
                    "date": _date_value(idx),
                    "value": _scalar_value(value),
                    "source_section": section,
                })
    rows = [row for row in rows if row.get("date") or row.get("value") not in (None, "")]
    rows.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
    return rows[:50]


def _frame_rows(value: Any, symbol: str, event_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, pd.DataFrame) or value.empty:
        return []
    frame = value.tail(20).reset_index()
    out: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        row = {str(k): _scalar_value(v) for k, v in raw.items()}
        date = row.get("Earnings Date") or row.get("Date") or row.get("index")
        out.append({
            "symbol": symbol,
            "event": event_name,
            "date": _date_value(date),
            "source_section": event_name,
            **row,
        })
    return out


def _date_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    text = str(value).strip()
    return text or None


def _scalar_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        return _date_value(value)
    if pd.isna(value):
        return None
    return value


def _human_label(value: str) -> str:
    return value.replace("_", " ").strip().lower() or "event"
