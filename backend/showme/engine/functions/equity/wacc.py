"""WACC — Weighted Average Cost of Capital.

WACC = (E/V × Re) + (D/V × Rd × (1 − T))
- Re = CAPM: rf + β × ERP
- rf  = US 10Y FRED DGS10
- ERP = the issuer's own country's Damodaran premium, or a caller's market_premium.
  No constant is substituted: without one, the ERP is missing and WACC is not computed.
- Rd  = FRED ICE BofA BBB corporate yield (BAMLC0A4CBBBEY), Aaa fallback
- T   = etkin vergi oranı (FA fonksiyonundan)
- E,D = balance sheet (FA fonksiyonundan)
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import pandas as pd

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions._fred_csv import fred_with_keyless_fallback
from showme.engine.functions.equity.beta import BetaFunction

# WACC#2: industry tokens that mark a bank or insurer. yfinance files card
# networks, exchanges and asset managers under the sector "Financial Services"
# too; those keep an ordinary capital structure, so the sector alone is not
# used. Insurance brokers are fee businesses, not insurers, and are excluded.
_FINANCIAL_INDUSTRY_TOKENS = ("bank", "insurance")
_NOT_AN_INSURER_TOKENS = ("broker",)


def _is_bank_or_insurer(industry: str) -> bool:
    if not any(token in industry for token in _FINANCIAL_INDUSTRY_TOKENS):
        return False
    return not ("insurance" in industry and any(t in industry for t in _NOT_AN_INSURER_TOKENS))


# WACC#6: how each input's source label is classified. "user" = caller supplied,
# "live" = provider data, "partial" = labelled default or stale snapshot.
_QUALITY_BY_SOURCE: dict[str, dict[str, str]] = {
    "rf": {"user_input": "user", "fred_dgs10": "live"},
    # WACC#6-RQ: the FRED BBB yield is a market-wide index, not the issuer's own
    # yield, so it is a labelled proxy (partial), never live.
    "rd": {"user_input": "user", "issuer_implied": "live", "fred_bbb_yield": "partial", "fred_aaa": "partial"},
    "tax": {"user_input": "user", "issuer_effective": "live", "statutory_us_21pct": "partial"},
    "capital_structure": {"live": "live", "sector_default": "partial", "not_applicable_financial": "live"},
}


def _beta_quality(beta_source: str) -> str:
    if beta_source == "user_input":
        return "user"
    if beta_source.startswith("beta_"):
        return "live"
    return "missing"


def _erp_quality(erp_source: str) -> str:
    if erp_source == "user_input":
        return "user"
    if erp_source == "unavailable":
        return "missing"
    if erp_source == "assumption_default_5pct" or erp_source.startswith("damodaran_snapshot")             or erp_source.endswith("_country_unmatched"):
        return "partial"
    return "live"


# WACC#4: the 21% constant is the US federal statutory rate. It may stand in
# only for a US issuer; any other issuer without its own effective rate has none.
_US_COUNTRY_NAMES = frozenset({"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"})
_TAX_EXPENSE_LINES = ("Income Tax Expense", "Tax Provision")
_PRETAX_LINES = ("Pretax Income", "Pre-Tax Income", "Income Before Tax")


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _effective_tax_from_income(income: Any) -> tuple[float, str] | None:
    """Effective tax rate from an annual income statement, newest period first.

    Returns (rate, period) for the most recent annual column that has both the
    income tax expense and a positive pre-tax income and a plausible rate
    (0 <= rate < 0.5). None when no column qualifies.
    """
    if not isinstance(income, pd.DataFrame) or income.empty:
        return None
    tax_line = next((line for line in _TAX_EXPENSE_LINES if line in income.index), None)
    pretax_line = next((line for line in _PRETAX_LINES if line in income.index), None)
    if tax_line is None or pretax_line is None:
        return None
    for column in income.columns:
        tax_expense = _finite_float(income.at[tax_line, column])
        pretax = _finite_float(income.at[pretax_line, column])
        if tax_expense is None or pretax is None or pretax <= 0:
            continue
        rate = tax_expense / pretax
        if 0.0 <= rate < 0.5:
            return rate, str(getattr(column, "date", lambda: column)())
    return None


# WACC#5: the handler's beta_window (manifest menu, in days) maps onto the
# BetaFunction window it can compute. Other menu values have no window there.
_BETA_WINDOW_LABELS: dict[str, str] = {"252d": "1Y", "504d": "2Y"}
_BETA_WINDOW_ORDER = ("5Y", "2Y", "1Y")


def _first_set(params: dict[str, Any], *names: str) -> Any:
    """First caller value that is actually set (None and "" count as unset)."""
    for name in names:
        value = params.get(name)
        if value not in (None, ""):
            return value
    return None


@FunctionRegistry.register
class WACCFunction(BaseFunction):
    code = "WACC"
    name = "Weighted Average Cost of Capital"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("WACC requires instrument")
        warnings: list[str] = []
        sources: list[str] = []
        # wc1-g34 WACC#3: the ERP comes from the caller (``market_premium`` is
        # the manifest name, ``erp`` the historical one), else from Damodaran.
        # Its source is always reported; a constant is labelled, never silent.
        erp_user = _first_set(params, "market_premium", "erp")
        erp: float | None = None
        erp_source: str = "unavailable"
        # The country whose Damodaran premium is used; None when the ERP is not
        # a country's own premium (user input, assumption, or unmatched country).
        erp_country: str | None = None
        if erp_user is not None:
            erp = float(erp_user)
            erp_source = "user_input"
            sources.append("user_input")
        else:
            damo = getattr(self.deps, "damodaran", None)
            if damo:
                # WACC#3: the Damodaran premium is the issuer's own country's. An
                # issuer whose country cannot be resolved gets no premium from
                # any other location; the failure is reported, never swallowed.
                country: str | None = None
                try:
                    if self.deps.yfinance:
                        from showme.engine.core.base_data_source import DataKind, DataRequest
                        rd = await asyncio.wait_for(
                            self.deps.yfinance.fetch(DataRequest(
                                kind=DataKind.REFDATA, instrument=instrument
                            )),
                            timeout=float(params.get("yfinance_timeout", 8)),
                        )
                        country = str(getattr(rd, "country", None) or "").strip() or None
                except Exception as e:
                    warnings.append(f"issuer country lookup failed: {e}")
                if country is None:
                    warnings.append(
                        "issuer country unknown: the Damodaran ERP is set per country, so no "
                        "premium is matched to this issuer (erp_source unavailable)"
                    )
                else:
                    try:
                        if hasattr(damo, "get_erp_with_source"):
                            erp, erp_source = await asyncio.wait_for(
                                damo.get_erp_with_source(country),
                                timeout=float(params.get("damodaran_timeout", 8)),
                            )
                        else:
                            erp = await asyncio.wait_for(
                                damo.get_erp(country),
                                timeout=float(params.get("damodaran_timeout", 8)),
                            )
                            erp_source = "damodaran"
                        if erp_source.endswith("_country_unmatched"):
                            # WACC#3-RQ: the adapter's value for a country missing
                            # from its table is the mature-market premium, another
                            # country's. It is not this issuer's ERP, so it is not
                            # used and the ERP is missing (no status-ok fallback).
                            warnings.append(
                                f"Damodaran has no ERP for country {country}; the mature-market "
                                "value is not used for this issuer (erp_source unavailable)"
                            )
                            erp = None
                            erp_source = "unavailable"
                        else:
                            sources.append("damodaran")
                            erp_country = country
                            if erp_source.startswith("damodaran_snapshot"):
                                warnings.append(
                                    "Damodaran ERP table unavailable; the January 2025 snapshot is used "
                                    f"for {country} (erp_source {erp_source})"
                                )
                    except Exception as e:
                        warnings.append(f"damodaran: {e}")
                        erp = None
            if erp is None:
                # WACC#3-RQ: no hard-coded premium is substituted. Without a
                # Damodaran value (or a user market_premium) the ERP is missing
                # and WACC is not computed.
                erp_source = "unavailable"
                warnings.append(
                    "ERP unavailable from Damodaran; WACC is not computed without an ERP "
                    "(erp_source unavailable). Pass market_premium to set it."
                )
        erp = float(erp) if erp is not None else None
        # Risk-free
        # HNT-07 fix: a user-supplied ``rf`` must win unconditionally, the
        # same way the beta/rd overrides already do. FRED is only consulted
        # when the caller did not pin a scenario rate.
        # wc1-g34 T10: a failed FRED lookup leaves rf unknown (None). It is
        # never replaced by a 4% constant; WACC then reports provider_unavailable.
        rf_user = params.get("rf") not in (None, "")
        rf: float | None = float(params.get("rf")) if rf_user else None
        rf_source: str | None = "user_input" if rf_user else None
        if rf_user:
            sources.append("user_input")
        else:
            # Keyless FRED CSV fallback (S2 c#3): the risk-free anchor is
            # attempted even without a keyed adapter.
            try:
                fred = fred_with_keyless_fallback(
                    self.deps.fred, client=getattr(self, "_http_client", None)
                )
                df = await asyncio.wait_for(
                    fred.series("DGS10", frequency="d"),
                    timeout=float(params.get("fred_timeout", 8)),
                )
                if df.empty:
                    warnings.append("fred DGS10: no observations; risk-free rate unavailable")
                else:
                    rf = float(df["value"].iloc[-1]) / 100.0
                    rf_source = "fred_dgs10"
                    sources.append("fred")
            except Exception as e:
                warnings.append(f"fred: {e}")
        # Beta — Bug #17: never silently fall back to 1.0 without labelling.
        #
        # wc1-g34 T10: a beta that cannot be resolved is None, not 1.0. A
        # synthetic β=1.0 under an ok status presented a made-up input as
        # provider data. The state is reported as provider_unavailable (or
        # empty when no window has enough history) and WACC is not computed.
        beta_window_used: str | None = None
        # WACC#5: the caller's beta_window, echoed in assumptions whatever β source.
        beta_window_requested = str(_first_set(params, "beta_window") or "").strip().lower() or None
        beta: float | None = None
        beta_source: str = "user_input"
        if params.get("beta") not in (None, ""):
            beta = float(params.get("beta"))
            sources.append("user_input")
        else:
            beta_source = "unavailable"
            # WACC#5: an explicit beta_window is the first preference when the
            # BetaFunction computes it; otherwise the long-window order applies.
            preferred = _BETA_WINDOW_LABELS.get(beta_window_requested or "")
            if beta_window_requested and preferred is None:
                warnings.append(
                    f"beta_window {beta_window_requested} is not computed by BETA (252d and 504d "
                    "are); the default long-window order was used"
                )
            beta_order = (
                (preferred,) + tuple(w for w in _BETA_WINDOW_ORDER if w != preferred)
                if preferred else _BETA_WINDOW_ORDER
            )
            try:
                beta_fn = BetaFunction(self.deps)
                # Request the windows so the BetaFunction returns whichever
                # window has enough history; the first populated one in
                # beta_order is used.
                beta_res = await asyncio.wait_for(
                    beta_fn.execute(instrument, windows=list(beta_order)),
                    timeout=float(params.get("beta_timeout", 8)),
                )
                beta_payload = beta_res.data or {}
                betas = beta_payload.get("betas") or {}
                beta_status = str(beta_payload.get("status") or "")
                beta_errors = (beta_res.metadata or {}).get("provider_errors")
                # HNT-01 fix: never accept a provider-failure payload as a
                # live β. A provider_unavailable status (or any provider
                # error marker — including the retired
                # "computed_market_model" baseline label) means the numbers
                # must not flow into CAPM tagged "beta_2y" + data_state
                # "live". Empty-betas payloads are handled below.
                beta_provider_failed = bool(
                    beta_status in ("provider_unavailable", "input_required", "computed_market_model")
                    or beta_errors
                )
                resolved: float | None = None
                if not beta_provider_failed:
                    for window in beta_order:
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
                elif beta_provider_failed:
                    warnings.append(
                        "beta unavailable: BetaFunction provider failed "
                        f"({beta_status or 'provider error'}); WACC cannot be computed without a live beta"
                    )
                else:
                    warnings.append(
                        "beta unavailable: BetaFunction returned no live window "
                        "(not enough price history); WACC cannot be computed without a beta"
                    )
            except Exception as e:
                warnings.append(f"beta: {e}; WACC cannot be computed without a live beta")
        # Cost of debt — audit Q3 #17:
        # 1) Prefer issuer-specific implied rate: interest_expense / total_debt
        #    when both come from yfinance fundamentals.
        # 2) Fall back to FRED BBB yield (BAMLC0A4CBBBEY) — closer to typical
        #    corp issuer than AAA, which understates by 100–300 bp.
        # 3) FRED AAA yield.
        # wc1-g34 T10: when every source fails rd is None; the former 5.5%
        # constant is not substituted.
        rd: float | None = float(params.get("rd")) if params.get("rd") not in (None, "") else None
        rd_source: str | None = "user_input" if rd is not None else None
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
            # Keyless FRED CSV fallback (S2 c#3): attempt without a key too.
            # WACC#1: BAMLC0A4CBBBEY is the ICE BofA BBB corporate YIELD. The
            # sibling BAMLC0A4CBBB is the option-adjusted SPREAD (1.16 on
            # 2026-11-05) and is not a cost of debt (yield 5.93 same day).
            try:
                fred = fred_with_keyless_fallback(
                self.deps.fred, client=getattr(self, "_http_client", None)
            )
                df = await asyncio.wait_for(
                    fred.series("BAMLC0A4CBBBEY", frequency="d"),
                    timeout=float(params.get("fred_timeout", 8)),
                )
                if not df.empty:
                    rd = float(df["value"].iloc[-1]) / 100.0
                    rd_source = "fred_bbb_yield"
            except Exception as e:
                warnings.append(f"fred BBB yield: {e}")
        if rd is None:
            # Keyless FRED CSV fallback (S2 c#3): attempt without a key too.
            try:
                fred = fred_with_keyless_fallback(
                self.deps.fred, client=getattr(self, "_http_client", None)
            )
                df = await asyncio.wait_for(
                    fred.series("AAA", frequency="d"),
                    timeout=float(params.get("fred_timeout", 8)),
                )
                if not df.empty:
                    rd = float(df["value"].iloc[-1]) / 100.0
                    rd_source = "fred_aaa"
            except Exception as e:
                warnings.append(f"fred AAA: {e}")
        # Tax rate / E/V/D ratios — best-effort from yfinance. The tax rate is
        # resolved after this block, once the issuer's own figures are read.
        issuer_tax: float | None = None
        tax_period: str | None = None
        issuer_country = ""
        # Audit Q3 #16: capital-structure provenance. ``debt_value_source``
        # is "book" when sourced from totalDebt (yfinance balance sheet),
        # "market" when from a bond-price feed (not yet wired), or
        # "sector_default" / "default" when we fall back.
        # wc1-g34 T10: when no market-value or sector basis exists the weights
        # stay None (unknown) instead of a 70/30 constant.
        debt_value_source = "unavailable"
        capital_data_state = "unavailable"
        sector_used: str | None = None
        financial_issuer = False
        ev_ratio: float | None = None
        dv_ratio: float | None = None
        try:
            if self.deps.yfinance:
                from showme.engine.core.base_data_source import DataKind, DataRequest
                rd_data = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.REFDATA, instrument=instrument)),
                    timeout=float(params.get("yfinance_timeout", 8)),
                )
                raw = (rd_data.extras or {}).get("raw", {}) if hasattr(rd_data, "extras") else {}
                issuer_country = str(getattr(rd_data, "country", None) or "").strip().upper()
                mc = raw.get("marketCap") or 0
                debt = raw.get("totalDebt") or 0
                v = (mc or 0) + (debt or 0)
                sector = (raw.get("sector") or raw.get("industry") or "").lower()
                industry = str(raw.get("industry") or "").lower()
                sector_used = sector or None
                # Classify on the industry; a provider that only supplies one
                # label gives it as the sector, so that label is the fallback.
                classifier_label = industry or sector
                if not industry and "financ" in sector:
                    warnings.append(
                        "industry unavailable: cannot tell whether this financial issuer is a bank "
                        "or insurer; book-debt weights are used"
                    )
                if _is_bank_or_insurer(classifier_label):
                    # WACC#2: a bank's or insurer's liabilities are operating
                    # funding (deposits, policy reserves), not capital-structure
                    # debt. Neither the book-debt weight nor a sector constant
                    # describes its capital structure, so WACC is not applicable.
                    financial_issuer = True
                    ev_ratio, dv_ratio = None, None
                    debt_value_source = "not_applicable_financial"
                    capital_data_state = "not_applicable_financial"
                elif v > 0:
                    ev_ratio = float(mc / v)
                    dv_ratio = float(debt / v)
                    debt_value_source = "book"
                    capital_data_state = "live"
                elif any(token in sector for token in ("technology", "software", "internet")):
                    # Audit Q3 #18: sector-aware fallback when balance sheet
                    # is empty. Capital-light tech ~95:5.
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
        # WACC#4: the issuer's effective tax comes from its annual income statement
        # (income tax expense over pre-tax income), the FUNDAMENTALS feed. The
        # REFDATA info dict carries no statement lines.
        try:
            if self.deps.yfinance:
                from showme.engine.core.base_data_source import DataKind, DataRequest
                fundamentals = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.FUNDAMENTALS, instrument=instrument,
                        extra={"period": "annual"},
                    )),
                    timeout=float(params.get("yfinance_timeout", 8)),
                )
                income = fundamentals.get("income") if isinstance(fundamentals, dict) else None
                found = _effective_tax_from_income(income)
                if found is not None:
                    issuer_tax, tax_period = found
        except Exception as e:
            warnings.append(f"yfinance income statement: {e}")
        # WACC#4: the tax rate is labelled with where it came from. A caller
        # value wins, then the issuer's own effective rate, then the 21% US
        # statutory rate for a US issuer (flagged as a default). Any other issuer
        # with no rate of its own leaves the tax unknown.
        tax_user = _first_set(params, "tax_rate_override", "tax_rate")
        tax: float | None
        if tax_user is not None:
            tax = float(tax_user)
            tax_source = "user_input"
        elif issuer_tax is not None:
            tax = issuer_tax
            tax_source = "issuer_effective"
        elif issuer_country in _US_COUNTRY_NAMES:
            tax = 0.21
            tax_source = "statutory_us_21pct"
            warnings.append(
                "effective tax rate not available from the provider; WACC uses the 21% US "
                "statutory rate (tax_source statutory_us_21pct). Pass tax_rate_override to set it."
            )
        else:
            tax = None
            tax_source = "unavailable"
            country_note = f"issuer country {issuer_country}" if issuer_country else "issuer country unknown"
            warnings.append(
                f"effective tax rate not available from the provider for {country_note}; the 21% "
                "statutory rate applies to US issuers only. Pass tax_rate_override to set it."
            )
        re_capm: float | None = (
            rf + beta * erp if rf is not None and beta is not None and erp is not None else None
        )
        missing: list[str] = []
        if erp is None:
            missing.append("equity risk premium (Damodaran, or market_premium)")
        if rf is None:
            missing.append("risk-free rate (FRED DGS10)")
        if beta is None:
            missing.append("beta")
        if rd is None:
            missing.append("cost of debt (FRED BBB/AAA yield or issuer interest)")
        if ev_ratio is None and not financial_issuer:
            missing.append("capital structure (market cap and total debt)")
        if tax is None:
            missing.append("tax rate (issuer effective rate; the 21% statutory rate is US-only)")
        wacc: float | None = None
        if financial_issuer:
            warnings.append(
                "WACC not applicable to a bank or insurer: its liabilities are operating "
                "funding (deposits, reserves), not capital-structure debt; cost of equity "
                "(re_capm) is still reported"
            )
        elif not missing:
            wacc = ev_ratio * re_capm + dv_ratio * rd * (1 - tax)
        rows = [
            {"component": "Cost of equity", "value": re_capm, "formula": "Re = rf + beta * ERP"},
            {"component": "After-tax cost of debt",
             "value": rd * (1 - tax) if rd is not None and tax is not None else None,
             "formula": "Rd * (1 - tax_rate)"},
            {"component": "Equity weight", "value": ev_ratio, "formula": "E / (E + D)"},
            {"component": "Debt weight", "value": dv_ratio, "formula": "D / (E + D)"},
            {"component": "WACC", "value": wacc, "formula": "(E/V * Re) + (D/V * Rd * (1 - tax))"},
        ]
        surface = []
        for b in ((max(0.1, beta - 0.25), beta, beta + 0.25) if wacc is not None else ()):
            for spread in (-0.01, 0, 0.01):
                rd_case = max(0.0, rd + spread)
                re_case = rf + b * erp
                w_case = ev_ratio * re_case + dv_ratio * rd_case * (1 - tax)
                surface.append({"bucket": f"beta {b:.2f} / Rd {rd_case:.1%}", "beta": b, "rd": rd_case, "wacc": w_case})
        extra_state: dict[str, Any] = {}
        if financial_issuer:
            status = "not_applicable"
            extra_state = {
                "reason": (
                    "WACC is not applicable to a bank or insurer: deposits and policy reserves "
                    "are operating funding, so the book-debt capital-structure weight is not a "
                    "meaningful input. The cost of equity (re_capm) is reported."
                ),
                "next_actions": [
                    "Use the cost of equity (re_capm) for a financial issuer valuation.",
                    "Use a financials-specific model (e.g. excess-return or dividend-discount) instead of WACC.",
                ],
            }
        elif wacc is None:
            status = "provider_unavailable"
            extra_state = {
                "reason": (
                    "WACC is not available: no live value for " + ", ".join(missing)
                    + ". No substitute is used, so no discount rate is reported."
                ),
                "next_actions": [
                    "Retry once the FRED and yfinance providers are reachable.",
                    "Pass beta, rf and rd explicitly to compute WACC from your own inputs.",
                ],
            }
        else:
            status = "ok"
        # WACC#6: data_state is the worst state over every input, not beta alone.
        # "partial" when any input is a labelled default or stale snapshot,
        # "user_input" when the caller supplied an input, else "live".
        input_quality = {
            "beta": _beta_quality(beta_source),
            "rf": _QUALITY_BY_SOURCE["rf"].get(rf_source or "", "missing"),
            "rd": _QUALITY_BY_SOURCE["rd"].get(rd_source or "", "missing"),
            "erp": _erp_quality(erp_source),
            "tax": _QUALITY_BY_SOURCE["tax"].get(tax_source, "missing"),
            "capital_structure": _QUALITY_BY_SOURCE["capital_structure"].get(capital_data_state, "missing"),
        }
        partial_inputs = sorted(k for k, q in input_quality.items() if q == "partial")
        user_inputs = sorted(k for k, q in input_quality.items() if q == "user")
        if status == "provider_unavailable":
            data_state = "provider_unavailable"
        elif partial_inputs:
            data_state = "partial"
        elif user_inputs:
            data_state = "user_input"
        else:
            data_state = "live"
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                **extra_state,
                "wacc": float(wacc) if wacc is not None else None,
                "re_capm": float(re_capm) if re_capm is not None else None,
                "rf": float(rf) if rf is not None else None,
                "beta": float(beta) if beta is not None else None,
                "erp": erp,
                "erp_source": erp_source,
                "erp_country": erp_country,
                "rd": float(rd) if rd is not None else None,
                "tax_rate": float(tax) if tax is not None else None,
                "tax_source": tax_source,
                "tax_period": tax_period,
                "equity_weight": ev_ratio, "debt_weight": dv_ratio,
                "rows": rows,
                "surface": surface,
                "methodology": "WACC = (E/V * Re) + (D/V * Rd * (1 - tax)). Re uses CAPM: rf + beta * ERP. E and D come from market cap and total debt when yfinance returns them; rf and Rd use FRED proxies when configured.",
                "field_dictionary": {
                    "wacc": "Weighted average cost of capital as a decimal.",
                    "re_capm": "Cost of equity from CAPM.",
                    "rf": "Risk-free rate.",
                    "erp": "Equity risk premium as a decimal.",
                    "tax_source": "Where the tax rate came from: user_input, issuer_effective (latest annual income tax expense over pre-tax income), statutory_us_21pct (a 21% US default for US issuers only, not the issuer's rate) or unavailable (no rate for a non-US issuer; tax_rate is null).",
                    "tax_period": "Period-end date of the income statement behind issuer_effective; null otherwise.",
                    "erp_source": "Where the ERP came from: user_input, damodaran_cache, damodaran_live or damodaran_snapshot_2025_01 (stale, January 2025 table). unavailable when there is no ERP for the issuer (no Damodaran value for its country, or none at all); WACC is then not computed and no mature-market value is substituted.",
                    "erp_country": "Issuer country whose Damodaran premium is used; null when the ERP is a user input or unavailable.",
                    "rd": "Pre-tax cost of debt proxy.",
                    "equity_weight": "Equity share of capital structure.",
                    "debt_weight": "Debt share of capital structure.",
                    "beta_source": "Source of β used in CAPM (user_input, beta_5y, beta_2y or beta_1y); unavailable when no live β exists.",
                    "beta_window": "Trailing window used by BetaFunction when β was sourced from it.",
                    "data_state": "live when every input is provider data; partial when a labelled default stands in for an input; provider_unavailable when a required input is missing.",
                },
                "beta_source": beta_source,
                "beta_window": beta_window_used,
                # WACC#5: the caller's assumptions and the values actually applied.
                "assumptions": {
                    "market_premium": float(erp_user) if erp_user is not None else None,
                    "beta_window": beta_window_requested,
                    "beta_window_applied": beta_window_used,
                    "tax_rate_override": float(tax_user) if tax_user is not None else None,
                },
                "data_state": data_state,
                "input_quality": input_quality,
                "partial_inputs": partial_inputs,
                "user_inputs": user_inputs,
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
                "data_state": data_state,
                "rd_source": rd_source,
                "debt_value_source": debt_value_source,
                "capital_structure_data_state": capital_data_state,
            },
        )
