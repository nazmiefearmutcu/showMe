"""PFA — Performance Attribution (Brinson-Hood-Beebower).

Decomposition:
    Total Active Return = Allocation effect + Selection effect + Interaction

For each sector i:
    AE_i = (w_p_i − w_b_i) × (R_b_i − R_b_total)
    SE_i = w_b_i × (R_p_i − R_b_i)
    IE_i = (w_p_i − w_b_i) × (R_p_i − R_b_i)
"""

from __future__ import annotations

import math
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

# Weights must sum to 100% on each side. The Brinson identity
# (allocation + selection + interaction = active return) only holds for fully
# invested weights; anything else leaves an unexplained residual.
_WEIGHT_SUM_TOLERANCE = 1e-4


def _input_state(status: str, reason: str, next_actions: list[str]) -> FunctionResult:
    """Explicit non-result: no rows, no totals, no headline."""
    return FunctionResult(
        code="PFA", instrument=None,
        data={"status": status, "reason": reason, "next_actions": next_actions,
              "rows": [], "totals": {}, "summary": {}},
        sources=[],
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_maps(port: Any, port_ret: Any, bench: Any, bench_ret: Any) -> str | None:
    """Return a reason string when the inputs cannot reconcile, else None."""
    named = (("port_weights", port), ("port_returns", port_ret),
             ("bench_weights", bench), ("bench_returns", bench_ret))
    for name, value in named:
        if not isinstance(value, dict):
            return f"{name} must be a mapping of sector to number."
        if not all(_is_number(v) for v in value.values()):
            return f"{name} contains a non-numeric value."
    for name, weights in (("port", port), ("bench", bench)):
        total = sum(weights.values())
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            return (f"{name}_weights sum to {total * 100:.4f}%, not 100%; the attribution "
                    "effects would not reconcile to the active return.")
    for name, weights, returns in (("port", port, port_ret), ("bench", bench, bench_ret)):
        for sector, weight in weights.items():
            if weight != 0 and sector not in returns:
                return f"{sector} has a {name} weight but no {name}_returns entry."
    return None


@FunctionRegistry.register
class PFAFunction(BaseFunction):
    code = "PFA"
    name = "Performance Attribution (Brinson)"
    category = "portfolio"
    description = "Brinson-Hood-Beebower attribution by sector — allocation + selection + interaction."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Inputs: portfolio weights/returns by sector, benchmark weights/returns by sector,
        # as {sector: fraction}. No sample is substituted: missing or inconsistent inputs
        # return an explicit state with no headline (P1a-g12 PFA#1 / PFA#2).
        port = params.get("port_weights")     # {sector: weight}
        port_ret = params.get("port_returns")  # {sector: total return}
        bench = params.get("bench_weights")
        bench_ret = params.get("bench_returns")
        if not all((port, port_ret, bench, bench_ret)):
            missing = [name for name, value in (
                ("port_weights", port), ("port_returns", port_ret),
                ("bench_weights", bench), ("bench_returns", bench_ret)) if not value]
            return _input_state(
                "input_required",
                "Brinson attribution needs portfolio and benchmark weights and returns by sector "
                f"(missing: {', '.join(missing)}). No sample is computed.",
                ["Enter port weights, port returns, bench weights and bench returns as Sector: percent pairs."],
            )

        problem = _validate_maps(port, port_ret, bench, bench_ret)
        if problem is not None:
            return _input_state("input_error", problem,
                                ["Correct the sector weights/returns so each side sums to 100% "
                                 "and every weighted sector has a return."])

        sectors = sorted(set(port) | set(bench))
        # Total benchmark return
        rb_total = sum(bench.get(s, 0) * bench_ret.get(s, 0) for s in sectors)
        rp_total = sum(port.get(s, 0) * port_ret.get(s, 0) for s in sectors)
        rows = []
        ae_total = se_total = ie_total = 0.0
        for s in sectors:
            wp = port.get(s, 0)
            wb = bench.get(s, 0)
            rp = port_ret.get(s, 0)
            rb = bench_ret.get(s, 0)
            ae = (wp - wb) * (rb - rb_total)
            se = wb * (rp - rb)
            ie = (wp - wb) * (rp - rb)
            ae_total += ae; se_total += se; ie_total += ie
            rows.append({
                "sector": s, "port_weight": wp, "bench_weight": wb,
                "port_return": rp, "bench_return": rb,
                "allocation_effect": ae,
                "selection_effect": se,
                "interaction_effect": ie,
                "total_effect": ae + se + ie,
            })
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "rows": rows,
                "totals": {
                    "portfolio_return": rp_total,
                    "benchmark_return": rb_total,
                    "active_return": rp_total - rb_total,
                    "allocation": ae_total,
                    "selection": se_total,
                    "interaction": ie_total,
                },
                "summary": {
                    "active_return": rp_total - rb_total,
                    "allocation": ae_total,
                    "selection": se_total,
                    "interaction": ie_total,
                    "sectors": len(rows),
                },
                "methodology": (
                    "Brinson-Hood-Beebower attribution: active return is decomposed by sector into "
                    "allocation, selection, and interaction effects using portfolio and benchmark "
                    "weights and sector returns."
                ),
                "field_dictionary": {
                    "allocation_effect": "(portfolio_weight - benchmark_weight) * (benchmark_sector_return - benchmark_total_return).",
                    "selection_effect": "benchmark_weight * (portfolio_sector_return - benchmark_sector_return).",
                    "interaction_effect": "(portfolio_weight - benchmark_weight) * (portfolio_sector_return - benchmark_sector_return).",
                    "total_effect": "Allocation + selection + interaction for the sector.",
                },
            },
            sources=["brinson_model"],
        )
