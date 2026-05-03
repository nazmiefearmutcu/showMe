"""PFA — Performance Attribution (Brinson-Hood-Beebower).

Decomposition:
    Total Active Return = Allocation effect + Selection effect + Interaction

For each sector i:
    AE_i = (w_p_i − w_b_i) × (R_b_i − R_b_total)
    SE_i = w_b_i × (R_p_i − R_b_i)
    IE_i = (w_p_i − w_b_i) × (R_p_i − R_b_i)
"""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class PFAFunction(BaseFunction):
    code = "PFA"
    name = "Performance Attribution (Brinson)"
    category = "portfolio"
    description = "Brinson-Hood-Beebower attribution by sector — allocation + selection + interaction."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Inputs: portfolio weights/returns by sector, benchmark weights/returns by sector.
        # Caller can pass dicts; otherwise we use a small default sample.
        port = params.get("port_weights")     # {sector: weight}
        port_ret = params.get("port_returns")  # {sector: total return %}
        bench = params.get("bench_weights")
        bench_ret = params.get("bench_returns")
        if not all((port, port_ret, bench, bench_ret)):
            # Sample data for UI demo
            port = {"Technology": 0.45, "Financials": 0.20, "Healthcare": 0.15,
                     "Energy": 0.10, "Consumer": 0.10}
            port_ret = {"Technology": 0.18, "Financials": 0.05, "Healthcare": 0.07,
                         "Energy": -0.04, "Consumer": 0.03}
            bench = {"Technology": 0.30, "Financials": 0.18, "Healthcare": 0.18,
                     "Energy": 0.08, "Consumer": 0.10, "Industrials": 0.16}
            bench_ret = {"Technology": 0.12, "Financials": 0.04, "Healthcare": 0.05,
                          "Energy": -0.06, "Consumer": 0.02, "Industrials": 0.06}

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
            },
            sources=[],
        )
