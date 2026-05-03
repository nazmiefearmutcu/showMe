"""DCFS — DCF sensitivity grid + tornado.

Plan §26.2 bonus.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.functions.equity.dcf import DCFFunction


@FunctionRegistry.register
class DCFSensitivityFunction(BaseFunction):
    code = "DCFS"
    name = "DCF Sensitivity"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "WACC × terminal-growth grid + ±20% input tornado."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("DCFS requires instrument")
        wacc_range = params.get("wacc_range") or [0.05, 0.07, 0.08, 0.09, 0.10, 0.12]
        g_range    = params.get("g_range")    or [0.01, 0.02, 0.025, 0.03, 0.035]
        base = DCFFunction(self.deps)
        base_params = {
            "wacc": params.get("wacc", 0.09),
            "fcfe": params.get("fcfe", 10_000_000_000),
            "shares_outstanding": params.get("shares_outstanding", 15_000_000_000),
            "years": int(params.get("years", 5)),
            "growth_high": float(params.get("growth_high", 0.08)),
        }
        if params.get("live_valuation"):
            try:
                base_res = await asyncio.wait_for(
                    base.execute(instrument, **base_params),
                    timeout=max(2.0, min(float(params.get("valuation_timeout", 4)), 8.0)),
                )
            except Exception:
                base_res = await base.execute(instrument, **base_params)
        else:
            base_res = await base.execute(instrument, **base_params)
        base_data = base_res.data or {}
        shared = {
            "wacc": base_data.get("wacc"),
            "fcfe": base_data.get("starting_fcfe"),
            "shares_outstanding": base_data.get("shares_outstanding"),
        }
        shared = {k: v for k, v in shared.items() if v is not None}
        grid: list[dict[str, Any]] = []
        for w in wacc_range:
            for g in g_range:
                try:
                    r = await base.execute(instrument, **base_params, **shared, wacc=w, growth_terminal=g,
                                            years=int(params.get("years", 5)),
                                            growth_high=float(params.get("growth_high", 0.08)))
                    grid.append({
                        "wacc": w, "g_terminal": g,
                        "fair_value_per_share": (r.data or {}).get("fair_value_per_share"),
                        "equity_value": (r.data or {}).get("equity_value"),
                    })
                except Exception:
                    grid.append({"wacc": w, "g_terminal": g,
                                  "fair_value_per_share": None})
        # Tornado: which input has biggest effect at ±20% perturbation
        base_fv = base_data.get("fair_value_per_share")
        tornado: list[dict[str, Any]] = []
        if base_fv is not None and base_fv > 0:
            label_to_key = [
                ("wacc",       "wacc"),
                ("g_terminal", "growth_terminal"),
                ("g_high",     "growth_high"),
                ("years",      "years"),
                ("fcfe",       "fcfe"),
            ]
            for label, key in label_to_key:
                base_v = base_data.get(
                    key if key != "fcfe" else "starting_fcfe"
                ) or 0
                if base_v == 0:
                    continue
                try:
                    low = await base.execute(instrument, **base_params, **shared, **{key: base_v * 0.8})
                    high = await base.execute(instrument, **base_params, **shared, **{key: base_v * 1.2})
                    lv = (low.data or {}).get("fair_value_per_share")
                    hv = (high.data or {}).get("fair_value_per_share")
                    tornado.append({
                        "input": label,
                        "low_value":  base_v * 0.8,
                        "high_value": base_v * 1.2,
                        "low_fv": lv, "high_fv": hv,
                        "delta": (hv or 0) - (lv or 0),
                    })
                except Exception:
                    continue
            tornado.sort(key=lambda x: abs(x.get("delta") or 0), reverse=True)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "base_fair_value": base_fv,
                "wacc_range": wacc_range, "g_range": g_range,
                "grid": grid, "tornado": tornado,
            },
            sources=base_res.sources,
        )
