"""HFS — Holder search (13F reverse lookup).

For an issuer ticker / company / CUSIP: which filers held it last quarter,
how many shares, total notional, ranked.

Backed by `data_sources/equity/sec_13f_adapter.py` DuckDB store.
Run `python scripts/ingest_13f.py` first to populate.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import FIELD_DICTIONARIES, reference_profile


@FunctionRegistry.register
class HFSFunction(BaseFunction):
    code = "HFS"
    name = "Holder Search"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "13F reverse lookup — list filers holding a given issuer / CUSIP."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        issuer = params.get("issuer") or (instrument.symbol if instrument else None)
        if not _truthy(params.get("live_holders") or params.get("live")):
            rows = _holder_search_template(issuer, instrument)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=rows,
                sources=["holder_search_model"],
                metadata={"issuer": issuer, "rows": len(rows), "live": False},
            )
        sec = getattr(self.deps, "sec_13f", None)
        if sec is None:
            rows = _holder_search_template(issuer, instrument)
            return FunctionResult(code=self.code, instrument=instrument, data={
                                  "status": "reference_holders" if rows and rows[0].get("source_mode") != "holder_search_unavailable" else "provider_unavailable",
                                  "rows": rows,
                                  "issuer": issuer,
                                  "quarter": "latest",
                                  "methodology": "HFS reverse-lookups 13F filers by issuer/CUSIP. Local 13F data is not populated, so rows are labelled public-reference holders when available.",
                                  "field_dictionary": FIELD_DICTIONARIES["holders"],
                                  "next_actions": ["Run scripts/ingest_13f.py to populate local 13F reverse lookup."],
                                  },
                                  sources=["holder_search_model"])
        cusip = params.get("cusip")
        quarter = params.get("quarter")
        top_n = int(params.get("top_n", 30))
        try:
            df = await asyncio.wait_for(
                sec.query_holdings_by_security(
                    cusip=cusip, issuer=issuer, quarter=quarter, top_n=top_n,
                ),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception as e:
            rows = [{"filer": "No local 13F match", "issuer": issuer,
                     "shares": 0, "market_value": 0, "source_mode": "holder_search_unavailable"}]
            return FunctionResult(code=self.code, instrument=instrument, data={
                                  "status": "provider_unavailable",
                                  "rows": rows,
                                  "issuer": issuer,
                                  "quarter": quarter or "latest",
                                  "methodology": "HFS reverse-lookups 13F filers by issuer/CUSIP. Provider errors are surfaced instead of returning an empty OK table.",
                                  "field_dictionary": FIELD_DICTIONARIES["holders"],
                                  "next_actions": ["Run scripts/ingest_13f.py or retry the local SEC 13F store."],
                                  },
                                  sources=["holder_search_model"],
                                  metadata={"provider_errors": [f"sec_13f: {e}"]})
        rows: list[dict[str, Any]] = []
        if hasattr(df, "to_dict") and not df.empty:
            rows = df.to_dict(orient="records")
        if not rows:
            rows = _holder_search_template(issuer, instrument)
        return FunctionResult(
            code=self.code, instrument=instrument, data={
                "status": "ok" if rows and rows[0].get("source_mode") != "holder_search_unavailable" else "provider_unavailable",
                "rows": rows,
                "issuer": issuer,
                "quarter": quarter or "latest",
                "methodology": "HFS reverse-lookups 13F filers by issuer/CUSIP. If the local 13F DuckDB is empty, the rows are labelled public-reference holders and next actions explain how to backfill the local database.",
                "field_dictionary": FIELD_DICTIONARIES["holders"],
                "next_actions": [] if sec else ["Run scripts/ingest_13f.py to populate local 13F reverse lookup."],
            },
            sources=["sec_13f"],
            metadata={"cusip": cusip, "issuer": issuer,
                       "quarter": quarter, "rows": len(rows),
                       "note": "Run scripts/ingest_13f.py to backfill DuckDB.",
                       "live": True},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _holder_search_template(issuer: str | None, instrument: Instrument | None) -> list[dict[str, Any]]:
    asset_class = instrument.asset_class.value if instrument else "UNKNOWN"
    if instrument and instrument.asset_class not in {AssetClass.EQUITY, AssetClass.ETF}:
        return [{
            "filer": "not_applicable",
            "issuer": issuer,
            "shares": 0,
            "market_value": 0,
            "asset_class": asset_class,
        }]
    profile = reference_profile(str(issuer or ""))
    rows = []
    for item in profile.get("holders", []):
        rows.append({
            "filer": item.get("holder"),
            "issuer": issuer,
            "shares": item.get("shares"),
            "pct_outstanding": item.get("pct_outstanding"),
            "quarter": item.get("quarter"),
            "source_mode": item.get("source_mode", "reference_13f_public"),
        })
    return rows or [{
        "filer": "No local 13F match",
        "issuer": issuer,
        "shares": 0,
        "market_value": 0,
        "source_mode": "holder_search_unavailable",
    }]
