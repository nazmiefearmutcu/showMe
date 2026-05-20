"""ISIN — Cross-reference any identifier (ISIN/CUSIP/SEDOL/Ticker) via OpenFIGI."""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


_ID_TYPES = ("ID_ISIN", "ID_CUSIP", "ID_SEDOL", "TICKER", "ID_BB_GLOBAL")


def _isin_check_digit(s: str) -> bool:
    """Luhn-like check digit for 12-char ISIN identifiers."""
    if len(s) != 12 or not s[-1].isdigit():
        return False
    digits = ""
    for ch in s[:-1]:
        if ch.isdigit():
            digits += ch
        elif ch.isalpha():
            digits += str(ord(ch) - 55)
        else:
            return False
    total = 0
    for idx, ch in enumerate(reversed(digits)):
        n = int(ch)
        if idx % 2 == 0:
            n *= 2
            if n >= 10:
                n -= 9
        total += n
    check = (10 - (total % 10)) % 10
    return check == int(s[-1])


def _detect_id_type(s: str) -> str:
    s = s.strip().upper()
    if not s:
        return "TICKER"
    # ISIN: 12 chars, 2 alpha country prefix + 9 alnum + 1 numeric check
    if (
        len(s) == 12
        and s[:2].isalpha()
        and s[2:11].isalnum()
        and s[-1].isdigit()
        and _isin_check_digit(s)
    ):
        return "ID_ISIN"
    # CUSIP: 9 alphanumeric chars with a numeric check digit at the end.
    # CUSIPs may be all-digit (e.g. AAPL = 037833100) or contain letters,
    # so do not require an alpha character — just check the structural
    # pattern: 9 alnum + last digit + at least one digit in the prefix.
    if (
        len(s) == 9
        and s.isalnum()
        and s[-1].isdigit()
        and any(c.isdigit() for c in s[:-1])
    ):
        return "ID_CUSIP"
    # SEDOL: 7 chars, last numeric, no vowels in the first 6 (UK convention)
    if (
        len(s) == 7
        and s.isalnum()
        and s[-1].isdigit()
        and not any(c in "AEIOU" for c in s[:6])
    ):
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
