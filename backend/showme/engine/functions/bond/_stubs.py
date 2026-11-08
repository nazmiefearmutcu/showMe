"""CRPR, DDIS, DEBT, ALLQ live handlers (single-file group).

These four bond/rates functions were previously canned-constant stubs.
They now fetch REAL keyless public data:

* CRPR  — implied credit profile from SEC EDGAR companyfacts (leverage +
  interest coverage) mapped to a transparent rating bucket.
* DDIS  — debt-by-maturity from SEC companyfacts long-term-debt maturity
  concepts (corporates) / labelled illustrative fallback otherwise.
* DEBT  — sovereign debt-to-GDP from the World Bank indicator API
  (GC.DOD.TOTL.GD.ZS), keyless.
* ALLQ  — indicative dealer ladder anchored to a REAL Treasury par yield
  (keyless US Treasury curve -> modeled clean price; no other anchor).

Every handler wraps the network in try/except and, on a genuine outage,
returns ``status="provider_unavailable"`` with an honest warning +
next_actions — never fabricated numbers presented as live.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.providers._http import get_client

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

_SEC_UA = "showMe research contact@example.com"
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_WORLDBANK_URL = "https://api.worldbank.org/v2/country/{iso}/indicator/{code}"
_WB_DEBT_TO_GDP = "GC.DOD.TOTL.GD.ZS"

# ALLQ per-tenor anchors from the keyless US Treasury daily par-yield curve
# (``engine/data_sources/bond/ustreasury_adapter.py``). FiscalData only
# publishes a security-TYPE average coupon (H-8 caveat); when the curve
# adapter is wired we can anchor each tenor to its actual par yield.
_US_TREASURY_TENOR_COLUMNS = {
    "US1M": "1 Mo", "US2M": "2 Mo", "US3M": "3 Mo", "US4M": "4 Mo", "US6M": "6 Mo",
    "US1Y": "1 Yr", "US2Y": "2 Yr", "US3Y": "3 Yr", "US5Y": "5 Yr", "US7Y": "7 Yr",
    "US10Y": "10 Yr", "US20Y": "20 Yr", "US30Y": "30 Yr",
}
_US_TREASURY_TENOR_YEARS = {
    "US1M": 1 / 12, "US2M": 2 / 12, "US3M": 0.25, "US4M": 4 / 12, "US6M": 0.5,
    "US1Y": 1.0, "US2Y": 2.0, "US3Y": 3.0, "US5Y": 5.0, "US7Y": 7.0,
    "US10Y": 10.0, "US20Y": 20.0, "US30Y": 30.0,
}

# Sovereign issuers that have no SEC CIK; treated as non-corporate so CRPR/DDIS
# fall back to a clearly-labelled reference profile rather than guessing a CIK.
_SOVEREIGN_HINTS = (
    "TREASURY",
    "SOVEREIGN",
    "GOVT",
    "GOVERNMENT",
    "US10Y",
    "US2Y",
    "US30Y",
    "US5Y",
    "UST",
    "BUND",
    "GILT",
    "JGB",
    "OAT",
    "BTP",
)

# ISO-2 -> ISO-3 for the World Bank API (subset covering the common desk set).
_ISO2_TO_ISO3 = {
    "US": "USA", "JP": "JPN", "DE": "DEU", "GB": "GBR", "FR": "FRA",
    "IT": "ITA", "ES": "ESP", "CA": "CAN", "AU": "AUS", "CN": "CHN",
    "IN": "IND", "BR": "BRA", "TR": "TUR", "MX": "MEX", "KR": "KOR",
    "RU": "RUS", "ZA": "ZAF", "ID": "IDN", "SA": "SAU", "CH": "CHE",
    "NL": "NLD", "SE": "SWE", "PL": "POL", "AR": "ARG", "GR": "GRC",
}
# Reverse for normalising whatever the user passes in.
_ISO3_TO_ISO2 = {v: k for k, v in _ISO2_TO_ISO3.items()}
_DEFAULT_DEBT_COUNTRIES = ["US", "JP", "DE", "GB", "FR", "IT", "TR", "BR"]


def _as_of() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bond_symbol(instrument: Instrument | None, params: dict[str, Any], fallback: str = "US10Y") -> str:
    return str(params.get("symbol") or getattr(instrument, "symbol", None) or fallback).strip().upper()


def _is_sovereign(token: str) -> bool:
    upper = token.upper()
    return any(hint in upper for hint in _SOVEREIGN_HINTS)


def _is_equity_instrument(instrument: Instrument | None) -> bool:
    return instrument is not None and getattr(instrument, "asset_class", None) == AssetClass.EQUITY



async def _sec_lookup_cik(client: Any, ticker: str) -> str | None:
    """Resolve a ticker to a 10-digit zero-padded CIK via EDGAR's map."""
    r = await client.get(_SEC_TICKERS_URL, headers={"User-Agent": _SEC_UA})
    r.raise_for_status()
    payload = r.json()
    iterable = payload.values() if isinstance(payload, dict) else payload
    want = ticker.strip().upper()
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("ticker", "")).upper() == want:
            return str(entry.get("cik_str", "")).zfill(10)
    return None


def _latest_usd_fact(facts: dict[str, Any], concept: str) -> tuple[float, str] | None:
    """Return (value, end_date) of the most recent USD datapoint for a us-gaap concept."""
    node = (
        facts.get("facts", {})
        .get("us-gaap", {})
        .get(concept, {})
        .get("units", {})
    )
    units = node.get("USD") or next(iter(node.values()), None) if node else None
    if not units:
        return None
    best: tuple[float, str] | None = None
    for item in units:
        val = item.get("val")
        end = item.get("end")
        if val is None or end is None:
            continue
        if best is None or end > best[1]:
            best = (float(val), str(end))
    return best


def _first_fact(facts: dict[str, Any], concepts: tuple[str, ...]) -> tuple[float, str] | None:
    for concept in concepts:
        got = _latest_usd_fact(facts, concept)
        if got is not None:
            return got
    return None


