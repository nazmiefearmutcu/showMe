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
import re
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
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$", re.IGNORECASE)
_REPORT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_QUARTER_END = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}


def _report_date_prefix(quarter: str | None) -> tuple[str | None, str | None]:
    """Map a quarter input to the store's report_date text, or an error reason.

    The 13F store keeps report_date as the SEC period date (``2026-06-30``), so
    ``2026-Q2`` becomes that date. A full ``YYYY-MM-DD`` report date is used as
    given. Anything else is refused, not passed on to match nothing.
    """
    text = str(quarter or "").strip()
    if not text:
        return None, None
    match = _QUARTER_RE.match(text)
    if match:
        return f"{match.group(1)}-{_QUARTER_END[match.group(2)]}", None
    if _REPORT_DATE_RE.match(text):
        return text, None
    return None, f"quarter must be YYYY-Q# (for example 2026-Q2) or a report date YYYY-MM-DD; got {quarter!r}."


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
                    "rows": [],
                    "issuer": issuer,
                    "quarter": quarter or "latest",
                    "reason": (
                        f"Holder search applies to equity and ETF issuers only; "
                        f"{instrument.asset_class.value} instruments have no 13F holders."
                    ),
                    "methodology": _METHODOLOGY,
                    "field_dictionary": FIELD_DICTIONARIES["holders"],
                    "next_actions": [],
                },
                sources=[],
                metadata=base_metadata,
            )

        # HFS#2: refuse inputs the store cannot honour instead of ignoring them.
        # The local store has no filer classification, so only filer_type=all applies.
        filer_type = str(params.get("filer_type") or "all").strip().lower()
        if filer_type != "all":
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_error",
                    "field": "filer_type",
                    "reason": (
                        f"The local 13F store does not classify filers, so filer_type={filer_type} "
                        "cannot be applied. No rows are returned rather than unfiltered rows labelled "
                        f"{filer_type}."
                    ),
                    "rows": [],
                    "issuer": issuer,
                    "quarter": quarter or "latest",
                    "methodology": _METHODOLOGY,
                    "field_dictionary": FIELD_DICTIONARIES["holders"],
                    "next_actions": ["Set filer_type to all."],
                },
                sources=[],
                metadata=base_metadata,
            )
        report_date, quarter_error = _report_date_prefix(quarter)
        if quarter_error is not None:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_error",
                    "field": "quarter",
                    "reason": quarter_error,
                    "rows": [],
                    "issuer": issuer,
                    "quarter": quarter,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": FIELD_DICTIONARIES["holders"],
                    "next_actions": ["Pass quarter as YYYY-Q# (for example 2026-Q2), or leave it empty."],
                },
                sources=[],
                metadata=base_metadata,
            )

        sec = getattr(self.deps, "sec_13f", None)
        if sec is None:
            return _unavailable(
                self.code, instrument, issuer, quarter,
                reason="The local SEC 13F store is not wired, so no holder rows can be returned.",
                sources=[], metadata=base_metadata, next_actions=[_INGEST_ACTION],
            )

        try:
            top_n = max(1, min(int(params.get("top_n", 30) or 30), 250))
        except (TypeError, ValueError):
            top_n = 30
        try:
            timeout_s = max(1.0, min(float(params.get("timeout", 8) or 8), 30.0))
        except (TypeError, ValueError):
            timeout_s = 8.0
        # cusip takes precedence over the symbol (hfs_seed): a bound ticker must not
        # also filter the CUSIP rows, because the store matches issuer names, not tickers.
        query_issuer = None if cusip else issuer
        try:
            df = await asyncio.wait_for(
                sec.query_holdings_by_security(
                    cusip=cusip, issuer=query_issuer, quarter=report_date, top_n=top_n,
                ),
                timeout=timeout_s,
            )
        except Exception as e:
            return _unavailable(
                self.code, instrument, issuer, quarter,
                reason=f"Local 13F store lookup failed: {str(e) or type(e).__name__}",
                sources=[],
                metadata={**base_metadata, "provider_errors": [f"sec_13f: {str(e) or type(e).__name__}"]},
                next_actions=[_INGEST_ACTION, "Retry the local SEC 13F store once the lookup is available."],
            )

        rows: list[dict[str, Any]] = []
        if hasattr(df, "to_dict") and getattr(df, "empty", True) is False:
            rows = df.to_dict(orient="records")
        if not rows:
            scope = f" in quarter {quarter}" if quarter else ""
            return _unavailable(
                self.code, instrument, issuer, quarter,
                reason=(
                    f"No 13F holdings for {issuer or cusip}{scope} in the local store "
                    "(the store may be unpopulated, or the issuer is not held)."
                ),
                sources=[], metadata=base_metadata, next_actions=[_INGEST_ACTION],
            )

        # Without a quarter the store returns every ingested report date, so the
        # label must name the real date(s) and say when they differ (HFS#2).
        report_dates = sorted({str(r["report_date"]) for r in rows if r.get("report_date")})
        warnings: list[str] = []
        if quarter:
            quarter_label = str(quarter).strip().upper()
        else:
            quarter_label = report_dates[-1] if report_dates else "latest"
            if len(report_dates) > 1:
                warnings.append(
                    f"Rows span report dates {report_dates[0]} to {report_dates[-1]}; "
                    "pass quarter=YYYY-Q# to show one quarter. Each row carries its own report_date."
                )

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": rows,
                "issuer": issuer,
                "quarter": quarter_label,
                "methodology": _METHODOLOGY,
                "field_dictionary": FIELD_DICTIONARIES["holders"],
                "next_actions": [],
            },
            sources=["sec_13f"],
            warnings=warnings,
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
