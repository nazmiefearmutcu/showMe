"""HDS — Holders / Institutional Holdings."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import FIELD_DICTIONARIES, finite, frame_rows, reference_profile


@FunctionRegistry.register
class HDSFunction(BaseFunction):
    code = "HDS"
    name = "Holders"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("HDS requires a symbol")
        if not _truthy(params.get("live_holders") or params.get("live")):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_holders_model(instrument),
                sources=["holders_model"],
                metadata={"live": False},
            )
        warnings: list[str] = []
        data: dict[str, Any] = {}
        sources: list[str] = []
        # First try yfinance (fast, but only top-line institutional/major holders)
        try:
            if self.deps.yfinance:
                data["yfinance"] = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.HOLDINGS, instrument=instrument
                    )),
                    timeout=float(params.get("yfinance_timeout", 8)),
                )
                sources.append("yfinance")
        except Exception as e:
            warnings.append(f"yfinance: {e}")
        # Then enrich with SEC 13F aggregate by issuer name (DuckDB-cached)
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
                    data["sec_13f_top"] = top.to_dict(orient="records")
                    sources.append("sec_13f")
            except Exception as e:
                warnings.append(f"sec_13f: {e}")
        if not data:
            data = {
                "holders": _reference_holder_rows(instrument.symbol),
                "status": "reference_holders",
            }
            sources = ["holders_reference"]
        rows = _holder_rows(instrument.symbol, data)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                **data,
                "status": data.get("status") or ("ok" if rows else "provider_unavailable"),
                "rows": rows,
                "methodology": "HDS shows holder rows from Yahoo holder tables and optional local SEC 13F data. When local 13F is empty, ShowMe labels public-reference holder rows instead of showing insider transaction columns.",
                "field_dictionary": FIELD_DICTIONARIES["holders"],
            },
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


def _holders_model(instrument: Instrument) -> dict[str, Any]:
    if instrument.asset_class not in {AssetClass.EQUITY, AssetClass.ETF}:
        return {
            "holders": [{
                "holder": "not_applicable",
                "shares": 0,
                "pct_outstanding": None,
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class.value,
            }],
            "status": "not_applicable",
        }
    return {
        "status": "reference_holders",
        "holders": _reference_holder_rows(instrument.symbol) or [
            {"holder": "Institutional holders aggregate", "shares": 1_250_000, "pct_outstanding": 0.012, "symbol": instrument.symbol},
            {"holder": "Insider and strategic holders", "shares": 450_000, "pct_outstanding": 0.004, "symbol": instrument.symbol},
        ],
        "methodology": "Reference holder rows preserve expected HDS shape when live holders are disabled.",
    }


def _reference_holder_rows(symbol: str) -> list[dict[str, Any]]:
    rows = []
    for row in reference_profile(symbol).get("holders", []):
        rows.append({"symbol": symbol, **row})
    return rows


def _holder_rows(symbol: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("sec_13f_top"), list) and data["sec_13f_top"]:
        rows = []
        for item in data["sec_13f_top"]:
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
    if isinstance(data.get("holders"), list):
        return data["holders"]
    holdings = data.get("yfinance") if isinstance(data.get("yfinance"), dict) else {}
    rows = []
    for key, holder_type in [("institutional", "institutional"), ("mutualfund", "mutual_fund"), ("major", "major_holder")]:
        for item in frame_rows(holdings.get(key), limit=25):
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
    return rows or _reference_holder_rows(symbol)
