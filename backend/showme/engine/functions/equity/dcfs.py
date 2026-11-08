"""DCFS — DCF sensitivity grid + tornado.

Plan §26.2 bonus.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DCFFunction


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
            "years": int(params.get("years", 5)),
            "growth_high": float(params.get("growth_high", 0.08)),
        }
        for key in ("wacc", "fcfe", "shares_outstanding"):
            value = params.get(key)
            if value not in (None, ""):
                base_params[key] = float(value)
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
                    grid_params = {
                        **base_params,
                        **shared,
                        "wacc": float(w),
                        "growth_terminal": float(g),
                        "years": int(params.get("years", 5)),
                        "growth_high": float(params.get("growth_high", 0.08)),
                    }
                    r = await base.execute(instrument, **grid_params)
                    grid.append({
                        "wacc": w, "g_terminal": g,
                        "fair_value_per_share": (r.data or {}).get("fair_value_per_share"),
                        "equity_value": (r.data or {}).get("equity_value"),
                        "bucket": f"WACC {float(w):.1%} / g {float(g):.1%}",
                    })
                except Exception:
                    grid.append({"wacc": w, "g_terminal": g,
                                  "fair_value_per_share": None,
                                  "bucket": f"WACC {float(w):.1%} / g {float(g):.1%}"})
        # Tornado: which input has biggest effect at ±20% perturbation
        base_fv = base_data.get("fair_value_per_share")
        tornado: list[dict[str, Any]] = []
        if base_fv is not None and base_fv > 0:
            # HNT-04 fix: the DCF payload publishes ``g_terminal``/``g_high``
            # (dcf.py output keys) — the old growth_terminal/growth_high
            # lookups always returned None → ``continue``, so the two most
            # sensitive DCF inputs silently never rendered a tornado bar.
            # The execute() PARAM names differ for the growth pair
            # (growth_terminal / growth_high), so each entry carries
            # (label, output_key, param_key) separately.
            label_to_keys = [
                ("wacc",       "wacc",          "wacc"),
                ("g_terminal", "g_terminal",    "growth_terminal"),
                ("g_high",     "g_high",        "growth_high"),
                ("years",      "years",         "years"),
                ("fcfe",       "starting_fcfe", "fcfe"),
            ]
            for label, out_key, param_key in label_to_keys:
                base_v = base_data.get(out_key) or 0
                if base_v == 0:
                    continue
                try:
                    low = await base.execute(instrument, **{**base_params, **shared, param_key: base_v * 0.8})
                    high = await base.execute(instrument, **{**base_params, **shared, param_key: base_v * 1.2})
                    lv = (low.data or {}).get("fair_value_per_share")
                    hv = (high.data or {}).get("fair_value_per_share")
                    # Skip the perturbation entirely when either endpoint failed
                    # validation (e.g. WACC * 0.8 ≤ g_terminal). Treating a
                    # missing fair-value as zero used to inflate the
                    # corresponding bar and corrupt sort order.
                    if lv is None or hv is None:
                        tornado.append({
                            "input": label,
                            "low_value":  base_v * 0.8,
                            "high_value": base_v * 1.2,
                            "low_fv": lv, "high_fv": hv,
                            "value": None,
                            "delta": None,
                            "status": "invalid_perturbation",
                            "reason": "One side of the ±20% perturbation produced no fair value (e.g. WACC fell below terminal growth).",
                        })
                        continue
                    tornado.append({
                        "input": label,
                        "low_value":  base_v * 0.8,
                        "high_value": base_v * 1.2,
                        "low_fv": lv, "high_fv": hv,
                        "value": abs(hv - lv),
                        "delta": hv - lv,
                    })
                except Exception:
                    continue
            tornado.sort(
                key=lambda x: (
                    0 if x.get("delta") is None else abs(x.get("delta") or 0)
                ),
                reverse=True,
            )
        # DCFS#1: the status must describe the base value. A negative or zero
        # fair value is not a live valuation, and the upstream DCF warnings
        # (negative free cash flow, missing shares) must reach the caller.
        warnings = list(base_res.warnings or [])
        if base_fv is None or base_fv == 0:
            status = "needs_input"
        elif base_fv < 0:
            status = "negative_value"
            warnings.append(
                "base_fair_value: the DCF implies a negative value per share at these inputs; "
                "no valuation or sensitivity grid is reported for it."
            )
        elif base_data.get("status", "ok") != "ok":
            status = "needs_input"
        else:
            status = "ok"
        # DCFS#5: echo the base assumptions the grid and tornado were computed from.
        assumptions = {
            "wacc": base_data.get("wacc"),
            "g_terminal": base_data.get("g_terminal"),
            "g_high": base_data.get("g_high"),
            "years": base_data.get("years"),
            "starting_fcfe": base_data.get("starting_fcfe"),
            "shares_outstanding": base_data.get("shares_outstanding"),
            "wacc_override": "wacc" in base_params,
            "fcfe_override": "fcfe" in base_params,
        }
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                "assumptions": assumptions,
                "base_fair_value": base_fv,
                "wacc_range": wacc_range, "g_range": g_range,
                "surface": grid,
                "grid": grid, "tornado": tornado,
                "rows": tornado or grid,
                "methodology": "DCFS runs the DCF engine across a WACC x terminal-growth grid, then perturbs key assumptions by +/-20% for a tornado sensitivity. Heatmap cells are fair value per share.",
                "field_dictionary": {
                    "fair_value_per_share": "DCF-implied value per share at the selected WACC and terminal-growth pair.",
                    "wacc": "Discount rate in the grid.",
                    "g_terminal": "Terminal growth assumption in the grid.",
                    "delta": "High-case fair value minus low-case fair value for a perturbed input.",
                },
            },
            sources=base_res.sources,
            warnings=warnings,
        )
