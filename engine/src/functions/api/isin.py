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
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["ids required (or pass instrument)"])
        if not self.deps.openfigi:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["no openfigi adapter"])
        id_type = (params.get("id_type") or "").upper()
        out: list[dict[str, Any]] = []
        for v in ids:
            t = id_type or _detect_id_type(v)
            try:
                rows = await self.deps.openfigi.lookup_by(id_type=t, id_value=v)
            except Exception as e:
                rows = []
                out.append({"input": v, "id_type": t, "error": str(e),
                            "matches": []})
                continue
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
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={"items": out, "n": len(out)},
            sources=["openfigi"],
        )