# ---------------------------------------------------------------------------
# CRPR — implied credit profile from SEC EDGAR companyfacts
# ---------------------------------------------------------------------------


_CRPR_ANNUAL_DAYS = (350, 380)


def _crpr_duration_days(item: dict[str, Any]) -> int | None:
    start, end = item.get("start"), item.get("end")
    if not start or not end:
        return None
    try:
        return (datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))).days
    except ValueError:
        return None


def _crpr_pick(
    facts: dict[str, Any],
    concepts: tuple[str, ...],
    *,
    flow: bool,
    period_end: str | None = None,
) -> tuple[float, str, str] | None:
    """Return ``(value, end, concept)`` for the first concept with a qualifying USD entry.

    ``flow=True`` keeps annual entries only (about 365 days), so a 10-Q year-to-date
    or single-quarter value is never read as a full-year figure. ``flow=False`` keeps
    point-in-time balances only (entries with no start date). ``period_end``, when
    given, restricts to that exact period end so numerator and denominator share a
    fiscal period. Ties on the end date go to the entry filed most recently.
    """
    lo, hi = _CRPR_ANNUAL_DAYS
    for concept in concepts:
        units = facts.get("facts", {}).get("us-gaap", {}).get(concept, {}).get("units", {}) or {}
        items = units.get("USD") or []
        best: tuple[tuple[str, str], float, str] | None = None
        for item in items:
            val, end = item.get("val"), item.get("end")
            if val is None or end is None:
                continue
            if flow:
                days = _crpr_duration_days(item)
                if days is None or not (lo <= days <= hi):
                    continue
            elif item.get("start"):
                continue
            if period_end is not None and str(end) != period_end:
                continue
            key = (str(end), str(item.get("filed") or ""))
            if best is None or key > best[0]:
                best = (key, float(val), str(end))
        if best is not None:
            return (best[1], best[2], concept)
    return None


_SP_BUCKET = {
    "AAA": "high_grade",
    "AA": "high_grade",
    "A": "investment_grade",
    "BBB": "investment_grade",
    "BB": "crossover",
    "B": "high_yield",
    "CCC": "distressed",
    "CC": "distressed",
    "C": "distressed",
    "D": "distressed",
}


def _bucket_for_sp_rating(rating: Any) -> str:
    """Map a pinned S&P rating (AA+, BBB-, ...) to the model's bucket scale; "n/a" if unknown."""
    if not isinstance(rating, str):
        return "n/a"
    return _SP_BUCKET.get(rating.strip().upper().rstrip("+-"), "n/a")


def _rating_bucket_from_coverage(leverage: float | None, coverage: float | None) -> tuple[str, str, str, str]:
    """Map (debt/EBITDA, interest coverage) to a transparent implied bucket.

    Returns (implied_rating, sp_like, bucket, outlook). Boundaries are coarse
    and documented in the methodology — this is model-implied-from-financials,
    NOT a paid agency feed.
    """
    lev = leverage if leverage is not None else 99.0
    cov = coverage if coverage is not None else 0.0
    if lev <= 1.5 and cov >= 12:
        return ("AA", "AA", "high_grade", "stable")
    if lev <= 2.5 and cov >= 8:
        return ("A", "A", "investment_grade", "stable")
    if lev <= 3.5 and cov >= 4:
        return ("BBB", "BBB", "investment_grade", "stable")
    if lev <= 4.5 and cov >= 2.5:
        return ("BB", "BB", "crossover", "negative")
    if lev <= 6.0 and cov >= 1.5:
        return ("B", "B", "high_yield", "negative")
    return ("CCC", "CCC", "distressed", "negative")


