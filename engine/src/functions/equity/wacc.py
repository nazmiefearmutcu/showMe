"""WACC — Weighted Average Cost of Capital.

WACC = (E/V × Re) + (D/V × Rd × (1 − T))
- Re = CAPM: rf + β × ERP
- rf  = US 10Y FRED DGS10
- ERP = 5.0% varsayılan (Damodaran scrape Faz 4'te eklenecek)
- Rd  = FRED corporate Aaa/Baa yield
- T   = etkin vergi oranı (FA fonksiyonundan)
- E,D = balance sheet (FA fonksiyonundan)
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.functions.equity.beta import BetaFunction


@FunctionRegistry.register
class WACCFunction(BaseFunction):
    code = "WACC"
    name = "Weighted Average Cost of Capital"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("WACC requires instrument")
        erp = params.get("erp")
        warnings: list[str] = []
        sources: list[str] = []
        # Damodaran-backed country ERP if no override
        if erp is None:
            damo = getattr(self.deps, "damodaran", None)
            if damo:
                country = "US"
                try:
                    if self.deps.yfinance:
                        from src.core.base_data_source import DataKind, DataRequest
                        rd = await asyncio.wait_for(
                            self.deps.yfinance.fetch(DataRequest(
                                kind=DataKind.REFDATA, instrument=instrument
                            )),
                            timeout=float(params.get("yfinance_timeout", 8)),
                        )
                        country = rd.country or "US"
                except Exception:
                    pass
                try:
                    erp = await asyncio.wait_for(
                        damo.get_erp(country),
                        timeout=float(params.get("damodaran_timeout", 8)),
                    )
                    sources.append("damodaran")
                except Exception as e:
                    warnings.append(f"damodaran: {e}")
                    erp = 0.05
            else:
                erp = 0.05
        erp = float(erp)
        # Risk-free
        rf = float(params.get("rf")) if params.get("rf") not in (None, "") else float("nan")
        try:
            if self.deps.fred:
                df = await asyncio.wait_for(
                    self.deps.fred.series("DGS10", frequency="d"),
                    timeout=float(params.get("fred_timeout", 8)),
                )
                rf = float(df["value"].iloc[-1]) / 100.0 if not df.empty else 0.04
                sources.append("fred")
        except Exception as e:
            warnings.append(f"fred: {e}")
            rf = 0.04
        # Beta
        beta = float(params.get("beta")) if params.get("beta") not in (None, "") else 1.0
        if params.get("beta") in (None, ""):
            try:
                beta_fn = BetaFunction(self.deps)
                beta_res = await asyncio.wait_for(
                    beta_fn.execute(instrument, windows=["2Y"]),
                    timeout=float(params.get("beta_timeout", 8)),
                )
                beta = float(((beta_res.data or {}).get("betas", {}) or {}).get("2Y", {}).get("beta") or 1.0)
                sources.append("yfinance")
            except Exception as e:
                warnings.append(f"beta: {e}")
        else:
            sources.append("user_input")
        # Cost of debt — Aaa as proxy
        rd = float(params.get("rd")) if params.get("rd") not in (None, "") else 0.05
        try:
            if self.deps.fred and params.get("rd") in (None, ""):
                df = await asyncio.wait_for(
                    self.deps.fred.series("AAA", frequency="d"),
                    timeout=float(params.get("fred_timeout", 8)),
                )
                rd = float(df["value"].iloc[-1]) / 100.0 if not df.empty else 0.05
        except Exception as e:
            warnings.append(f"fred AAA: {e}")
        # Tax rate / E/V/D ratios — best-effort from yfinance
        tax = float(params.get("tax_rate")) if params.get("tax_rate") not in (None, "") else 0.21
        ev_ratio = 0.7
        dv_ratio = 0.3
        try:
            if self.deps.yfinance:
                from src.core.base_data_source import DataKind, DataRequest
                rd_data = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.REFDATA, instrument=instrument)),
                    timeout=float(params.get("yfinance_timeout", 8)),
                )
                raw = (rd_data.extras or {}).get("raw", {}) if hasattr(rd_data, "extras") else {}
                mc = raw.get("marketCap") or 0
                debt = raw.get("totalDebt") or 0
                v = (mc or 0) + (debt or 0)
                if v > 0:
                    ev_ratio = float(mc / v)
                    dv_ratio = float(debt / v)
                sources.append("yfinance")
        except Exception as e:
            warnings.append(f"yfinance ratios: {e}")
        if rf != rf:
            rf = 0.04
        re_capm = rf + beta * erp
        wacc = ev_ratio * re_capm + dv_ratio * rd * (1 - tax)
        rows = [
            {"component": "Cost of equity", "value": re_capm, "formula": "Re = rf + beta * ERP"},
            {"component": "After-tax cost of debt", "value": rd * (1 - tax), "formula": "Rd * (1 - tax_rate)"},
            {"component": "Equity weight", "value": ev_ratio, "formula": "E / (E + D)"},
            {"component": "Debt weight", "value": dv_ratio, "formula": "D / (E + D)"},
            {"component": "WACC", "value": wacc, "formula": "(E/V * Re) + (D/V * Rd * (1 - tax))"},
        ]
        surface = []
        for b in (max(0.1, beta - 0.25), beta, beta + 0.25):
            for spread in (-0.01, 0, 0.01):
                rd_case = max(0.0, rd + spread)
                re_case = rf + b * erp
                w_case = ev_ratio * re_case + dv_ratio * rd_case * (1 - tax)
                surface.append({"bucket": f"beta {b:.2f} / Rd {rd_case:.1%}", "beta": b, "rd": rd_case, "wacc": w_case})
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok",
                "wacc": float(wacc),
                "re_capm": float(re_capm),
                "rf": float(rf), "beta": float(beta), "erp": erp,
                "rd": float(rd), "tax_rate": float(tax),
                "equity_weight": ev_ratio, "debt_weight": dv_ratio,
                "rows": rows,
                "surface": surface,
                "methodology": "WACC = (E/V * Re) + (D/V * Rd * (1 - tax)). Re uses CAPM: rf + beta * ERP. E and D come from market cap and total debt when yfinance returns them; rf and Rd use FRED proxies when configured.",
                "field_dictionary": {
                    "wacc": "Weighted average cost of capital as a decimal.",
                    "re_capm": "Cost of equity from CAPM.",
                    "rf": "Risk-free rate.",
                    "erp": "Equity risk premium.",
                    "rd": "Pre-tax cost of debt proxy.",
                    "equity_weight": "Equity share of capital structure.",
                    "debt_weight": "Debt share of capital structure.",
                },
            },
            sources=sources, warnings=warnings,
        )
