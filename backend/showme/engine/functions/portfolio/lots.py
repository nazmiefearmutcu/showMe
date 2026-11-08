"""LOTS — Tax lot ledger function.

Param 'action' = "list" | "open" | "sell" | "summary"
"""

from __future__ import annotations

import math
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


def _symbol(params: dict[str, Any], instrument: Instrument | None) -> str | None:
    """Symbol from params, else from the routed instrument.

    The generic /api/fn route pops ``symbol`` out of the params and passes it on
    as ``instrument``, so the instrument is the fallback, not an error.
    """
    raw = params.get("symbol")
    if raw is None or not str(raw).strip():
        raw = getattr(instrument, "symbol", None)
    text = str(raw or "").strip()
    return text or None


def _number(raw: Any) -> float | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _input_error(reason: str, missing: list[str]) -> FunctionResult:
    return FunctionResult(
        code="LOTS",
        instrument=None,
        data={
            "status": "input_error",
            "reason": reason,
            "missing": missing,
            "next_actions": [
                "Pass symbol, quantity and price for action=open or action=sell.",
            ],
            "methodology": _methodology(),
            "field_dictionary": _field_dictionary(),
        },
        sources=["local_tax_lot_ledger"],
        warnings=[],
    )


@FunctionRegistry.register
class LOTSFunction(BaseFunction):
    code = "LOTS"
    name = "Tax Lots"
    category = "portfolio"
    description = "Open / list / sell tax lots with FIFO/LIFO/HIFO/specific-id selection."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        from showme.engine.services import tax_lots
        action = str(params.get("action", "list") or "list").lower()
        symbol = _symbol(params, instrument)
        quantity = _number(params.get("quantity"))
        price = _number(params.get("price"))
        if action in ("open", "sell"):
            missing = [
                name for name, value in (("symbol", symbol), ("quantity", quantity), ("price", price))
                if value in (None, "")
            ]
            if missing:
                # Nothing is written: the ledger changes only on a complete input.
                return _input_error(
                    f"{action} needs {', '.join(missing)} as numeric input; no lot was written.",
                    missing,
                )
            # A zero or negative quantity (or a negative price) would be written
            # or sold as an invisible or nonsensical row, so reject it up front.
            invalid = []
            if quantity <= 0:
                invalid.append("quantity")
            if price < 0:
                invalid.append("price")
            if invalid:
                return _input_error(
                    f"{action} needs quantity > 0 and price >= 0; no lot was written.",
                    invalid,
                )
        if action == "open":
            lot_id = tax_lots.open_lot(
                symbol=symbol,
                quantity=quantity,
                price=price,
                account=params.get("account") or "main",
            )
            return FunctionResult(code=self.code, instrument=None,
                                  data={"lot_id": lot_id, "action": "open", "symbol": symbol})
        if action == "sell":
            res = tax_lots.sell(
                symbol=symbol,
                quantity=quantity,
                price=price,
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
        lots = tax_lots.list_open_lots(symbol=symbol,
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