@FunctionRegistry.register
class CRPRFunction(BaseFunction):
    code = "CRPR"
    name = "Credit Rating Profile"
    # Must match crpr_seed.py (BOND + EQUITY): the route's compatibility guard
    # rejects any instrument class not listed here before execute() runs.
    asset_classes = (AssetClass.BOND, AssetClass.EQUITY)
    category = "bond"

    _METHODOLOGY = (
        "CRPR derives a MODEL-IMPLIED credit profile from the issuer's latest SEC EDGAR "
        "companyfacts (XBRL): gross debt = LongTermDebt(+Current) + ShortTermBorrowings; "
        "EBITDA proxy = OperatingIncomeLoss + DepreciationDepletionAndAmortization; "
        "interest coverage = EBIT (OperatingIncomeLoss) / InterestExpense. Only annual (about "
        "365-day) flow facts are used, and interest and D&A must share the EBIT fiscal period. "
        "A missing input is reported as null with a warning, never as zero, and no rating is "
        "derived without both leverage and coverage. Leverage (debt/EBITDA) and coverage "
        "are mapped to a coarse, transparent rating bucket (AA..CCC). This is implied from "
        "financials, NOT a paid S&P/Moody's/Fitch feed. If the caller pins a ``rating`` dict "
        "it is echoed verbatim and its implied bucket is taken from the pinned S&P rating "
        "(n/a when none is pinned). Sovereign issuers (no SEC CIK) get a labelled reference profile."
    )
    _FIELD_DICT = {
        "agency": "Source label for the row (model_implied or user_input).",
        "rating": "Long-term credit rating (implied or user-pinned).",
        "outlook": "Stable/positive/negative outlook.",
        "watch": "Watchlist state when available.",
        "rating_date": "As-of date of the underlying financials or override.",
        "rationale": "Why this rating was assigned, incl. leverage/coverage inputs.",
    }
    _SCALE = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"]

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        issuer = str(params.get("issuer") or _bond_symbol(instrument, params, "US Treasury")).strip()

        # 1) explicit user override -> echo verbatim
        user_rating = params.get("rating")
        if isinstance(user_rating, dict) and user_rating:
            rows = [
                {"agency": "S&P", "rating": user_rating.get("sp"), "outlook": user_rating.get("outlook", "n/a"), "watch": user_rating.get("watch", "none"), "rating_date": _as_of(), "rationale": "Operator-pinned rating override."},
                {"agency": "Moody's", "rating": user_rating.get("moodys"), "outlook": user_rating.get("outlook", "n/a"), "watch": user_rating.get("watch", "none"), "rating_date": _as_of(), "rationale": "Operator-pinned rating override."},
                {"agency": "Fitch", "rating": user_rating.get("fitch"), "outlook": user_rating.get("outlook", "n/a"), "watch": user_rating.get("watch", "none"), "rating_date": _as_of(), "rationale": "Operator-pinned rating override."},
            ]
            # The bucket follows the pinned S&P rating. The ``bucket`` input is not
            # read here: the seed injects its default (high_grade) on every call.
            pinned_bucket = _bucket_for_sp_rating(user_rating.get("sp"))
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "ok",
                    "rows": rows,
                    "summary": {"issuer": issuer, "implied_bucket": pinned_bucket, "agencies": len(rows), "source_mode": "user_input"},
                    "implied_bucket": pinned_bucket,
                    "scale": self._SCALE,
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                },
                sources=["user_input"],
                metadata={"data_mode": "user_input", "as_of": _as_of()},
            )

        # 2) sovereign / non-tickerable issuer -> honest not-applicable state.
        # CRPR's model is built from SEC financials, which sovereigns do not
        # file, and no keyless sovereign-rating feed is wired. A constant rating
        # here would be placeholder data presented as model output, so the
        # payload carries no rating row at all.
        # An EQUITY instrument is never a sovereign: the hint list matches by
        # substring, so an ETF or company symbol such as BOAT or GOVT would
        # otherwise be labelled a sovereign issuer.
        if _is_sovereign(issuer) and not _is_equity_instrument(instrument):
            reason = (
                f"{issuer!r} is a sovereign issuer: CRPR's SEC-financials model does not apply "
                "and no keyless sovereign rating feed is wired, so no rating is shown."
            )
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "rows": [],
                    "summary": {"issuer": issuer, "implied_bucket": "n/a", "agencies": 0, "source_mode": "sovereign_not_applicable"},
                    "reason": reason,
                    "scale": self._SCALE,
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                    "next_actions": [
                        "Pass a ``rating`` override with the sovereign's published agency ratings.",
                        "Pick a tickerable corporate issuer for a model-implied profile from SEC financials.",
                    ],
                },
                sources=["no_live_source"],
                warnings=[reason],
                metadata={"data_mode": "empty", "as_of": _as_of()},
            )

        # 3) corporate -> derive from SEC EDGAR companyfacts
        ticker = issuer.split()[0].upper()
        started = time.monotonic()
        try:
            client = await get_client()
            cik = await _sec_lookup_cik(client, ticker)
            if not cik:
                latency_ms = int((time.monotonic() - started) * 1000)
                return FunctionResult(
                    code=self.code,
                    instrument=instrument,
                    data={
                        "status": "empty",
                        "rows": [],
                        "summary": {"issuer": issuer, "implied_bucket": "n/a", "agencies": 0, "source_mode": "sec_edgar"},
                        "scale": self._SCALE,
                        "methodology": self._METHODOLOGY,
                        "field_dictionary": self._FIELD_DICT,
                        "next_actions": [f"No SEC CIK found for ticker {ticker!r}. Provide a ``rating`` override or use a tickerable US issuer."],
                    },
                    sources=["sec_edgar"],
                    warnings=[f"Ticker {ticker!r} not found in SEC EDGAR company map; cannot derive an implied profile."],
                    metadata={"latency_ms": latency_ms, "data_mode": "empty", "as_of": _as_of()},
                )
            r = await client.get(_SEC_FACTS_URL.format(cik=cik), headers={"User-Agent": _SEC_UA})
            r.raise_for_status()
            facts = r.json()
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - started) * 1000)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "summary": {"issuer": issuer, "implied_bucket": "n/a", "agencies": 0, "source_mode": "sec_edgar"},
                    "scale": self._SCALE,
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                    "next_actions": ["Retry when SEC EDGAR (data.sec.gov) is reachable."],
                },
                sources=["sec_edgar"],
                warnings=[f"SEC EDGAR unreachable: {exc}"],
                metadata={"latency_ms": latency_ms, "data_mode": "provider_unavailable", "as_of": _as_of()},
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        # Flow facts are annual and share the EBIT fiscal period; balances are instants.
        op_income = _crpr_pick(facts, ("OperatingIncomeLoss",), flow=True)
        period_end = op_income[1] if op_income else None
        dep_amort = _crpr_pick(facts, ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"), flow=True, period_end=period_end)
        interest_concepts = ("InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense")
        interest = _crpr_pick(facts, interest_concepts, flow=True, period_end=period_end)
        lt_debt = _crpr_pick(facts, ("LongTermDebtNoncurrent", "LongTermDebt"), flow=False)
        lt_debt_cur = _crpr_pick(facts, ("LongTermDebtCurrent", "DebtCurrent"), flow=False)
        short_debt = _crpr_pick(facts, ("ShortTermBorrowings",), flow=False)

        # The LongTermDebt fallback is the total including the current portion
        # (Apple: 78.114bn = 68.208bn noncurrent + 9.906bn current), so the current
        # portion is added only when the noncurrent figure or no long-term figure was used.
        term_debt_parts = [lt_debt[0]] if lt_debt is not None else []
        if lt_debt_cur is not None and (lt_debt is None or lt_debt[2] != "LongTermDebt"):
            term_debt_parts.append(lt_debt_cur[0])
        gross_debt = sum(term_debt_parts) + (short_debt[0] if short_debt is not None else 0.0)

        # A missing input stays None. It is never read as zero.
        ebit = op_income[0] if op_income is not None else None
        ebitda = (ebit + dep_amort[0]) if (ebit is not None and dep_amort is not None) else None
        leverage = round(gross_debt / ebitda, 3) if ebitda is not None and ebitda > 0 else None
        # Coverage is EBIT / interest expense, the conventional definition.
        coverage = round(ebit / interest[0], 3) if ebit is not None and interest is not None and interest[0] > 0 else None
        fin_date = next((x[1] for x in (op_income, lt_debt, interest) if x is not None), _as_of())
        input_warnings: list[str] = []
        if op_income is None:
            input_warnings.append(
                "No annual OperatingIncomeLoss (EBIT) reported; EBITDA, leverage and interest coverage are not computed."
            )
        else:
            if dep_amort is None:
                input_warnings.append(
                    f"No annual D&A for the EBIT period ending {period_end}; EBITDA and leverage are not computed."
                )
            if interest is None:
                latest_interest = _crpr_pick(facts, interest_concepts, flow=True)
                if latest_interest is not None:
                    input_warnings.append(
                        f"Interest expense has no annual entry for the EBIT period ending {period_end} "
                        f"(latest annual interest ends {latest_interest[1]}); interest coverage is not computed."
                    )
                else:
                    input_warnings.append("No annual interest expense reported; interest coverage is not computed.")
        if ebitda is not None and ebitda <= 0:
            input_warnings.append("EBITDA is not positive, so leverage is not meaningful.")

        if gross_debt <= 0 and (ebitda or 0.0) <= 0:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "rows": [],
                    "summary": {"issuer": issuer, "implied_bucket": "n/a", "agencies": 0, "source_mode": "sec_edgar"},
                    "scale": self._SCALE,
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                    "next_actions": ["Issuer's filings lack the debt/EBITDA concepts CRPR needs; provide a ``rating`` override."],
                },
                sources=["sec_edgar"],
                warnings=["SEC companyfacts did not expose the debt/EBITDA concepts required to imply a rating."],
                metadata={"latency_ms": latency_ms, "data_mode": "empty", "as_of": _as_of()},
            )

        interest_fields = {
            "interest_expense_usd": interest[0] if interest else None,
            "interest_period_end": interest[1] if interest else None,
        }
        if leverage is None or coverage is None:
            # A null input must not reach the bucket map, which would score it as CCC.
            reason = "; ".join(input_warnings) or (
                "Required inputs (EBIT, D&A and interest for one annual period, with positive EBITDA) "
                "are not all available, so no implied rating is derived from these filings."
            )
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "rows": [],
                    "summary": {
                        "issuer": issuer,
                        "cik": cik,
                        "implied_bucket": "n/a",
                        "agencies": 0,
                        "leverage_x": leverage,
                        "interest_coverage_x": None,
                        "gross_debt_usd": gross_debt,
                        "ebitda_proxy_usd": ebitda,
                        **interest_fields,
                        "source_mode": "sec_edgar",
                    },
                    "reason": reason,
                    "scale": self._SCALE,
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                    "next_actions": ["Provide a ``rating`` override, or retry when the filings report matching annual interest expense."],
                },
                sources=["sec_edgar"],
                warnings=list(input_warnings) or [reason],
                metadata={"latency_ms": latency_ms, "data_mode": "empty", "as_of": fin_date},
            )

        rating, sp_like, bucket, outlook = _rating_bucket_from_coverage(leverage, coverage)
        rationale = (
            f"Implied from SEC financials (as of {fin_date}): gross debt ${gross_debt/1e9:.2f}bn, "
            f"EBITDA proxy ${ebitda/1e9:.2f}bn, leverage {leverage if leverage is not None else 'n/a'}x, "
            f"interest coverage {coverage if coverage is not None else 'n/a'}x."
        )
        rows = [
            {"agency": "model_implied", "rating": rating, "outlook": outlook, "watch": "none", "rating_date": fin_date, "rationale": rationale},
        ]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": rows,
                "summary": {
                    "issuer": issuer,
                    "cik": cik,
                    "implied_bucket": bucket,
                    "agencies": len(rows),
                    "leverage_x": leverage,
                    "interest_coverage_x": coverage,
                    "gross_debt_usd": gross_debt,
                    "ebitda_proxy_usd": ebitda,
                    **interest_fields,
                    "source_mode": "model_implied_from_financials",
                },
                "implied_bucket": bucket,
                "scale": self._SCALE,
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICT,
            },
            sources=["sec_edgar"],
            warnings=["CRPR rating is MODEL-IMPLIED from SEC financials, not a paid agency rating."],
            metadata={"latency_ms": latency_ms, "data_mode": "modeled", "as_of": fin_date},
        )


