"""LOTS — Tax lot ledger function.

Param 'action' = "list" | "open" | "sell" | "summary"
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


@FunctionRegistry.register
class LOTSFunction(BaseFunction):
    code = "LOTS"
    name = "Tax Lots"
    category = "portfolio"
    description = "Open / list / sell tax lots with FIFO/LIFO/HIFO/specific-id selection."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        from showme.engine.services import tax_lots
        action = params.get("action", "list").lower()
        if action == "open":
            lot_id = tax_lots.open_lot(
                symbol=params["symbol"],
                quantity=float(params["quantity"]),
                price=float(params["price"]),
                account=params.get("account") or "main",
            )
            return FunctionResult(code=self.code, instrument=None,
                                  data={"lot_id": lot_id, "action": "open"})
        if action == "sell":
            res = tax_lots.sell(
                symbol=params["symbol"],
                quantity=float(params["quantity"]),
                price=float(params["price"]),
                method=params.get("method", "FIFO"),
                account=params.get("account"),
                specific_lot_ids=params.get("lot_ids"),
            )
            return FunctionResult(code=self.code, instrument=None, data=res)
        if action == "summary":
            year = params.get("year")
            return FunctionResult(
                code=self.code, instrument=None,
                data=tax_lots.realized_summary(year=int(year) if year else None),
            )
        # default: list
        lots = tax_lots.list_open_lots(symbol=params.get("symbol"),
                                       account=params.get("account"))
        if not lots:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty",
                    "reason": "local portfolio has no tax lots",
                    "lots": [],
                    "rows": [],
                    "count": 0,
                    "next_actions": [
                        "Add a lot with action=open or import portfolio tax lots before rerunning LOTS.",
                    ],
                    "methodology": _methodology(),
                    "field_dictionary": _field_dictionary(),
                },
                sources=["local_tax_lot_ledger"],
                warnings=[],
            )
        return FunctionResult(code=self.code, instrument=None,
                              data={"status": "ok", "lots": lots, "rows": lots, "count": len(lots),
                                    "methodology": _methodology(),
                                    "field_dictionary": _field_dictionary()},
                              sources=["local_tax_lot_ledger"])


def _methodology() -> str:
    return (
        "Maintain a local tax-lot ledger. Open creates a lot with acquisition quantity/cost; sell matches "
        "open lots by FIFO/LIFO/HIFO or specific lot IDs and records realized gain or loss."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "quantity": "Open quantity remaining in the lot.",
        "price": "Lot acquisition price or sell price depending on action.",
        "method": "Lot selection method: FIFO, LIFO, HIFO, or specific lot IDs.",
        "realized_gain": "Sale proceeds minus matched tax basis.",
    }
