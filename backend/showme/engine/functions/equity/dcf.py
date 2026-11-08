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
        forward_indicated: float | None = None
        # No caller value and no provider answer yet: the dividend is unknown
        # until the provider returns a usable payload (T10: a failed or empty
        # provider must never read as "pays no dividend, value 0, status ok").
        provider_failed = d0 is None
        # Try to source D0 from yfinance
        if d0 is None and self.deps.yfinance:
            try:
                from showme.engine.core.base_data_source import DataKind, DataRequest
                rd = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA, instrument=instrument
                ))
                raw = (rd.extras or {}).get("raw", {}) if hasattr(rd, "extras") else {}
                # The adapter swallows info failures and returns raw holding
                # only info_error (or nothing): that is no data, not a payer.
                if not raw or raw.get("info_error"):
                    provider_failed = True
                    warnings.append(f"yfinance: {raw.get('info_error') or 'no reference data returned'}")
                else:
                    provider_failed = False
                    # D0 is the TRAILING dividend. dividendRate is the forward
                    # indicated annual rate (not yet paid): growing it by (1+g)
                    # again would double-count one year of growth (DDM#1).
                    d0 = raw.get("trailingAnnualDividendRate") or 0
                    forward_indicated = raw.get("dividendRate")
                    sources.append("yfinance")
            except Exception as e:
                provider_failed = True
                warnings.append(f"yfinance: {e}")
        d0 = float(d0 or 0)
        if d0 <= 0:
            if provider_failed:
                status = "provider_unavailable"
                reason = "Dividend reference data is unavailable, so the trailing dividend is unknown. Pass dividend_ttm explicitly."
            elif forward_indicated is not None and float(forward_indicated) > 0:
                status = "needs_input"
                reason = "Provider reports a forward dividend but no trailing 12-month dividend. Pass dividend_ttm explicitly."
            else:
                status = "not_applicable"
                reason = "Provider reports no trailing dividend, so DDM is not applicable for non-dividend payers."
                warnings.append(
                    "dividend_ttm: provider returned 0 or no dividend; DDM is not applicable for non-dividend payers. Pass dividend_ttm explicitly to override."
                )
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={
                    "status": status,
                    "reason": reason,
                    "next_actions": ["Pass dividend_ttm explicitly (trailing annual dividend per share)."],
                    "dividend_ttm": None,
                    "dividend_forward_indicated": forward_indicated,
                    "next_dividend": None,
                    "growth": g, "required_return": None,
                    "fair_value_per_share": None,
                    "rows": [], "surface": [],
                },
                sources=list(set(sources)), warnings=warnings,
            )
        # Required return: WACC if not specified
        if r is None:
            # Data policy: never substitute a constant required return. When
            # WACC is not applicable or unavailable, report the explicit state.
            try:
                from showme.engine.functions.equity.wacc import WACCFunction
                wres = await WACCFunction(self.deps).execute(instrument)
                sources += list(wres.sources or [])
                wacc_value = (wres.data or {}).get("wacc")
                if wacc_value is None:
                    wacc_status = str((wres.data or {}).get("status") or "")
                    reason = (wres.data or {}).get("reason") or (
                        "WACC is not available for this issuer, so no required return can be derived. "
                        "Pass required_return explicitly to value this DDM."
                    )
                    warnings.append(f"wacc: {reason}")
                    return FunctionResult(
                        code=self.code, instrument=instrument,
                        data={
                            "status": "not_applicable" if wacc_status == "not_applicable" else "needs_input",
                            "reason": reason,
                            "next_actions": [
                                "Pass required_return explicitly (cost of equity) to value this DDM.",
                            ],
                            "dividend_ttm": d0, "growth": g,
                            "required_return": None,
                            "fair_value_per_share": None,
                        },
                        sources=list(set(sources)), warnings=warnings,
                    )
                r = float(wacc_value)
            except Exception as e:
                warnings.append(f"wacc: {e}")
                return FunctionResult(
                    code=self.code, instrument=instrument,
                    data={
                        "status": "provider_unavailable",
                        "reason": f"WACC provider failed ({e}); required return is unknown.",
                        "next_actions": [
                            "Retry once the WACC provider is reachable.",
                            "Or pass required_return explicitly.",
                        ],
                        "dividend_ttm": d0, "growth": g,
                        "required_return": None,
                        "fair_value_per_share": None,
                    },
                    sources=list(set(sources)), warnings=warnings,
                )
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
                # D1 depends on the column's own growth: D0 * (1 + g_cell).
                # Reusing the base-case D1 would understate the growth axis.
                value = None if req <= grow else d0 * (1 + grow) / (req - grow)
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
                   # Labelled cross-check only; never used in the valuation.
                   "dividend_forward_indicated": forward_indicated,
                   "growth": g, "required_return": r,
                   "fair_value_per_share": fair_value,
                   "assumptions": {"required_return": r, "growth": g, "dividend_ttm": d0},
                   "rows": rows,
                   "surface": sensitivity,
                   "methodology": "Gordon Growth DDM: P = D1 / (r - g), where D1 is next expected dividend, r is required return, and g is perpetual dividend growth. Required return defaults to WACC when not supplied.",
                   "field_dictionary": {
                       "dividend_ttm": "Trailing annual dividend per share from provider or user override.",
                       "dividend_forward_indicated": "Provider forward indicated annual dividend; cross-check only, not used in the valuation.",
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
        # Defaults mirror the manifest (dcf_seed.py defaults) and the pane (DCF.tsx).
        N = int(params.get("years", 10))
        g_high = float(params.get("growth_high", 0.08))
        g_terminal = float(params.get("growth_terminal", 0.025))
        # DCFS#2: the cash flow is FCFE (levered, after debt), so it is discounted at the
        # cost of equity (CAPM re_capm), not the enterprise WACC. A caller "wacc" is a
        # discount-rate override applied as given. The WACC model's WACC is reported for
        # reference only and never used to discount FCFE.
        caller_rate = params.get("wacc")
        wacc_source = "input" if caller_rate is not None else "cost_of_equity"
        # The "wacc" output is the WACC model's own value. A caller rate is the discount
        # rate (discount_rate), so the WACC model is not consulted and "wacc" stays null
        # rather than carrying the caller's number under the WACC key.
        wacc_reference: float | None = None
        cost_of_equity: float | None = None
        wacc: float | None = float(caller_rate) if caller_rate is not None else None
        # Provenance of the cost of equity (CAPM) inputs, set on the provider path only.
        erp_source: str | None = None
        discount_rate_data_state: str | None = None
        fcfe = params.get("fcfe")
        shares = params.get("shares_outstanding")
        warnings: list[str] = []
        sources: list[str] = []
        if caller_rate is None:
            # Data policy: never discount at a silent constant. When the cost of equity
            # is not applicable or unavailable, report the explicit state (merged
            # from the DCF#1 and WACC#1 fixes: their state names, the full
            # payload shape the pane expects).
            def _no_wacc(status: str, reason: str, next_actions: list[str]) -> FunctionResult:
                warnings.append(f"discount_rate: {reason}")
                return FunctionResult(
                    code=self.code, instrument=instrument,
                    data={"status": status, "reason": reason, "next_actions": next_actions,
                          "wacc": None, "discount_rate": None, "cost_of_equity": None,
                          "wacc_source": None, "g_high": g_high, "g_terminal": g_terminal,
                          "years": N, "starting_fcfe": None, "fcfe_source": None, "shares_source": None,
                          "assumptions": {"wacc": None, "wacc_source": None, "growth_high": g_high,
                                  "growth_terminal": g_terminal, "years": N,
                                  "fcfe_source": None, "shares_source": None},
                          "shares_outstanding": None, "equity_value": None, "fair_value_per_share": None,
                          "rows": [], "bridge": [],
                          "methodology": "Two-stage FCFE DCF; FCFE is discounted at the cost of equity (CAPM re_capm), which is required and is never substituted with a constant or with WACC.",
                          "field_dictionary": FIELD_DICTIONARIES["valuation"]},
                    sources=list(set(sources)), warnings=warnings,
                )

            try:
                from showme.engine.functions.equity.wacc import WACCFunction
                w = await WACCFunction(self.deps).execute(instrument)
            except Exception as e:  # noqa: BLE001 - reported as the provider state
                return _no_wacc(
                    "provider_unavailable",
                    f"WACC provider failed ({str(e) or type(e).__name__}); discount rate is unknown.",
                    ["Retry once the WACC provider is reachable.", "Or pass wacc explicitly."],
                )
            sources += list(w.sources or [])
            wacc_reference = (w.data or {}).get("wacc")
            re_capm = (w.data or {}).get("re_capm")
            if re_capm is None:
                wacc_status = str((w.data or {}).get("status") or "")
                reason = (w.data or {}).get("reason") or (
                    "The cost of equity (CAPM) is not available for this issuer, so FCFE cannot be "
                    "discounted. Pass wacc explicitly to value this DCF."
                )
                if wacc_status == "not_applicable":
                    state = "not_applicable"
                elif wacc_status == "provider_unavailable":
                    state = "provider_unavailable"
                else:
                    state = "needs_input"
                return _no_wacc(
                    state,
                    reason,
                    ["Pass wacc explicitly as the discount rate, or retry once the WACC inputs are reachable."],
                )
            cost_of_equity = float(re_capm)
            wacc = cost_of_equity
            erp_source = (w.data or {}).get("erp_source")
            discount_rate_data_state = (w.data or {}).get("data_state")
            if erp_source == "assumption_default_5pct":
                warnings.append(
                    "discount_rate: the cost of equity rests on a constant 5.0% equity risk premium "
                    "(erp_source assumption_default_5pct); pass market_premium to replace it."
                )
        wacc = float(wacc)
        if caller_rate is not None:
            warnings.append(
                "discount_rate: the caller-supplied rate is applied to FCFE as given; the cost of "
                "equity (CAPM) is the consistent discount rate for levered FCFE."
            )
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
                      "wacc": wacc_reference, "discount_rate": wacc, "cost_of_equity": cost_of_equity, "wacc_source": wacc_source, "g_high": g_high, "g_terminal": g_terminal,
                      "years": N, "starting_fcfe": None,
                      "fcfe_source": "missing",
                      "assumptions": {"wacc": wacc_reference, "discount_rate": wacc, "cost_of_equity": cost_of_equity, "wacc_source": wacc_source,
                                      "growth_high": g_high, "growth_terminal": g_terminal,
                                      "years": N, "fcfe_source": "missing",
                                      "shares_source": "user_override" if shares is not None else None},
                      "shares_source": "user_override" if shares is not None else None,
                      "shares_outstanding": shares,
                      "equity_value": None, "fair_value_per_share": None,
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
            # Explicit input_error state with the full must_have payload shape
            # (DCF#3): the Gordon terminal value is undefined here, so no
            # valuation is computed and no value is substituted.
            reason = (
                f"WACC ({wacc:.2%}) must exceed terminal growth ({g_terminal:.2%}); "
                "the terminal value is undefined. Raise wacc or lower terminal growth."
            )
            warnings.append("wacc ≤ g_terminal")
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={"status": "input_error",
                      "reason": reason,
                      "next_actions": ["Raise wacc above terminal growth.",
                                       "Or lower growth_terminal below wacc."],
                      "error": "wacc must exceed terminal growth",
                      "wacc": wacc_reference, "discount_rate": wacc, "cost_of_equity": cost_of_equity, "wacc_source": wacc_source,
                      "g_high": g_high, "g_terminal": g_terminal,
                      "years": N, "starting_fcfe": fcfe,
                      "fcfe_source": fcfe_source,
                      "assumptions": {"wacc": wacc_reference, "discount_rate": wacc, "cost_of_equity": cost_of_equity, "wacc_source": wacc_source,
                                      "growth_high": g_high, "growth_terminal": g_terminal,
                                      "years": N, "fcfe_source": fcfe_source,
                                      "shares_source": None},
                      "shares_source": None,
                      "shares_outstanding": None,
                      "pv_explicit": None, "terminal_value": None, "pv_terminal": None,
                      "equity_value": None, "fair_value_per_share": None,
                      "rows": [], "bridge": [],
                      "methodology": "Two-stage FCFE DCF; the terminal value is undefined when wacc is not above terminal growth.",
                      "field_dictionary": FIELD_DICTIONARIES["valuation"]},
                sources=list(set(sources)), warnings=warnings,
            )
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
                   "wacc": wacc_reference, "discount_rate": wacc, "cost_of_equity": cost_of_equity, "wacc_source": wacc_source,
                   "erp_source": erp_source, "discount_rate_data_state": discount_rate_data_state,
                   "g_high": g_high, "g_terminal": g_terminal,
                   "years": N, "starting_fcfe": fcfe,
                   "fcfe_source": fcfe_source,
                   "shares_source": shares_source or "missing",
                   "assumptions": {"wacc": wacc_reference, "discount_rate": wacc, "cost_of_equity": cost_of_equity, "wacc_source": wacc_source,
                                   "erp_source": erp_source, "discount_rate_data_state": discount_rate_data_state,
                                   "growth_high": g_high, "growth_terminal": g_terminal,
                                   "years": N, "fcfe_source": fcfe_source,
                                   "shares_source": shares_source or "missing"},
                   "pv_explicit": pv_explicit,
                   "terminal_value": tv, "pv_terminal": pv_tv,
                   "equity_value": equity_value,
                   "fair_value_per_share": per_share,
                   "shares_outstanding": shares,
                   "rows": cashflows,
                   "bridge": bridge,
                   "methodology": "Two-stage FCFE DCF: forecast FCFE for N years at high growth, discount each cash flow at discount_rate (the cost of equity by default, or a caller override), then add terminal value TV = FCFE_N * (1 + g_terminal) / (discount_rate - g_terminal). wacc is the WACC model's value (null when the caller supplies the discount rate), reported for reference only; erp_source and discount_rate_data_state label the cost-of-equity inputs. Inputs are labelled user_override (caller value) or provider (yfinance).",
                   "field_dictionary": FIELD_DICTIONARIES["valuation"]},
            sources=list(set(sources)), warnings=warnings,
        )