# ---------------------------------------------------------------------------
# DDIS — debt by maturity from SEC EDGAR companyfacts
# ---------------------------------------------------------------------------


@FunctionRegistry.register
class DDISFunction(BaseFunction):
    code = "DDIS"
    name = "Debt Distribution by Maturity"
    asset_classes = (AssetClass.EQUITY, AssetClass.BOND)
    category = "bond"

    _METHODOLOGY = (
        "DDIS buckets an issuer's outstanding debt principal by remaining maturity. For US "
        "corporates it reads the latest SEC EDGAR companyfacts long-term-debt maturity concepts "
        "(LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths / Year{Two..Five} / "
        "AfterYearFive) and maps them onto the 0-1Y / 1-3Y / 3-5Y / 5Y+ ladder, in USD billions. "
        "Share % = amount / total x 100. When the caller supplies a ``maturities`` schedule it is "
        "returned verbatim. With no SEC data and no override the pane stays EMPTY (H-5 fix "
        "2026-09-08: the old fabricated illustrative ladder was removed) and the payload says why."
    )
    _FIELD_DICT = {
        "bucket": "Remaining-maturity bucket.",
        "tenor_years": "Representative tenor for chart ordering.",
        "amount_usd_bn": "Principal amount in USD billions.",
        "currency": "Currency of the underlying issuance.",
        "pct": "Share of total visible debt schedule.",
    }

    @staticmethod
    def _finalize_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
        for row in rows:
            if "amount" in row and "amount_usd_bn" not in row:
                row["amount_usd_bn"] = row.pop("amount")
            if "amount_usd_bn" not in row:
                row["amount_usd_bn"] = 0.0
        total = round(sum(float(r.get("amount_usd_bn") or 0) for r in rows), 4)
        if total > 0:
            for row in rows:
                row["pct"] = round(float(row.get("amount_usd_bn") or 0) / total * 100.0, 1)
        return rows, total

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        explicit_issuer = params.get("issuer")
        instrument_symbol = getattr(instrument, "symbol", None)
        issuer = str(explicit_issuer or instrument_symbol or "UNSPECIFIED_ISSUER").strip().upper() or "UNSPECIFIED_ISSUER"
        currency = str(params.get("currency") or "USD").upper()

        # 1) user-supplied schedule -> verbatim
        if params.get("maturities") is not None:
            rows, total = self._finalize_rows(list(params.get("maturities") or []))
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "ok",
                    "rows": rows,
                    "summary": {"issuer": issuer, "total_debt_usd_bn": total, "currency": currency, "source_mode": "user_input"},
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                },
                sources=["user_input"],
                metadata={"data_mode": "user_input", "as_of": _as_of()},
            )

        # H-5 fix (2026-09-08): the fabricated "illustrative" ladder
        # (3.2 / 8.6 / 6.4 / 8.5 bn constants at HTTP 200) is gone. Every
        # no-data path now returns honest empty rows + a reason +
        # next_actions instead of invented principal amounts.
        def _empty_schedule(reason: str, next_actions: list[str]) -> FunctionResult:
            data: dict[str, Any] = {
                "status": "empty",
                "rows": [],
                "summary": {"issuer": issuer, "total_debt_usd_bn": 0.0, "currency": currency, "source_mode": "no_live_source"},
                "reason": reason,
                "next_actions": next_actions,
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICT,
            }
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=data,
                sources=["no_live_source"],
                warnings=[reason],
                metadata={"data_mode": "empty", "as_of": _as_of()},
            )

        # 2) sovereign issuer -> honest empty (SEC corporate ladder N/A)
        if _is_sovereign(issuer) or issuer == "UNSPECIFIED_ISSUER":
            return _empty_schedule(
                "Sovereign/unspecified issuer: SEC corporate maturity schedule does not apply; no debt ladder is shown.",
                next_actions=[
                    "Pass an explicit ``maturities`` schedule for this issuer.",
                    "Pick a tickerable US corporate issuer to read the SEC EDGAR maturity ladder.",
                ],
            )

        # 3) corporate -> SEC EDGAR maturity concepts
        ticker = issuer.split()[0].upper()
        started = time.monotonic()
        try:
            client = await get_client()
            cik = await _sec_lookup_cik(client, ticker)
            if not cik:
                return _empty_schedule(
                    f"No SEC CIK for ticker {ticker!r}; no maturity ladder can be derived.",
                    next_actions=[f"Use a tickerable US issuer or pass an explicit ``maturities`` schedule for {ticker!r}."],
                )
            r = await client.get(_SEC_FACTS_URL.format(cik=cik), headers={"User-Agent": _SEC_UA})
            r.raise_for_status()
            facts = r.json()
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - started) * 1000)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "summary": {"issuer": issuer, "total_debt_usd_bn": 0.0, "currency": currency, "source_mode": "sec_edgar"},
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                    "next_actions": ["Retry when SEC EDGAR (data.sec.gov) is reachable."],
                },
                sources=["sec_edgar"],
                warnings=[f"SEC EDGAR unreachable: {exc}"],
                metadata={"latency_ms": latency_ms, "data_mode": "provider_unavailable", "as_of": _as_of()},
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        y1 = _first_fact(facts, ("LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths", "LongTermDebtMaturitiesRepaymentsOfPrincipalRemainderOfFiscalYear"))
        y2 = _first_fact(facts, ("LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",))
        y3 = _first_fact(facts, ("LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree",))
        y4 = _first_fact(facts, ("LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour",))
        y5 = _first_fact(facts, ("LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive",))
        beyond = _first_fact(facts, ("LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive",))

        def _bn(fact: tuple[float, str] | None) -> float:
            return round(fact[0] / 1e9, 4) if fact else 0.0

        b_0_1 = _bn(y1)
        b_1_3 = _bn(y2) + _bn(y3)
        b_3_5 = _bn(y4) + _bn(y5)
        b_5p = _bn(beyond)

        if (b_0_1 + b_1_3 + b_3_5 + b_5p) <= 0:
            return _empty_schedule(
                f"SEC companyfacts for CIK {cik} did not expose long-term-debt maturity concepts; no maturity ladder is shown.",
                next_actions=[
                    f"Pass an explicit ``maturities`` schedule for {ticker!r}.",
                    "Retry after the issuer's latest 10-K/10-Q posts companyfacts maturity concepts.",
                ],
            )

        rows, total = self._finalize_rows([
            {"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": b_0_1, "currency": currency},
            {"bucket": "1-3Y", "tenor_years": 2.0, "amount_usd_bn": b_1_3, "currency": currency},
            {"bucket": "3-5Y", "tenor_years": 4.0, "amount_usd_bn": b_3_5, "currency": currency},
            {"bucket": "5Y+", "tenor_years": 7.0, "amount_usd_bn": b_5p, "currency": currency},
        ])
        fin_date = next((f[1] for f in (y1, y2, beyond) if f is not None), _as_of())
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": rows,
                "summary": {"issuer": issuer, "cik": cik, "total_debt_usd_bn": total, "currency": currency, "source_mode": "sec_edgar"},
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICT,
            },
            sources=["sec_edgar"],
            metadata={"latency_ms": latency_ms, "data_mode": "live_official", "as_of": fin_date},
        )


