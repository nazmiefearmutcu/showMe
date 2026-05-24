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

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.beta import BetaFunction


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
                        from showme.engine.core.base_data_source import DataKind, DataRequest
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
        # Beta — Bug #17: never silently fall back to 1.0 without labelling.
        #
        # The WACC pane reported β=1.0 for AAPL while the dedicated BETA
        # pane reported β=1.20 (5Y window). Two adapters, two truths in one
        # cockpit. Fix: always share the BetaFunction adapter, prefer the
        # longest window the user asked for (defaults to 5Y, then 2Y, then
        # 1Y) and, if we *do* fall through to 1.0, mark the response with
        # ``data_state: "synthetic_beta"`` so the UI can pill it.
        beta_source: str = "user_input"
        beta_window_used: str | None = None
        beta_data_state: str = "live"
        if params.get("beta") not in (None, ""):
            beta = float(params.get("beta"))
            sources.append("user_input")
        else:
            # Anything other than a successful BetaFunction window lands us
            # in synthetic territory — flip the source label up front so the
            # exception/empty branches don't need to remember to.
            beta_source = "synthetic_beta"
            beta = 1.0
            try:
                beta_fn = BetaFunction(self.deps)
                # Request 5Y/2Y/1Y so the BetaFunction returns whichever
                # window has enough history; prefer the long window when it
                # came back populated (matches what the BETA pane displays).
                beta_res = await asyncio.wait_for(
                    beta_fn.execute(instrument, windows=["5Y", "2Y", "1Y"]),
                    timeout=float(params.get("beta_timeout", 8)),
                )
                betas = ((beta_res.data or {}).get("betas") or {})
                resolved: float | None = None
                for window in ("5Y", "2Y", "1Y"):
                    entry = betas.get(window) if isinstance(betas, dict) else None
                    if isinstance(entry, dict):
                        candidate = entry.get("beta")
                        if isinstance(candidate, (int, float)) and float(candidate) == float(candidate):
                            resolved = float(candidate)
                            beta_window_used = window
                            break
                if resolved is not None:
                    beta = resolved
                    beta_source = f"beta_{beta_window_used.lower()}" if beta_window_used else "beta"
                    sources.append("beta")
                else:
                    # BetaFunction returned but had no usable window (e.g. it
                    # took the deterministic _beta_baseline path because
                    # yfinance failed). Surface that honestly.
                    beta_data_state = "synthetic_beta"
                    warnings.append(
                        "beta unavailable: BetaFunction returned no live window; "
                        "WACC is using a synthetic β=1.0"
                    )
                    sources.append("synthetic_beta")
            except Exception as e:
                beta_data_state = "synthetic_beta"
                warnings.append(f"beta: {e}; WACC is using a synthetic β=1.0")
                sources.append("synthetic_beta")
        # Cost of debt — audit Q3 #17:
        # 1) Prefer issuer-specific implied rate: interest_expense / total_debt
        #    when both come from yfinance fundamentals.
        # 2) Fall back to FRED BBB (BAMLC0A4CBBB) — closer to typical corp
        #    issuer than AAA, which understates by 100–300 bp.
        # 3) Last-resort fixed 0.055 (5.5%).
        rd = float(params.get("rd")) if params.get("rd") not in (None, "") else None
        rd_source = "user_input" if rd is not None else None
        if rd is None and self.deps.yfinance:
            try:
                from showme.engine.core.base_data_source import DataKind, DataRequest
                rd_data = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.REFDATA, instrument=instrument)),
                    timeout=float(params.get("yfinance_timeout", 8)),
                )
                raw = (rd_data.extras or {}).get("raw", {}) if hasattr(rd_data, "extras") else {}
                interest_expense = raw.get("interestExpense") or raw.get("interest_expense")
                total_debt = raw.get("totalDebt") or raw.get("total_debt")
                if interest_expense and total_debt and float(total_debt) > 0:
                    implied = abs(float(interest_expense)) / float(total_debt)
                    if 0.005 < implied < 0.30:
                        rd = float(implied)
                        rd_source = "issuer_implied"
            except Exception as e:
                warnings.append(f"yfinance implied rd: {e}")
        if rd is None:
            try:
                if self.deps.fred:
                    df = await asyncio.wait_for(
                        self.deps.fred.series("BAMLC0A4CBBB", frequency="d"),
                        timeout=float(params.get("fred_timeout", 8)),
                    )
                    if not df.empty:
                        rd = float(df["value"].iloc[-1]) / 100.0
                        rd_source = "fred_bbb"
            except Exception as e:
                warnings.append(f"fred BBB: {e}")
        if rd is None:
            try:
                if self.deps.fred:
                    df = await asyncio.wait_for(
                        self.deps.fred.series("AAA", frequency="d"),
                        timeout=float(params.get("fred_timeout", 8)),
                    )
                    if not df.empty:
                        rd = float(df["value"].iloc[-1]) / 100.0
                        rd_source = "fred_aaa"
            except Exception as e:
                warnings.append(f"fred AAA: {e}")
        if rd is None:
            rd = 0.055
            rd_source = "default"
        # Tax rate / E/V/D ratios — best-effort from yfinance
        tax = float(params.get("tax_rate")) if params.get("tax_rate") not in (None, "") else 0.21
        # Audit Q3 #16: capital-structure provenance. ``debt_value_source``
        # is "book" when sourced from totalDebt (yfinance balance sheet),
        # "market" when from a bond-price feed (not yet wired), or
        # "sector_default" / "default" when we fall back.
        debt_value_source = "default"
        capital_data_state = "default"
        sector_used: str | None = None
        ev_ratio = 0.7
        dv_ratio = 0.3
        try:
            if self.deps.yfinance:
                from showme.engine.core.base_data_source import DataKind, DataRequest
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
                    debt_value_source = "book"
                    capital_data_state = "live"
                else:
                    # Audit Q3 #18: sector-aware fallback when balance sheet
                    # is empty. Banks carry ~9:1, capital-light tech ~95:5.
                    sector = (raw.get("sector") or raw.get("industry") or "").lower()
                    sector_used = sector or None
                    if any(token in sector for token in ("bank", "financ", "insurance")):
                        ev_ratio, dv_ratio = 0.1, 0.9
                        debt_value_source = "sector_default_financial"
                        capital_data_state = "sector_default"
                    elif any(token in sector for token in ("technology", "software", "internet")):
                        ev_ratio, dv_ratio = 0.95, 0.05
                        debt_value_source = "sector_default_tech"
                        capital_data_state = "sector_default"
                    elif any(token in sector for token in ("utility", "real estate", "reit")):
                        ev_ratio, dv_ratio = 0.45, 0.55
                        debt_value_source = "sector_default_utility"
                        capital_data_state = "sector_default"
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
                    "beta_source": "Source of β used in CAPM (user_input, beta_5y, beta_2y, beta_1y, or synthetic_beta).",
                    "beta_window": "Trailing window used by BetaFunction when β was sourced from it.",
                    "data_state": "live when β was sourced from a real BetaFunction window; synthetic_beta when WACC fell back to β=1.0.",
                },
                "beta_source": beta_source,
                "beta_window": beta_window_used,
                "data_state": beta_data_state,
                # Audit Q3 #16-18 — provenance fields for the UI.
                "rd_source": rd_source,
                "debt_value_source": debt_value_source,
                "capital_structure_data_state": capital_data_state,
                "sector": sector_used,
            },
            sources=sources, warnings=warnings,
            metadata={
                "beta_source": beta_source,
                "beta_window": beta_window_used,
                "data_state": beta_data_state,
                "rd_source": rd_source,
                "debt_value_source": debt_value_source,
                "capital_structure_data_state": capital_data_state,
            },
        )
