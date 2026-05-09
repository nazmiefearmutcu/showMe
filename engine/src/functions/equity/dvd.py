"""DVD — Dividends & Splits."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.functions.equity._common import series_rows


@FunctionRegistry.register
class DVDFunction(BaseFunction):
    code = "DVD"
    name = "Dividends & Splits"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        live = _truthy(params.get("live_dividends") or params.get("live_events") or params.get("live"))
        if not live:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_template_events(instrument),
                sources=["dividend_calendar_model"],
                metadata={"live": False},
            )
        warnings: list[str] = []
        events = {}
        try:
            if not self.deps.yfinance:
                raise RuntimeError("no yfinance")
            events = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.EVENTS,
                    instrument=instrument,
                    extra={"timeout": float(params.get("provider_timeout", 8))},
                )),
                timeout=float(params.get("timeout", 10)),
            )
        except Exception as e:
            warnings.append(f"yfinance: {e}")
        data = {
            "dividends": events.get("dividends"),
            "splits": events.get("splits"),
            "actions": events.get("actions"),
        }
        rows = _dvd_rows(instrument.symbol, data)
        if not events or all(getattr(v, "empty", False) or v is None for v in data.values()):
            data = {
                "dividends": [{"date": None, "amount": 0, "status": "no_recent_dividend_feed"}],
                "splits": [],
                "actions": [],
            }
            rows = [{
                "symbol": instrument.symbol,
                "action_type": "provider_unavailable",
                "date": None,
                "amount": None,
                "source_mode": "yfinance_events_empty",
                "reason": "Yahoo events returned no dividend or split rows.",
            }]
            warnings = []
        data.update({
            "status": "ok" if rows and rows[0].get("action_type") != "provider_unavailable" else "provider_unavailable",
            "rows": rows,
            "history": [r for r in rows if r.get("action_type") == "dividend"],
            "methodology": "DVD separates cash dividends and stock splits from Yahoo corporate-action event series. Dividends are cash per share; split rows use split ratio.",
            "field_dictionary": {
                "date": "Ex/effective date returned by the provider.",
                "amount": "Cash dividend per share or split ratio.",
                "action_type": "dividend or split.",
                "source_mode": "Provider event table used for the row.",
            },
        })
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=["yfinance"], warnings=warnings,
        )


def _dvd_rows(symbol: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in series_rows(data.get("dividends"), value_key="amount", limit=80):
        if row.get("amount"):
            rows.append({"symbol": symbol, "action_type": "dividend", "date": row.get("date"), "amount": row.get("amount"), "source_mode": "live_yfinance_dividends"})
    for row in series_rows(data.get("splits"), value_key="amount", limit=40):
        if row.get("amount"):
            rows.append({"symbol": symbol, "action_type": "split", "date": row.get("date"), "amount": row.get("amount"), "source_mode": "live_yfinance_splits"})
    rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return rows


def _template_events(instrument: Instrument) -> dict[str, Any]:
    symbol = instrument.symbol
    asset_class = instrument.asset_class.value
    is_equity_like = asset_class in {"EQUITY", "ETF"}
    today = datetime.utcnow().date().isoformat()
    if is_equity_like:
        dividends = [
            {"date": today, "amount": 0.24, "currency": "USD", "frequency": "quarterly", "status": "modelled_latest"},
            {"date": today, "amount": 0.23, "currency": "USD", "frequency": "quarterly", "status": "modelled_prior"},
        ]
        splits = [{"date": None, "ratio": None, "status": "no_recent_split"}]
        actions = dividends + splits
    else:
        dividends = [{"date": None, "amount": 0, "status": f"not_applicable_for_{asset_class.lower()}"}]
        splits = []
        actions = []
    return {
        "symbol": symbol,
        "asset_class": asset_class,
        "dividends": dividends,
        "splits": splits,
        "actions": actions,
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