# ---------------------------------------------------------------------------
# DEBT — sovereign debt-to-GDP from World Bank (keyless)
# ---------------------------------------------------------------------------


@FunctionRegistry.register
class DEBTFunction(BaseFunction):
    code = "DEBT"
    name = "Sovereign Debt Exposure"
    category = "bond"

    _METHODOLOGY = (
        "DEBT pulls live general-government debt-to-GDP from the World Bank indicator API "
        f"({_WB_DEBT_TO_GDP}, keyless) for each requested country, taking the most recent "
        "non-null annual observation. local_currency_share is a published reference where the "
        "World Bank does not expose a keyless series. portfolio_weight_pct is 0 unless portfolio "
        "holdings are wired (``summary.portfolio_linked`` reports the state). Supplying "
        "``exposures`` directly bypasses the World Bank fetch."
    )
    _FIELD_DICT = {
        "country": "ISO-2 country code.",
        "debt_to_gdp": "General government debt as percent of GDP (World Bank, latest annual).",
        "local_currency_share": "Reference share of sovereign debt issued in local currency.",
        "portfolio_weight_pct": "Portfolio country weight; zero when no portfolio link.",
        "year": "Year of the World Bank debt-to-GDP observation.",
    }
    # Reference local-currency shares (broad, stable; labelled as reference).
    _LOCAL_CCY_REF = {
        "US": 99.0, "JP": 92.0, "DE": 96.0, "GB": 97.0, "FR": 95.0,
        "IT": 94.0, "TR": 56.0, "BR": 90.0, "MX": 80.0, "ZA": 89.0,
        "IN": 96.0, "CN": 98.0, "ES": 95.0, "CA": 98.0, "AU": 97.0,
    }

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        raw_countries = params.get("countries")
        country_filter = [
            str(item).strip().upper()
            for item in (raw_countries if isinstance(raw_countries, (list, tuple, set)) else str(raw_countries or "").split(","))
            if str(item).strip()
        ]

        # 1) user-supplied exposures -> verbatim (still honour country filter)
        if params.get("exposures") is not None:
            rows = list(params.get("exposures") or [])
            if country_filter:
                rows = [r for r in rows if str(r.get("country", "")).upper() in set(country_filter)]
            avg = round(sum(float(r.get("debt_to_gdp") or 0) for r in rows) / len(rows), 2) if rows else 0.0
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "ok",
                    "rows": rows,
                    "summary": {"countries": len(rows), "avg_debt_to_gdp": avg, "measure": "user_supplied", "portfolio_linked": False},
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                },
                sources=["user_input"],
                metadata={"data_mode": "user_input", "as_of": _as_of()},
            )

        countries = country_filter or _DEFAULT_DEBT_COUNTRIES
        # Normalise to ISO-2 keys for output, ISO-3 for the API.
        normalised: list[str] = []
        for c in countries:
            iso2 = _ISO3_TO_ISO2.get(c, c)
            if iso2 not in normalised:
                normalised.append(iso2)
        # Codes with no World Bank mapping are named in the response, never
        # silently dropped from the requested set.
        unsupported = [c for c in normalised if c not in _ISO2_TO_ISO3]
        normalised = [c for c in normalised if c in _ISO2_TO_ISO3]
        unsupported_warning = (
            [f"Unsupported country code(s) not fetched: {', '.join(unsupported)}."]
            if unsupported else []
        )
        if not normalised:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": f"No World Bank debt series for: {', '.join(unsupported)}.",
                    "rows": [],
                    "summary": {"countries": 0, "avg_debt_to_gdp": 0.0, "measure": "world_bank", "portfolio_linked": False, "unsupported_countries": unsupported},
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                    "next_actions": ["Use ISO-2 codes that the World Bank publishes, such as US, DE, JP or BR."],
                },
                sources=[],
                warnings=unsupported_warning,
            )

        started = time.monotonic()
        rows: list[dict[str, Any]] = []
        any_error: Exception | None = None
        import asyncio
        try:
            client = await get_client()

            async def _fetch_one(iso2: str) -> dict[str, Any] | None:
                iso3 = _ISO2_TO_ISO3.get(iso2)
                if not iso3:
                    return None
                try:
                    r = await client.get(
                        _WORLDBANK_URL.format(iso=iso3, code=_WB_DEBT_TO_GDP),
                        params={"format": "json", "per_page": "60"},
                        timeout=4.0,
                    )
                    r.raise_for_status()
                    payload = r.json()
                except Exception as exc:  # noqa: BLE001 — per-country tolerant
                    nonlocal any_error
                    any_error = exc
                    return None
                series = payload[1] if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list) else []
                latest = next((obs for obs in series if obs.get("value") is not None), None)
                if latest is None:
                    return None
                return {
                    "country": iso2,
                    "debt_to_gdp": round(float(latest["value"]), 2),
                    "local_currency_share": self._LOCAL_CCY_REF.get(iso2, 0.0),
                    "portfolio_weight_pct": 0.0,
                    "year": latest.get("date"),
                }

            results = await asyncio.gather(*(_fetch_one(iso2) for iso2 in normalised))
            rows = [r for r in results if r is not None]
        except Exception as exc:  # noqa: BLE001
            any_error = exc

        latency_ms = int((time.monotonic() - started) * 1000)

        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "summary": {"countries": 0, "avg_debt_to_gdp": 0.0, "measure": "world_bank", "portfolio_linked": False},
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                    "next_actions": ["Retry when the World Bank API (api.worldbank.org) is reachable."],
                },
                sources=["worldbank"],
                warnings=[f"World Bank debt-to-GDP fetch returned no data{f': {any_error}' if any_error else ''}.", *unsupported_warning],
                metadata={"latency_ms": latency_ms, "data_mode": "provider_unavailable", "as_of": _as_of()},
            )

        avg = round(sum(r["debt_to_gdp"] for r in rows) / len(rows), 2)
        warnings = ["local_currency_share is a published reference, not a live World Bank series.", *unsupported_warning]
        if any_error:
            warnings.append("Some countries were skipped due to World Bank fetch errors.")
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "rows": rows,
                "summary": {"countries": len(rows), "avg_debt_to_gdp": avg, "measure": "world_bank_debt_to_gdp", "portfolio_linked": False, "unsupported_countries": unsupported},
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICT,
            },
            sources=["worldbank"],
            warnings=warnings,
            metadata={"latency_ms": latency_ms, "data_mode": "live_official", "as_of": _as_of()},
        )


