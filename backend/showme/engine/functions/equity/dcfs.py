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
    description = "Discount-rate (cost of equity by default) × terminal-growth grid + ±20% input tornado."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("DCFS requires instrument")
        base = DCFFunction(self.deps)
        # DCFS#3: the manifest inputs drive the run. discount_rate (alias wacc)
        # and terminal_growth are the grid centres, growth_rate (alias
        # growth_high) the stage-1 growth, grid_width the cells per axis.
        explicit_rate = _first_number(params, "discount_rate", "wacc")
        explicit_g = _first_number(params, "terminal_growth", "growth_terminal")
        growth_high = _first_number(params, "growth_rate", "growth_high")
        base_params: dict[str, Any] = {
            "years": int(params.get("years", 5)),
            "growth_high": growth_high if growth_high is not None else 0.08,
        }
        if explicit_rate is not None:
            base_params["wacc"] = explicit_rate
        if explicit_g is not None:
            base_params["growth_terminal"] = explicit_g
        for key in ("fcfe", "shares_outstanding"):
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
            # DCFS#2: the discount rate actually applied to FCFE (cost of equity by default).
            "wacc": base_data.get("discount_rate"),
            "fcfe": base_data.get("starting_fcfe"),
            "shares_outstanding": base_data.get("shares_outstanding"),
        }
        shared = {k: v for k, v in shared.items() if v is not None}
        base_fv = base_data.get("fair_value_per_share")
        # DCFS#3/#4: the grid is centred on the effective discount rate and
        # terminal growth (50 bp / 25 bp steps), grid_width cells per axis
        # (3/5/7, default 5 -> the manifest's 25 cells). An explicit
        # wacc_range / g_range from the caller still wins.
        width = _grid_width(params.get("grid_width"))
        half = width // 2
        rate_center = explicit_rate if explicit_rate is not None else _finite(base_data.get("discount_rate"))
        g_center = explicit_g if explicit_g is not None else _finite(base_data.get("g_terminal"))
        if g_center is None:
            g_center = 0.025
        wacc_range = params.get("wacc_range") or (
            [round(rate_center + (i - half) * 0.005, 6) for i in range(width)] if rate_center is not None else []
        )
        g_range = params.get("g_range") or [
            round(max(0.0, g_center + (i - half) * 0.0025), 6) for i in range(width)
        ]
        # DCFS#1: a negative base value is not a valuation, so the grid is
        # withheld rather than published as a sensitivity surface of negatives.
        grid_withheld = base_fv is not None and base_fv < 0
        grid: list[dict[str, Any]] = []
        for w in ([] if grid_withheld else wacc_range):
            for g in g_range:
                try:
                    grid_params = {
                        **base_params,
                        **shared,
                        "wacc": float(w),
                        "growth_terminal": float(g),
                    }
                    r = await base.execute(instrument, **grid_params)
                    grid.append({
                        "wacc": w, "g_terminal": g,
                        "fair_value_per_share": (r.data or {}).get("fair_value_per_share"),
                        "equity_value": (r.data or {}).get("equity_value"),
                        "bucket": f"discount rate {float(w):.1%} / g {float(g):.1%}",
                    })
                except Exception:
                    grid.append({"wacc": w, "g_terminal": g,
                                  "fair_value_per_share": None,
                                  "bucket": f"discount rate {float(w):.1%} / g {float(g):.1%}"})
        # Tornado: which input has biggest effect at ±20% perturbation
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
                ("discount_rate", "discount_rate", "wacc"),
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
                            "reason": "One side of the ±20% perturbation produced no fair value (e.g. the discount rate fell below terminal growth).",
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
                "no sensitivity grid or tornado is reported for it."
            )
        elif base_data.get("status", "ok") != "ok":
            status = "needs_input"
        else:
            status = "ok"
        # DCFS#5: echo the base assumptions the grid and tornado were computed from.
        assumptions = {
            "wacc": base_data.get("discount_rate"),
            "discount_rate": base_data.get("discount_rate"),
            "discount_rate_data_state": base_data.get("discount_rate_data_state"),
            "erp_source": base_data.get("erp_source"),
            "wacc_reference": base_data.get("wacc"),
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
                "grid_width": width,
                "grid_center": {"discount_rate": rate_center, "terminal_growth": g_center},
                "surface": grid,
                "grid": grid, "tornado": tornado,
                "rows": tornado or grid,
                "methodology": "DCFS runs the DCF engine across a discount rate (cost of equity by default, or a caller override) x terminal-growth grid, then perturbs key assumptions by +/-20% for a tornado sensitivity. Heatmap cells are fair value per share.",
                "field_dictionary": {
                    "fair_value_per_share": "DCF-implied value per share at the selected discount rate and terminal-growth pair.",
                    "discount_rate": "Discount rate applied to FCFE in the grid: the cost of equity by default, or a caller override. Grid rows keep the value under the key wacc for compatibility.",
                    "wacc": "Same value as discount_rate in each grid row (kept for compatibility; not the WACC model's WACC).",
                    "g_terminal": "Terminal growth assumption in the grid.",
                    "delta": "High-case fair value minus low-case fair value for a perturbed input.",
                },
            },
            sources=base_res.sources,
            warnings=warnings,
        )


def _first_number(params: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = params.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number and abs(number) != float("inf"):
            return number
    return None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _grid_width(value: Any) -> int:
    try:
        width = int(float(value))
    except (TypeError, ValueError):
        return 5
    return width if width in (3, 5, 7) else 5
