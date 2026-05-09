"""GREEKS — Portfolio-level options Greeks aggregation."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.services import greeks as greeks_svc


@FunctionRegistry.register
class GREEKSFunction(BaseFunction):
    code = "GREEKS"
    name = "Portfolio Greeks"
    category = "portfolio"
    description = "Sum delta/gamma/vega/theta/rho across an option book."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        positions = params.get("positions") or []
        if not positions:
            return FunctionResult(code=self.code, instrument=None,
                                  data={"delta": 0, "gamma": 0, "vega": 0, "theta": 0,
                                        "rho": 0, "positions": 0,
                                        "rows": [],
                                        "status": "ready_no_option_positions",
                                        "reason": "No option positions were supplied or found in the local option book.",
                                        "next_actions": [
                                            "Pass positions with qty, type, spot, strike, expiry, vol, and rate.",
                                            "Use OSA/OVME for single-strategy or single-contract assumptions.",
                                        ],
                                        "methodology": _methodology(),
                                        "field_dictionary": _field_dictionary()},
                                  sources=["empty_book"])
        try:
            agg = greeks_svc.aggregate_book(positions)
        except Exception as e:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=[f"aggregate: {e}"])
        rows = _rows_from_positions(positions)
        data = {
            **agg,
            "rows": rows,
            "summary": {
                "positions": len(positions),
                "delta": agg.get("delta"),
                "gamma": agg.get("gamma"),
                "vega": agg.get("vega"),
                "theta": agg.get("theta"),
                "rho": agg.get("rho"),
            },
            "methodology": _methodology(),
            "field_dictionary": _field_dictionary(),
        }
        return FunctionResult(code=self.code, instrument=None, data=data,
                              sources=["greeks"])


def _rows_from_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, pos in enumerate(positions, start=1):
        row = dict(pos)
        row.setdefault("label", f"{row.get('symbol', 'OPT')} #{idx}")
        row.setdefault("quantity", row.get("qty", row.get("quantity", 1)))
        row.setdefault("contract_size", row.get("multiplier", row.get("contract_size", 100)))
        rows.append(row)
    return rows


def _methodology() -> str:
    return (
        "Aggregate contract-level Black-Scholes Greeks across the option book. Each row is scaled by "
        "quantity and contract size; portfolio delta/gamma/vega/theta/rho are the sums across positions."
    )


def _field_dictionary() -> dict[str, str]:
    return {
        "delta": "Change in option value for a one-unit spot move.",
        "gamma": "Change in delta for a one-unit spot move.",
        "vega": "Change in option value for a 1.00 volatility-point move.",
        "theta": "Time decay per year under the Black-Scholes convention used by the service.",
        "rho": "Change in option value for a 1.00 rate move.",
        "contract_size": "Multiplier applied to per-contract Greeks.",
    }