# ---------------------------------------------------------------------------
# ALLQ — indicative dealer ladder anchored to a REAL reference yield
# ---------------------------------------------------------------------------

# Labelled modelling assumption: the coupon of the reference bond whose clean
# price is derived from the tenor's par yield. It is disclosed in the summary.
_ALLQ_REF_COUPON_PCT = 4.0
# Source marker for the modelled ladder; "_model" classifies rows as model.
_ALLQ_MODEL_SOURCE = "allq_ladder_model"


def _allq_reference_price(yield_pct: float, years: float, coupon_pct: float = _ALLQ_REF_COUPON_PCT) -> float:
    """Clean price of a reference bond with ``coupon_pct`` discounted at ``yield_pct``.

    Notes/bonds (> 1Y): exact semi-annual cash flows. Bills (<= 1Y): zero-coupon
    simple discounting. Both use the tenor's own years, so tenors price apart.
    """
    if years <= 1.0:
        return 100.0 / (1.0 + yield_pct / 100.0 * years)
    freq = 2
    n = max(1, round(years * freq))
    r = yield_pct / 100.0 / freq
    c = coupon_pct / freq
    if r == 0:
        return c * n + 100.0
    return c * (1.0 - (1.0 + r) ** -n) / r + 100.0 * (1.0 + r) ** -n


