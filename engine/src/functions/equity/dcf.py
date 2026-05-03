"""DCF + DDM valuation calculators (Plan §26 bonus — Coder geliştirir).

DDM (Dividend Discount Model — Gordon growth):
    P = D1 / (r - g)

DCF two-stage (high-growth + terminal):
    PV(FCFE) over N years + terminal value @ stable growth.
"""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


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
                from src.core.base_data_source import DataKind, DataRequest
                rd = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA, instrument=instrument
                ))
                raw = (rd.extras or {}).get("raw", {}) if hasattr(rd, "extras") else {}
                d0 = raw.get("dividendRate") or raw.get("trailingAnnualDividendRate") or 0
                sources.append("yfinance")
            except Exception as e:
                warnings.append(f"yfinance: {e}")
        d0 = float(d0 or 0)
        # Required return: WACC if not specified
        if r is None:
            try:
                from src.functions.equity.wacc import WACCFunction
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
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={"dividend_ttm": d0, "next_dividend": d1,
                   "growth": g, "required_return": r,
                   "fair_value_per_share": fair_value},
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
                from src.functions.equity.wacc import WACCFunction
                w = await WACCFunction(self.deps).execute(instrument)
                wacc = float(w.data.get("wacc") or 0.08)
                sources += list(w.sources or [])
            except Exception as e:
                warnings.append(f"wacc: {e}")
                wacc = 0.08
        wacc = float(wacc)
        # FCFE proxy: yfinance freeCashflow
        if fcfe is None and self.deps.yfinance:
            try:
                from src.core.base_data_source import DataKind, DataRequest
                rd = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA, instrument=instrument
                ))
                raw = (rd.extras or {}).get("raw", {}) if hasattr(rd, "extras") else {}
                fcfe = raw.get("freeCashflow") or 0
                sources.append("yfinance")
            except Exception as e:
                warnings.append(f"yfinance: {e}")
        fcfe = float(fcfe or 0)
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
                              "pv": cf / (1 + wacc) ** t})
        pv_explicit = sum(c["pv"] for c in cashflows)
        # Stage 2: terminal value
        tv = (cf * (1 + g_terminal)) / (wacc - g_terminal)
        pv_tv = tv / (1 + wacc) ** N
        # Equity value (FCFE basis — already after debt)
        equity_value = pv_explicit + pv_tv
        # Per-share if we know share count
        per_share = None
        if shares:
            try:
                shares = float(shares)
                if shares > 0:
                    per_share = equity_value / shares
            except Exception:
                shares = None
        if per_share is None and self.deps.yfinance:
            try:
                from src.core.base_data_source import DataKind, DataRequest
                rd = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA, instrument=instrument
                ))
                shares = rd.shares_outstanding or (rd.extras or {}).get("raw", {}).get("sharesOutstanding")
                if shares and shares > 0:
                    per_share = equity_value / shares
            except Exception:
                pass
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={"wacc": wacc, "g_high": g_high, "g_terminal": g_terminal,
                   "years": N, "starting_fcfe": fcfe,
                   "pv_explicit": pv_explicit,
                   "terminal_value": tv, "pv_terminal": pv_tv,
                   "equity_value": equity_value,
                   "fair_value_per_share": per_share,
                   "shares_outstanding": shares,
                   "cashflows": cashflows},
            sources=list(set(sources)), warnings=warnings,
        )
