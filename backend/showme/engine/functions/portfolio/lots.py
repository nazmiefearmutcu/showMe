"""LOTS — Tax lot ledger function.

Param 'action' = "list" | "open" | "sell" | "summary"
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
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


def _parse_acquired_at(raw: Any) -> tuple[datetime | None, str | None]:
    """Acquisition date for action=open: (moment, problem).

    Accepts an ISO date (YYYY-MM-DD, taken as UTC midnight) or an ISO datetime.
    An empty value means "not supplied" (no problem). A future or unparseable
    date is a problem: the lot must not be written with a wrong holding period.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    text = str(raw).strip()
    try:
        if len(text) == 10:
            moment = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            moment = moment.astimezone(timezone.utc)
    except ValueError:
        return None, "acquired_at must be an ISO date (YYYY-MM-DD) or datetime"
    if moment > datetime.now(timezone.utc):
        return None, "acquired_at cannot be in the future"
    return moment, None


def _lot_ids(raw: Any) -> list[str]:
    """lot_ids as a list: accepts a list/tuple or a comma-separated string."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items: list[Any] = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        items = [raw]
    return [str(item).strip() for item in items if str(item).strip()]


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
        # Review of LOTS#1: when the caller chose no symbol the router injects a
        # default one and flags it __explicit_symbol=False. That symbol must
        # never narrow the list (the user would see an empty or partial
        # ledger) and must never receive a lot.
        if params.get("__explicit_symbol", True) is False and not str(params.get("symbol") or "").strip():
            symbol = None
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
            # LOTS#3: the acquisition date drives holding_days and the short/long
            # term split, so the caller must be able to set it. A date that is
            # in the future or unparseable is rejected before any write.
            raw_acquired = params.get("acquired_at")
            if raw_acquired in (None, ""):
                raw_acquired = params.get("opened_at")
            acquired, problem = _parse_acquired_at(raw_acquired)
            if problem:
                return _input_error(f"open: {problem}; no lot was written.", ["acquired_at"])
            stamp = acquired or datetime.now(timezone.utc)
            lot_id = tax_lots.open_lot(
                symbol=symbol,
                quantity=quantity,
                price=price,
                opened_at=stamp,
                account=params.get("account") or "main",
            )
            data: dict[str, Any] = {
                "lot_id": lot_id,
                "action": "open",
                "symbol": symbol,
                "acquired_at": stamp.isoformat(),
                "acquired_at_source": "supplied" if acquired else "entry_time",
                "warnings": [],
            }
            if acquired is None:
                data["warnings"] = [
                    "acquired_at was not supplied: the lot is stamped with the entry time, "
                    "so its holding period and short/long term are not historical until it is set."
                ]
            return FunctionResult(code=self.code, instrument=None, data=data,
                                  sources=["local_tax_lot_ledger"])
        if action == "sell":
            # LOTS#4: named lot_ids select exactly those lots. The service only
            # honours them under method=SPECIFIC, so naming lots switches to
            # SPECIFIC; otherwise FIFO would silently ignore the caller's choice.
            lot_ids = _lot_ids(params.get("lot_ids"))
            method = "SPECIFIC" if lot_ids else params.get("method", "FIFO")
            # LOTS#6: the short/long cutoff is an input; an invalid value is
            # rejected rather than silently replaced by the default.
            raw_threshold = params.get("long_term_threshold_days")
            if raw_threshold in (None, ""):
                threshold = tax_lots.DEFAULT_LONG_TERM_DAYS
            else:
                parsed = _number(raw_threshold)
                if parsed is None or parsed < 1 or parsed != int(parsed):
                    return _input_error(
                        "sell needs long_term_threshold_days as a whole number of days >= 1; no lot was sold.",
                        ["long_term_threshold_days"],
                    )
                threshold = int(parsed)
            res = tax_lots.sell(
                symbol=symbol,
                quantity=quantity,
                price=price,
                method=method,
                account=params.get("account"),
                specific_lot_ids=lot_ids or None,
                long_term_days=threshold,
            )
            if lot_ids:
                res["method_note"] = "lot_ids were given, so the lots were selected by id (SPECIFIC); the method input was not used."
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
