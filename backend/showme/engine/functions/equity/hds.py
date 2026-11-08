"""HDS — Holders / Institutional Holdings."""

from __future__ import annotations

import asyncio
import re
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
        holder_type = str(params.get("holder_type") or "all").strip().lower()
        if holder_type not in HOLDER_TYPE_FILTERS:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_error",
                    "rows": [],
                    "reason": f"Unknown holder_type {holder_type!r}.",
                    "next_actions": [f"Use one of: {', '.join(HOLDER_TYPE_FILTERS)}."],
                    "field_dictionary": FIELD_DICTIONARIES["holders"],
                },
                sources=[],
                metadata={"live": False},
            )
        if holder_type == "insider":
            # No provider wired into HDS returns insider holder rows, so the
            # filter is reported as unavailable instead of falling back to all rows.
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "holder_type_filter": holder_type,
                    "reason": "No HDS provider supplies insider holder rows. Yahoo institutional and mutual-fund tables and local SEC 13F data are the holder sources.",
                    "next_actions": ["Choose holder_type all, institutional or mutual_fund."],
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
        # Then enrich with the SEC 13F aggregate for the issuer (DuckDB-cached).
        # 13F rows carry the issuer name, not the ticker, so the ticker is first
        # resolved to its SEC filer name and matched on the normalized name.
        sec_top: list[dict[str, Any]] = []
        sec_13f = getattr(self.deps, "sec_13f", None)
        if sec_13f:
            try:
                top = await asyncio.wait_for(
                    _query_13f_for_ticker(
                        sec_13f,
                        getattr(self.deps, "sec_edgar", None),
                        instrument.symbol,
                        top_n=int(params.get("top_n", 20)),
                    ),
                    timeout=float(params.get("sec_timeout", 8)),
                )
                if top is None:
                    warnings.append(f"sec_13f: no SEC issuer name maps to {instrument.symbol}")
                elif not top.empty:
                    sec_top = top.to_dict(orient="records")
                    sources.append("sec_13f")
            except Exception as e:
                warnings.append(f"sec_13f: {e}")
        all_rows = _holder_rows(instrument.symbol, sec_top, yahoo)
        rows = _filter_holder_type(all_rows, holder_type)
        summary = _major_summary(yahoo.get("major"))
        if rows:
            status, reason = "ok", None
        elif all_rows:
            status = "empty"
            reason = f"Holder rows exist for {instrument.symbol} but none match holder_type={holder_type}."
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
            "holder_type_filter": holder_type,
            "methodology": "HDS shows holder rows from Yahoo institutional / mutual-fund holder tables and local SEC 13F data, restricted to holder_type. Yahoo major-holder percentages are a summary block, not holder rows.",
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


HOLDER_TYPE_FILTERS: tuple[str, ...] = ("all", "institutional", "insider", "mutual_fund")

# Row holder_type values that each holder_type filter selects. 13F rows are
# typed institutional_13f and count as institutional.
_HOLDER_TYPE_MATCH: dict[str, frozenset[str]] = {
    "institutional": frozenset({"institutional", "institutional_13f"}),
    "mutual_fund": frozenset({"mutual_fund"}),
}


def _filter_holder_type(rows: list[dict[str, Any]], holder_type: str) -> list[dict[str, Any]]:
    if holder_type == "all":
        return rows
    wanted = _HOLDER_TYPE_MATCH.get(holder_type, frozenset())
    return [row for row in rows if row.get("holder_type") in wanted]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


async def _query_13f_for_ticker(sec_13f: Any, sec_edgar: Any, symbol: str, *, top_n: int) -> pd.DataFrame | None:
    """Return the 13F per-filer aggregate for ``symbol``, or None when the
    ticker has no SEC issuer name (nothing to match on, so nothing is guessed)."""
    issuer_name = await _sec_issuer_name(sec_edgar, symbol)
    if not issuer_name:
        return None
    return await sec_13f.query_holdings_by_security(
        issuer_normalized=_issuer_key(issuer_name),
        top_n=top_n,
    )


async def _sec_issuer_name(sec_edgar: Any, symbol: str) -> str | None:
    if sec_edgar is None:
        return None
    cik = await sec_edgar.cik_for(symbol)
    if not cik:
        return None
    submissions = await sec_edgar.submissions(cik)
    name = (submissions or {}).get("name") if isinstance(submissions, dict) else None
    return str(name).strip() if name else None


def _issuer_key(name: str) -> str:
    """Same normalization the 13F adapter applies to nameOfIssuer."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


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


def _fraction_of_outstanding(value: Any) -> float | None:
    """yfinance ``pctHeld`` is a fraction of shares outstanding (0.08 = 8%).

    Only values inside [0, 1] are kept; anything else is reported as missing
    rather than rescaled.
    """
    out = finite(value)
    if out is None or out < 0 or out > 1:
        return None
    return out


def _holder_rows(symbol: str, sec_top: list[dict[str, Any]], yahoo: dict[str, Any]) -> list[dict[str, Any]]:
    if sec_top:
        rows = []
        for item in sec_top:
            # Field names follow SEC13FAdapter.query_holdings_by_security:
            # filer_cik, report_date, shares, and value_usd (always NULL: the
            # InfoTable unit is unresolved, so no dollar value is shown).
            # The local store keeps no filer name, so the holder is labelled by its CIK.
            filer_cik = item.get("filer_cik")
            rows.append({
                "symbol": symbol,
                "holder": f"CIK {filer_cik}" if filer_cik else (item.get("filer") or item.get("holder")),
                "holder_type": "institutional_13f",
                "shares": finite(item.get("shares")),
                "market_value": None,
                "market_value_status": "unit_unresolved",
                "quarter": item.get("report_date") or None,
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
                "pct_outstanding": _fraction_of_outstanding(
                    item.get("pctHeld", item.get("% Out", item.get("pct_outstanding")))
                ),
                "market_value": finite(item.get("Value") or item.get("value")),
                "date_reported": item.get("Date Reported") or item.get("date_reported"),
                "source_mode": "yfinance_holders",
            })
    return rows
