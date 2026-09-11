"""DVD — Dividends & Splits."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import series_rows


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
            # F6 fix: the model branch used to return the bare `_template_events`
            # dict with no `rows`/`status`, so the pane's Model toggle rendered
            # "No corporate actions" (dead mode). Return real reference rows,
            # explicitly labelled as model data — never as reported events.
            template = _template_events(instrument)
            rows = _model_rows(instrument.symbol, template)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "modeled",
                    "symbol": instrument.symbol,
                    "rows": rows,
                    "history": [r for r in rows if r.get("action_type") == "dividend"],
                    "dividends": template["dividends"],
                    "splits": template["splits"],
                    "actions": template["actions"],
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                },
                sources=["dividend_calendar_model"],
                warnings=[
                    (
                        "Model mode: rows are reference-shaped model events, not "
                        "reported corporate actions. Switch the toggle to Live "
                        "for provider data."
                    )
                ],
                metadata={"live": False, "data_mode": "modeled"},
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
            "methodology": _METHODOLOGY,
            "field_dictionary": _FIELD_DICTIONARY,
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


def _model_rows(symbol: str, template: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn the model template into explicit, labelled reference rows.

    F6 fix: the Model mode is a reference-shape model — every row carries
    ``source_mode="model"`` so the pane can never present it as a reported
    corporate action.
    """
    rows: list[dict[str, Any]] = []
    for div in template.get("dividends") or []:
        if not isinstance(div, dict):
            continue
        amount = div.get("amount")
        rows.append({
            "symbol": symbol,
            "action_type": "dividend",
            "date": div.get("date"),
            "amount": amount if isinstance(amount, (int, float)) else None,
            "source_mode": "model",
            "reason": div.get("status"),
        })
    for split in template.get("splits") or []:
        if not isinstance(split, dict):
            continue
        ratio = split.get("ratio")
        if isinstance(ratio, (int, float)):
            rows.append({
                "symbol": symbol,
                "action_type": "split",
                "date": split.get("date"),
                "amount": ratio,
                "source_mode": "model",
                "reason": split.get("status"),
            })
    if not rows:
        first = (template.get("dividends") or [{}])[0]
        rows = [{
            "symbol": symbol,
            "action_type": "not_applicable",
            "date": None,
            "amount": None,
            "source_mode": "model",
            "reason": first.get("status") if isinstance(first, dict) else None,
        }]
    return rows


def _template_events(instrument: Instrument) -> dict[str, Any]:
    symbol = instrument.symbol
    asset_class = instrument.asset_class.value
    is_equity_like = asset_class in {"EQUITY", "ETF"}
    today = datetime.now(timezone.utc).date().isoformat()
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


_METHODOLOGY = (
    "DVD separates cash dividends and stock splits from Yahoo corporate-action "
    "event series. Dividends are cash per share; split rows use split ratio. "
    "Model mode rows are reference-shaped model events (source_mode=model), "
    "not reported corporate actions."
)

_FIELD_DICTIONARY = {
    "date": "Ex/effective date returned by the provider.",
    "amount": "Cash dividend per share or split ratio.",
    "action_type": "dividend or split.",
    "source_mode": "Provider event table used for the row.",
}
