"""HFS — Holder search (13F reverse lookup).

For an issuer ticker / company / CUSIP: which filers held it last quarter,
how many shares, total notional, ranked.

Backed by `data_sources/equity/sec_13f_adapter.py` DuckDB store.
Run `python scripts/ingest_13f.py` first to populate.

Holder rows come only from that local 13F store. When the store is not wired,
errors, or holds no rows for the issuer, HFS returns an explicit
``provider_unavailable`` state with no rows and next actions. Static holder
tables are never served as holdings.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import FIELD_DICTIONARIES

_METHODOLOGY = (
    "HFS reverse-lookups 13F filers by issuer/CUSIP from the local SEC 13F store "
    "(scripts/ingest_13f.py). Rows exist only when that store returns holdings for the "
    "issuer. Otherwise the response is an explicit provider_unavailable state; no static "
    "holder lists are served as holdings."
)
_INGEST_ACTION = "Run scripts/ingest_13f.py to populate the local 13F store."


@FunctionRegistry.register
class HFSFunction(BaseFunction):
    code = "HFS"
    name = "Holder Search"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "13F reverse lookup — list filers holding a given issuer / CUSIP."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None and not (params.get("issuer") or params.get("cusip")):
            raise ValueError("HFS requires a symbol, issuer, or cusip")
        issuer = params.get("issuer") or (instrument.symbol if instrument else None)
        cusip = params.get("cusip")
        quarter = params.get("quarter")
        live_requested = _truthy(params.get("live_holders") or params.get("live"))
        base_metadata: dict[str, Any] = {
            "issuer": issuer,
            "cusip": cusip,
            "quarter": quarter,
            "live_requested": live_requested,
            # The local 13F store is quarterly filings data, not a live feed.
            "live": False,
        }

        if instrument is not None and instrument.asset_class not in {AssetClass.EQUITY, AssetClass.ETF}:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "not_applicable",
                    "rows": [{
                        "filer": "not_applicable",
                        "issuer": issuer,
                        "shares": 0,
                        "market_value": 0,
                        "asset_class": instrument.asset_class.value,
                    }],
                    "issuer": issuer,
                    "quarter": quarter or "latest",
                    "methodology": _METHODOLOGY,
                    "field_dictionary": FIELD_DICTIONARIES["holders"],
                    "next_actions": [],
                },
                sources=["sec_13f"],
                metadata=base_metadata,
            )

        sec = getattr(self.deps, "sec_13f", None)
        if sec is None:
            return _unavailable(
                self.code, instrument, issuer, quarter,
                reason="The local SEC 13F store is not wired, so no holder rows can be returned.",
                sources=["sec_13f"], metadata=base_metadata, next_actions=[_INGEST_ACTION],
            )

        try:
            top_n = max(1, min(int(params.get("top_n", 30) or 30), 250))
        except (TypeError, ValueError):
            top_n = 30
        try:
            timeout_s = max(1.0, min(float(params.get("timeout", 8) or 8), 30.0))
        except (TypeError, ValueError):
            timeout_s = 8.0
        try:
            df = await asyncio.wait_for(
                sec.query_holdings_by_security(
                    cusip=cusip, issuer=issuer, quarter=quarter, top_n=top_n,
                ),
                timeout=timeout_s,
            )
        except Exception as e:
            return _unavailable(
                self.code, instrument, issuer, quarter,
                reason=f"Local 13F store lookup failed: {e}",
                sources=["sec_13f"],
                metadata={**base_metadata, "provider_errors": [f"sec_13f: {e}"]},
                next_actions=[_INGEST_ACTION, "Retry the local SEC 13F store once the lookup is available."],
            )

        rows: list[dict[str, Any]] = []
        if hasattr(df, "to_dict") and getattr(df, "empty", True) is False:
            rows = df.to_dict(orient="records")
        if not rows:
            return _unavailable(
                self.code, instrument, issuer, quarter,
                reason=(
                    f"No 13F holdings for {issuer or cusip} in the local store "
                    "(the store may be unpopulated, or the issuer is not held)."
                ),
                sources=["sec_13f"], metadata=base_metadata, next_actions=[_INGEST_ACTION],
            )

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": rows,
                "issuer": issuer,
                "quarter": quarter or "latest",
                "methodology": _METHODOLOGY,
                "field_dictionary": FIELD_DICTIONARIES["holders"],
                "next_actions": [],
            },
            sources=["sec_13f"],
            metadata={**base_metadata, "rows": len(rows), "store": "local_sec_13f"},
        )


def _unavailable(
    code: str,
    instrument: Instrument | None,
    issuer: str | None,
    quarter: str | None,
    *,
    reason: str,
    sources: list[str],
    metadata: dict[str, Any],
    next_actions: list[str],
) -> FunctionResult:
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "status": "provider_unavailable",
            "rows": [],
            "issuer": issuer,
            "quarter": quarter or "latest",
            "reason": reason,
            "methodology": _METHODOLOGY,
            "field_dictionary": FIELD_DICTIONARIES["holders"],
            "next_actions": next_actions,
        },
        sources=sources,
        metadata=metadata,
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
