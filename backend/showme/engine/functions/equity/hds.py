"""HDS — Holders / Institutional Holdings."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import FIELD_DICTIONARIES, finite, frame_rows


@FunctionRegistry.register
class HDSFunction(BaseFunction):
    code = "HDS"
    name = "Holders"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("HDS requires a symbol")
        if instrument.asset_class not in {AssetClass.EQUITY, AssetClass.ETF}:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "not_applicable",
                    "rows": [],
                    "reason": f"HDS covers equities and ETFs, not {instrument.asset_class.value}.",
                    "field_dictionary": FIELD_DICTIONARIES["holders"],
                },
                sources=[],
                metadata={"live": False},
            )
        if not _truthy(params.get("live_holders") or params.get("live")):
            # No holder rows are synthesised here: holder data exists only when a
            # provider returns it, so the honest state is "live mode is off".
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "needs_input",
                    "rows": [],
                    "reason": "Live holder mode is off. Turn on live to query Yahoo holder tables and local SEC 13F data.",
                    "next_actions": ["Set live=true to query holder providers."],
                    "field_dictionary": FIELD_DICTIONARIES["holders"],
                },
                sources=[],
                metadata={"live": False},
            )
        warnings: list[str] = []
        sources: list[str] = []
        yahoo: dict[str, Any] = {}
        # First try yfinance (fast, but only top-line institutional/major holders)
        try:
            if self.deps.yfinance:
                yahoo = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.HOLDINGS, instrument=instrument
                    )),
                    timeout=float(params.get("yfinance_timeout", 8)),
                )
                if not isinstance(yahoo, dict):
                    yahoo = {}
                sources.append("yfinance")
        except Exception as e:
            warnings.append(f"yfinance: {e}")
        # Then enrich with SEC 13F aggregate by issuer name (DuckDB-cached)
        sec_top: list[dict[str, Any]] = []
        sec_13f = getattr(self.deps, "sec_13f", None)
        if sec_13f:
            try:
                top = await asyncio.wait_for(
                    sec_13f.query_holdings_by_security(
                        issuer=instrument.symbol,
                        top_n=int(params.get("top_n", 20)),
                    ),
                    timeout=float(params.get("sec_timeout", 8)),
                )
                if not top.empty:
                    sec_top = top.to_dict(orient="records")
                    sources.append("sec_13f")
            except Exception as e:
                warnings.append(f"sec_13f: {e}")
        rows = _holder_rows(instrument.symbol, sec_top, yahoo)
        summary = _major_summary(yahoo.get("major"))
        if rows:
            status, reason = "ok", None
        elif sources:
            status = "empty"
            reason = f"Holder providers answered for {instrument.symbol} but returned no holder rows."
        else:
            status = "provider_unavailable"
            reason = f"No holder provider returned data for {instrument.symbol}."
        if warnings and reason:
            reason = f"{reason} Provider errors: {'; '.join(warnings)}"
        payload: dict[str, Any] = {
            "status": status,
            "rows": rows,
            "methodology": "HDS shows holder rows from Yahoo institutional / mutual-fund holder tables and local SEC 13F data. Yahoo major-holder percentages are a summary block, not holder rows.",
            "field_dictionary": FIELD_DICTIONARIES["holders"],
        }
        if reason:
            payload["reason"] = reason
        if summary:
            payload["major_holders_summary"] = summary
        if sec_top:
            payload["sec_13f_top"] = sec_top
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=payload,
            sources=sources,
            metadata={
                "note": "Run scripts/ingest_13f.py to backfill DuckDB",
                "provider_errors": warnings,
                "live": True,
            },
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _major_summary(frame: Any) -> dict[str, Any]:
    """Yahoo major_holders is a label/Value summary, not a holder table."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    out: dict[str, Any] = {}
    has_value = "Value" in frame.columns
    for idx, row in frame.iterrows():
        if has_value:
            label, raw = idx, row["Value"]
        elif frame.shape[1] >= 2:
            label, raw = row.iloc[0], row.iloc[1]
        else:
            label, raw = idx, row.iloc[0]
        key = str(label).strip()
        if key:
            out[key] = finite(raw)
    return out


def _holder_rows(symbol: str, sec_top: list[dict[str, Any]], yahoo: dict[str, Any]) -> list[dict[str, Any]]:
    if sec_top:
        rows = []
        for item in sec_top:
            rows.append({
                "symbol": symbol,
                "holder": item.get("filer") or item.get("holder") or item.get("name"),
                "holder_type": "institutional_13f",
                "shares": finite(item.get("shares") or item.get("sshPrnamt")),
                "market_value": finite(item.get("market_value") or item.get("value")),
                "quarter": item.get("quarter") or item.get("period"),
                "source_mode": "sec_13f",
            })
        return rows
    rows = []
    for key, holder_type in [("institutional", "institutional"), ("mutualfund", "mutual_fund")]:
        for item in frame_rows(yahoo.get(key), limit=25):
            rows.append({
                "symbol": symbol,
                "holder": item.get("Holder") or item.get("holder") or item.get("index") or holder_type,
                "holder_type": holder_type,
                "shares": finite(item.get("Shares") or item.get("shares")),
                "pct_outstanding": finite(item.get("% Out") or item.get("pct_outstanding")),
                "market_value": finite(item.get("Value") or item.get("value")),
                "date_reported": item.get("Date Reported") or item.get("date_reported"),
                "source_mode": "yfinance_holders",
            })
    return rows
