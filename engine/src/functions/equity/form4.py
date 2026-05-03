"""FORM4 — SEC Form 4 (insider transactions) calendar."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class FORM4Function(BaseFunction):
    code = "FORM4"
    name = "Insider Transactions"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Recent SEC Form 4 (insider) filings for the given ticker."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (instrument.symbol if instrument else
               params.get("symbol") or "").upper()
        if not sym:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["symbol required"])
        if not self.deps.sec_edgar:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_fallback_form4(sym),
                                  sources=["form4_model"])
        try:
            rows = await asyncio.wait_for(
                self.deps.sec_edgar.form4_filings(sym, limit=int(params.get("limit", 40))),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception as e:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_fallback_form4(sym),
                                  sources=["form4_model"],
                                  metadata={"provider_errors": [f"sec_edgar: {e}"]})
        # Aggregate counts
        by_month: dict[str, int] = {}
        for r in rows:
            d = (r.get("filingDate") or "")[:7]   # YYYY-MM
            if d:
                by_month[d] = by_month.get(d, 0) + 1
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "symbol": sym,
                "n": len(rows),
                "filings": rows,
                "by_month": [
                    {"month": k, "count": v}
                    for k, v in sorted(by_month.items(), reverse=True)
                ],
            },
            sources=["sec_edgar"],
        )


def _fallback_form4(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "n": 0,
        "filings": [{"filingDate": None, "reportingOwner": None, "status": "provider_unavailable"}],
        "by_month": [],
    }