def _allq_ref_coupon_pct(years: float) -> float | None:
    """Reference-bond coupon disclosed for a tenor; ``None`` for bills (zero-coupon discount)."""
    return None if years <= 1.0 else _ALLQ_REF_COUPON_PCT


def _allq_observation_date(value: Any) -> str:
    day = value.date() if hasattr(value, "date") else value
    return day.isoformat() if hasattr(day, "isoformat") else str(day)


@FunctionRegistry.register
class ALLQFunction(BaseFunction):
    code = "ALLQ"
    name = "Dealer Quotes (TRACE proxy)"
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    _METHODOLOGY = (
        "ALLQ builds an INDICATIVE dealer-quote ladder anchored to a REAL reference yield. "
        "Only US Treasury tenors on the keyless US Treasury daily par-yield curve (US1M to US30Y) "
        "are anchored: the tenor's latest par yield is discounted to a clean price of a reference "
        "bond with a labelled 4% coupon (exact semi-annual cash flows; bills up to 1Y use simple "
        "discounting). Other symbols, including share prices, get no anchor and return "
        "provider_unavailable. The ladder spreads a bid/ask around that mid: composite A spread/2; "
        "composite B -0.7/+0.8 spread; composite C full spread. Rows are MODELED from one anchor and "
        "one spread input, not observed dealer or TRACE quotes, so they are INDICATIVE and not "
        "executable. mid, spread_points and spread_bps_of_price are (bid+ask)/2, ask-bid and "
        "(spread/mid)*10000. quote_time is the Treasury observation date (end-of-day curve, no time "
        "published). An explicit mid input overrides the reference and is labelled user_input."
    )
    _FIELD_DICT = {
        "dealer": "Composite/indicative quote source label.",
        "bid": "Indicative bid price (modeled from the reference anchor).",
        "ask": "Indicative ask price (modeled from the reference anchor).",
        "mid": "Average of bid and ask.",
        "size": "Indicative notional size.",
        "spread_points": "Bid/ask spread in price points.",
        "spread_bps_of_price": "Bid/ask spread in basis points of mid.",
        "synthetic": "Always true: rows are modeled from one reference anchor and one spread input, never observed dealer or TRACE quotes.",
        "quote_time": "Observation date of the reference yield (end-of-day curve), or the request time for an operator-supplied mid.",
    }

    async def _ustreasury_curve_anchor(self, symbol: str) -> tuple[float, str, str, str] | None:
        """Per-tenor anchor from the keyless US Treasury par-yield curve.

        Returns ``(clean_price, source, ref_note, as_of_date)`` or ``None``; see
        ``_ustreasury_curve_anchor_detail`` for the failure reason.
        """
        anchor, _failure = await self._ustreasury_curve_anchor_detail(symbol)
        return anchor

    async def _ustreasury_curve_anchor_detail(
        self, symbol: str
    ) -> tuple[tuple[float, str, str, str] | None, str | None]:
        """Per-tenor anchor plus the reason a fetch failed.

        Returns ``(anchor, failure)``. ``anchor`` is ``(clean_price, source,
        ref_note, as_of_date)``: the tenor's latest observed par yield discounted
        to a reference-bond clean price. ``failure`` names the curve fetch error
        when the adapter raised, so the caller can report it; it is ``None`` when
        the adapter is absent, the symbol is not a US curve tenor, or the tenor
        simply has no observation.
        """
        import math

        provider = getattr(self.deps, "ustreasury", None)
        upper = str(symbol).upper()
        column = _US_TREASURY_TENOR_COLUMNS.get(upper)
        if provider is None or column is None:
            return None, None
        try:
            curve = await provider.yield_curve()
        except Exception as exc:  # noqa: BLE001 — reported by the ALLQ caller, never silent
            return None, f"Treasury curve fetch failed ({type(exc).__name__}: {exc})"
        if not hasattr(curve, "columns") or column not in curve.columns:
            return None, None
        series = curve[column].dropna()
        if series.empty:
            return None, None
        try:
            yld = float(series.iloc[-1])
        except (TypeError, ValueError):
            return None, None
        if not math.isfinite(yld):
            return None, None
        as_of = _allq_observation_date(series.index[-1])
        years = float(_US_TREASURY_TENOR_YEARS.get(upper, 10.0))
        price = round(_allq_reference_price(yld, years), 4)
        basis = (
            "zero-coupon simple discount"
            if _allq_ref_coupon_pct(years) is None
            else f"reference bond {_ALLQ_REF_COUPON_PCT:.0f}% coupon"
        )
        note = f"Treasury {column} par yield {yld:.3f}% on {as_of} (per-tenor, keyless curve; {basis})"
        return (price, "ustreasury", note, as_of), None

    def _build_ladder(
        self, symbol: str, anchor: float, spread: float, size: float, ref_note: str, quote_time: str
    ) -> list[dict[str, Any]]:
        quotes = [
            {"bond": symbol, "dealer": "Composite A", "bid": anchor - spread / 2, "ask": anchor + spread / 2, "size": size, "quote_time": quote_time},
            {"bond": symbol, "dealer": "Composite B", "bid": anchor - spread * 0.7, "ask": anchor + spread * 0.8, "size": size * 0.75, "quote_time": quote_time},
            {"bond": symbol, "dealer": "Composite C", "bid": anchor - spread, "ask": anchor + spread, "size": size * 0.5, "quote_time": quote_time},
        ]
        for q in quotes:
            q["bid"] = round(float(q["bid"]), 6)
            q["ask"] = round(float(q["ask"]), 6)
            q["mid"] = round((q["bid"] + q["ask"]) / 2, 6)
            q["spread_points"] = round(q["ask"] - q["bid"], 6)
            q["spread_bps_of_price"] = round((q["spread_points"] / q["mid"]) * 10_000, 3) if q["mid"] else 0.0
            q["reference"] = ref_note
            q["synthetic"] = True
        return quotes

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbol = _bond_symbol(instrument, params)
        spread = float(params.get("spread", params.get("spread_points", 0.18)))
        size = float(params.get("size", 1_000_000))
        user_mid = params.get("mid")
        us_tenor = symbol in _US_TREASURY_TENOR_COLUMNS

        started = time.monotonic()
        anchor: float | None = None
        source = "ustreasury"
        ref_note = ""
        as_of = _as_of()
        quote_time = _now_iso()
        fetch_error: Exception | None = None
        curve_failure: str | None = None
        try:
            got = None
            if us_tenor:
                got, curve_failure = await self._ustreasury_curve_anchor_detail(symbol)
            if got is not None:
                anchor, source, ref_note, as_of = got
                quote_time = f"{as_of}T00:00:00+00:00"
        except Exception as exc:  # noqa: BLE001
            fetch_error = exc

        latency_ms = int((time.monotonic() - started) * 1000)

        # An explicit operator mid overrides the reference and is labelled as such.
        if user_mid not in (None, ""):
            try:
                anchor = float(user_mid)
            except (TypeError, ValueError):
                return FunctionResult(
                    code=self.code,
                    instrument=instrument,
                    data={
                        "status": "input_error",
                        "rows": [],
                        "spread_curve": [],
                        "summary": {"bond": symbol, "source_mode": "user_input"},
                        "methodology": self._METHODOLOGY,
                        "field_dictionary": self._FIELD_DICT,
                        "next_actions": ["Pass ``mid`` as a number, or omit it to use the live reference."],
                    },
                    sources=[],
                    warnings=[f"Operator mid {user_mid!r} is not a number."],
                    metadata={"latency_ms": latency_ms, "data_mode": "explicit_unavailable", "as_of": _as_of()},
                )
            reference = f"; overrides {ref_note}" if ref_note else ""
            source = "user_input"
            ref_note = f"operator-supplied mid {anchor}{reference}"
            as_of = _as_of()
            quote_time = _now_iso()

        # Without a live Treasury observation or an explicit mid: honest unavailable state.
        if anchor is None:
            reason = (
                f"No Treasury curve observation for {symbol!r}"
                if us_tenor
                else f"{symbol!r} is not a US Treasury tenor on the keyless curve; no reference yield is anchored"
            )
            detail = curve_failure or (str(fetch_error) if fetch_error else None)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "spread_curve": [],
                    "summary": {"bond": symbol, "source_mode": "unavailable"},
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                    "next_actions": ["Retry when the Treasury curve is reachable, or pass an explicit ``mid``."],
                },
                sources=[source] if us_tenor else [],
                warnings=[f"{reason}{f': {detail}' if detail else ''}."],
                metadata={"latency_ms": latency_ms, "data_mode": "provider_unavailable", "as_of": _as_of()},
            )

        quotes = self._build_ladder(symbol, anchor, spread, size, ref_note, quote_time)
        warnings = [
            "ALLQ rows are INDICATIVE composite quotes modeled from one reference anchor and one spread input, not executable dealer prices.",
            f"The {spread:g}-point spread is an input assumption applied to every tenor, not a measured dealer or TRACE spread.",
        ]
        if source == "user_input":
            warnings.append("The mid is the operator-supplied value; it overrides the Treasury reference and is not a market observation.")
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": quotes,
                "spread_curve": [{"dealer": q["dealer"], "spread_bps_of_price": q["spread_bps_of_price"]} for q in quotes],
                "summary": {
                    "bond": symbol,
                    "synthetic": True,
                    "mid": round(anchor, 6),
                    "best_bid": max(q["bid"] for q in quotes),
                    "best_ask": min(q["ask"] for q in quotes),
                    "reference": ref_note,
                    "reference_coupon_pct": (
                        _allq_ref_coupon_pct(_US_TREASURY_TENOR_YEARS.get(symbol, 10.0))
                        if source != "user_input"
                        else None
                    ),
                    "spread_points_input": spread,
                    "as_of": as_of,
                    "source_mode": "indicative_anchored_to_real_reference" if source != "user_input" else "indicative_user_mid",
                },
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICT,
            },
            sources=[source, _ALLQ_MODEL_SOURCE],
            warnings=warnings,
            metadata={
                "latency_ms": latency_ms,
                "data_mode": "user_input" if source == "user_input" else "modeled",
                "as_of": as_of,
            },
        )


# GC3D is canonically registered via showme.engine.functions.bond.gc3d (GC3DFunctionLive).
# The legacy stub here was deleted to avoid the duplicate-code drift flagged in
# ARCH-10/PY-LINT-08.
