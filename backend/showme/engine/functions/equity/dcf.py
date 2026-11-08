"""DCF + DDM valuation calculators (Plan §26 bonus — Coder geliştirir).

DDM (Dividend Discount Model — Gordon growth):
    P = D1 / (r - g)

DCF two-stage (high-growth + terminal):
    PV(FCFE) over N years + terminal value @ stable growth.
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import FIELD_DICTIONARIES


@FunctionRegistry.register
class DDMFunction(BaseFunction):
    """DDM — Gordon Growth Dividend Discount Model."""
    code = "DDM"
    name = "Dividend Discount Model"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("DDM requires instrument")
        warnings: list[str] = []
        sources: list[str] = []
        d0 = params.get("dividend_ttm")
        g = float(params.get("growth_rate", 0.03))
        r = params.get("required_return")
        # Try to source D0 from yfinance
        if d0 is None and self.deps.yfinance:
            try:
                from showme.engine.core.base_data_source import DataKind, DataRequest
                rd = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA, instrument=instrument
                ))
                raw = (rd.extras or {}).get("raw", {}) if hasattr(rd, "extras") else {}
                d0 = raw.get("dividendRate") or raw.get("trailingAnnualDividendRate") or 0
                sources.append("yfinance")
            except Exception as e:
                warnings.append(f"yfinance: {e}")
        d0 = float(d0 or 0)
        if d0 <= 0:
            warnings.append(
                "dividend_ttm: provider returned 0 or no dividend; DDM is not applicable for non-dividend payers. Pass dividend_ttm explicitly to override."
            )
        # Required return: WACC if not specified
        if r is None:
            try:
                from showme.engine.functions.equity.wacc import WACCFunction
                wres = await WACCFunction(self.deps).execute(instrument)
                r = float(wres.data.get("wacc") or 0.08)
                sources += list(wres.sources or [])
            except Exception as e:
                warnings.append(f"wacc: {e}")
                r = 0.08
        r = float(r)
        d1 = d0 * (1 + g)
        if r <= g:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data={"error": "r must be > g for Gordon model",
                                          "d0": d0, "g": g, "r": r},
                                  warnings=["r ≤ g — model not applicable"])
        fair_value = d1 / (r - g)
        rows = [
            {"metric": "Dividend TTM", "value": d0, "formula": "D0"},
            {"metric": "Next dividend", "value": d1, "formula": "D1 = D0 * (1 + g)"},
            {"metric": "Growth rate", "value": g, "formula": "g"},
            {"metric": "Required return", "value": r, "formula": "r"},
            {"metric": "Fair value/share", "value": fair_value, "formula": "P = D1 / (r - g)"},
        ]
        sensitivity = []
        for req in (r - 0.02, r, r + 0.02):
            for grow in (max(0.0, g - 0.01), g, g + 0.01):
                value = None if req <= grow else d1 / (req - grow)
                sensitivity.append({
                    "required_return": round(req, 4),
                    "growth": round(grow, 4),
                    "value": value,
                    "bucket": f"r {req:.1%} / g {grow:.1%}",
                })
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={"status": "ok",
                   "dividend_ttm": d0, "next_dividend": d1,
                   "growth": g, "required_return": r,
                   "fair_value_per_share": fair_value,
                   "rows": rows,
                   "surface": sensitivity,
                   "methodology": "Gordon Growth DDM: P = D1 / (r - g), where D1 is next expected dividend, r is required return, and g is perpetual dividend growth. Required return defaults to WACC when not supplied.",
                   "field_dictionary": {
                       "dividend_ttm": "Trailing annual dividend per share from provider or user override.",
                       "growth": "Long-run dividend growth assumption.",
                       "required_return": "Discount rate required by equity holders.",
                       "fair_value_per_share": "The dividend-implied value per share.",
                   }},
            sources=list(set(sources)), warnings=warnings,
        )


@FunctionRegistry.register
class DCFFunction(BaseFunction):
    """DCF — Two-stage discounted cash flow valuation."""
    code = "DCF"
    name = "Discounted Cash Flow"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("DCF requires instrument")
        N = int(params.get("years", 5))
        g_high = float(params.get("growth_high", 0.10))
        g_terminal = float(params.get("growth_terminal", 0.025))
        wacc = params.get("wacc")
        fcfe = params.get("fcfe")
        shares = params.get("shares_outstanding")
        warnings: list[str] = []
        sources: list[str] = []
        if wacc is None:
            try:
                from showme.engine.functions.equity.wacc import WACCFunction
                w = await WACCFunction(self.deps).execute(instrument)
                wacc = float(w.data.get("wacc") or 0.08)
                sources += list(w.sources or [])
            except Exception as e:
                warnings.append(f"wacc: {e}")
                wacc = 0.08
        wacc = float(wacc)
        # Provenance of every model input: a caller value is a manual override,
        # a provider value is labelled with its source, and a missing value is
        # reported as missing. Nothing is substituted with a placeholder.
        fcfe_source: str | None = "user_override" if fcfe is not None else None
        # FCFE proxy: yfinance freeCashflow. Preserve negative values as-is so
        # distressed companies aren't silently coerced to a zero base case
        # (the surface payload would then look real but be driven entirely by
        # growth compounding from zero — see fix in 2026-05-17 audit).
        provider_raw_fcfe: Any = None
        if fcfe is None and self.deps.yfinance:
            try:
                from showme.engine.core.base_data_source import DataKind, DataRequest
                rd = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA, instrument=instrument
                ))
                raw = (rd.extras or {}).get("raw", {}) if hasattr(rd, "extras") else {}
                provider_raw_fcfe = raw.get("freeCashflow")
                if provider_raw_fcfe is not None:
                    fcfe = provider_raw_fcfe
                    fcfe_source = "yfinance"
                sources.append("yfinance")
            except Exception as e:
                warnings.append(f"yfinance: {e}")
        if fcfe is None:
            warnings.append(
                "free_cash_flow: no FCFE from the caller or the provider; pass fcfe to run the model."
            )
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={"status": "needs_input",
                      "reason": "Provider free cash flow is unavailable for this instrument; pass fcfe to run the model.",
                      "next_actions": ["Enter FCFE (USD) as a manual override.",
                                       "Retry once the yfinance reference data recovers."],
                      "wacc": wacc, "g_high": g_high, "g_terminal": g_terminal,
                      "years": N, "starting_fcfe": None,
                      "fcfe_source": "missing",
                      "shares_source": "user_override" if shares is not None else None,
                      "shares_outstanding": shares,
                      "fair_value_per_share": None,
                      "rows": [], "bridge": [],
                      "methodology": "Two-stage FCFE DCF; FCFE is required and is never substituted with a placeholder.",
                      "field_dictionary": FIELD_DICTIONARIES["valuation"]},
                sources=list(set(sources)), warnings=warnings,
            )
        fcfe = float(fcfe)
        if provider_raw_fcfe is not None and float(provider_raw_fcfe) < 0:
            warnings.append(
                "free_cash_flow: provider reported negative free cash flow; DCF surface compounds the negative base value — pass fcfe explicitly for a tradable model."
            )
        if wacc <= g_terminal:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data={"error": "wacc must exceed terminal growth"},
                                  warnings=["wacc ≤ g_terminal"])
        # Stage 1: explicit forecast
        cashflows = []
        cf = fcfe
        for t in range(1, N + 1):
            cf = cf * (1 + g_high)
            cashflows.append({"year": t, "fcfe": cf,
                              "pv": cf / (1 + wacc) ** t,
                              "discount_factor": 1 / (1 + wacc) ** t})
        pv_explicit = sum(c["pv"] for c in cashflows)
        # Stage 2: terminal value
        tv = (cf * (1 + g_terminal)) / (wacc - g_terminal)
        pv_tv = tv / (1 + wacc) ** N
        # Equity value (FCFE basis — already after debt)
        equity_value = pv_explicit + pv_tv
        # Per-share needs a share count: caller override first, then provider.
        shares_source: str | None = None
        if shares is not None:
            try:
                shares_f = float(shares)
                if shares_f > 0:
                    shares = shares_f
                    shares_source = "user_override"
                else:
                    shares = None
                    warnings.append("shares_outstanding: non-positive override ignored.")
            except Exception:
                shares = None
                warnings.append("shares_outstanding: override is not a number; ignored.")
        if shares is None and self.deps.yfinance:
            try:
                from showme.engine.core.base_data_source import DataKind, DataRequest
                rd = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA, instrument=instrument
                ))
                provider_shares = rd.shares_outstanding or (rd.extras or {}).get("raw", {}).get("sharesOutstanding")
                if provider_shares and provider_shares > 0:
                    shares = float(provider_shares)
                    shares_source = "yfinance"
            except Exception as e:
                warnings.append(f"shares_outstanding: {e}")
        per_share = equity_value / shares if shares else None
        if per_share is None:
            warnings.append("shares_outstanding: no share count from the caller or the provider; fair value per share is not computed.")
        bridge = [
            {"component": "PV explicit FCFE", "value": pv_explicit},
            {"component": "PV terminal value", "value": pv_tv},
            {"component": "Equity value", "value": equity_value},
            {"component": "Fair value/share", "value": per_share},
        ]
        if fcfe <= 0:
            warnings.append("free_cash_flow: provider returned missing or non-positive free cash flow; user should override fcfe for a tradable DCF.")
        if fcfe_source == "user_override" or shares_source == "user_override":
            warnings.append("manual_override: at least one model input is a caller override, not provider data.")
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={"status": "ok" if fcfe > 0 and per_share is not None else "needs_input",
                   "wacc": wacc, "g_high": g_high, "g_terminal": g_terminal,
                   "years": N, "starting_fcfe": fcfe,
                   "fcfe_source": fcfe_source,
                   "shares_source": shares_source or "missing",
                   "pv_explicit": pv_explicit,
                   "terminal_value": tv, "pv_terminal": pv_tv,
                   "equity_value": equity_value,
                   "fair_value_per_share": per_share,
                   "shares_outstanding": shares,
                   "rows": cashflows,
                   "bridge": bridge,
                   "methodology": "Two-stage FCFE DCF: forecast FCFE for N years at high growth, discount each cash flow by WACC, then add terminal value TV = FCFE_N * (1 + g_terminal) / (WACC - g_terminal). Inputs are labelled user_override (caller value) or provider (yfinance).",
                   "field_dictionary": FIELD_DICTIONARIES["valuation"]},
            sources=list(set(sources)), warnings=warnings,
        )
