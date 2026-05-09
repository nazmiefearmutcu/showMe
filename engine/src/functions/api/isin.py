"""ISIN — Cross-reference any identifier (ISIN/CUSIP/SEDOL/Ticker) via OpenFIGI."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


_ID_TYPES = ("ID_ISIN", "ID_CUSIP", "ID_SEDOL", "TICKER", "ID_BB_GLOBAL")


def _detect_id_type(s: str) -> str:
    s = s.strip().upper()
    # Heuristics
    if len(s) == 12 and s[:2].isalpha() and s[2:].isalnum():
        return "ID_ISIN"
    if len(s) == 9 and s[:8].isalnum() and s[8].isalnum():
        return "ID_CUSIP"
    if len(s) == 7 and s.isalnum():
        return "ID_SEDOL"
    return "TICKER"


@FunctionRegistry.register
class ISINFunction(BaseFunction):
    code = "ISIN"
    name = "Symbol Cross-Reference"
    category = "api"
    description = "Resolve ISIN/CUSIP/SEDOL/Ticker → OpenFIGI canonical record + cross IDs."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        ids = params.get("ids") or params.get("id") or params.get("query") or []
        if isinstance(ids, str):
            ids = [s.strip() for s in ids.split(",") if s.strip()]
        if not ids and instrument:
            ids = [instrument.symbol]
        if not ids:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_required",
                    "reason": "Identifier required.",
                    "next_actions": ["Enter a ticker such as AAPL or an ISIN such as US0378331005."],
                    "rows": [],
                },
                warnings=["ids required (or pass instrument)"],
            )
        if not self.deps.openfigi:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "OpenFIGI adapter is not configured.",
                    "next_actions": ["Configure the OpenFIGI adapter or use ticker-only local symbol search."],
                    "rows": [],
                },
                sources=["openfigi"],
                warnings=["no openfigi adapter"],
            )
        id_type = (params.get("id_type") or "").upper()
        try:
            limit = max(1, min(int(params.get("limit") or 25), 100))
        except Exception:
            limit = 25
        out: list[dict[str, Any]] = []
        flat_rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for v in ids:
            t = id_type or _detect_id_type(v)
            try:
                rows = await self.deps.openfigi.lookup_by(id_type=t, id_value=v)
            except Exception as e:
                rows = []
                warning = f"{v}: {e}"
                warnings.append(warning)
                out.append({"input": v, "id_type": t, "error": str(e), "matches": []})
                continue
            match_rows = [
                {
                    "input": v,
                    "id_type": t,
                    "rank": f"#{idx + 1}",
                    "figi": r.get("figi"),
                    "ticker": r.get("ticker"),
                    "name": r.get("name"),
                    "market_sector": r.get("marketSector"),
                    "security_type": r.get("securityType"),
                    "security_type2": r.get("securityType2"),
                    "exchange": r.get("exchCode"),
                    "composite_figi": r.get("compositeFIGI"),
                    "share_class_figi": r.get("shareClassFIGI"),
                }
                for idx, r in enumerate(rows[:limit])
            ]
            flat_rows.extend(match_rows)
            out.append({
                "input": v, "id_type": t,
                "matches": [
                    {
                        "figi": r.get("figi"),
                        "ticker": r.get("ticker"),
                        "name": r.get("name"),
                        "marketSector": r.get("marketSector"),
                        "securityType": r.get("securityType"),
                        "securityType2": r.get("securityType2"),
                        "exchCode": r.get("exchCode"),
                        "compositeFIGI": r.get("compositeFIGI"),
                        "shareClassFIGI": r.get("shareClassFIGI"),
                    } for r in rows
                ],
            })
        status = "ok" if flat_rows else "empty"
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                "rows": flat_rows,
                "match_groups": out,
                "summary": {
                    "inputs": len(ids),
                    "matches": len(flat_rows),
                    "id_type": id_type or "auto",
                    "limit_per_input": limit,
                },
                "methodology": (
                    "ISIN maps the visible identifier to an OpenFIGI lookup type. "
                    "If ID Type is AUTO, ShowMe detects ISIN/CUSIP/SEDOL by length and falls back to TICKER. "
                    "Rows are flattened so each exchange-level OpenFIGI match can be inspected directly."
                ),
                "field_dictionary": {
                    "input": "Identifier entered by the user.",
                    "id_type": "OpenFIGI lookup type used for the request.",
                    "rank": "Provider match order shown as a label; it is not a metric to chart.",
                    "figi": "OpenFIGI security identifier.",
                    "composite_figi": "Composite FIGI for all trading venues where available.",
                    "share_class_figi": "FIGI representing the issuer share class.",
                    "exchange": "OpenFIGI exchange code.",
                },
                "next_actions": [] if flat_rows else ["Try ID Type TICKER for common symbols such as AAPL, MSFT, or SPY."],
            },
            sources=["openfigi"],
            warnings=warnings,
        )
