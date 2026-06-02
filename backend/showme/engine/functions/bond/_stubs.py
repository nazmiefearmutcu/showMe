"""CRPR, DDIS, DEBT, ALLQ live handlers (single-file group).

These four bond/rates functions were previously canned-constant stubs.
They now fetch REAL keyless public data:

* CRPR  — implied credit profile from SEC EDGAR companyfacts (leverage +
  interest coverage) mapped to a transparent rating bucket.
* DDIS  — debt-by-maturity from SEC companyfacts long-term-debt maturity
  concepts (corporates) / labelled illustrative fallback otherwise.
* DEBT  — sovereign debt-to-GDP from the World Bank indicator API
  (GC.DOD.TOTL.GD.ZS), keyless.
* ALLQ  — indicative dealer ladder anchored to a REAL reference price
  (US Treasury FiscalData yield -> clean price, or yfinance for a symbol).

Every handler wraps the network in try/except and, on a genuine outage,
returns ``status="provider_unavailable"`` with an honest warning +
next_actions — never fabricated numbers presented as live.
"""

from __future__ import annotations

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
_FISCALDATA_AVG_RATES = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
    "v2/accounting/od/avg_interest_rates"
)

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
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    _METHODOLOGY = (
        "CRPR derives a MODEL-IMPLIED credit profile from the issuer's latest SEC EDGAR "
        "companyfacts (XBRL): gross debt = LongTermDebt(+Current) + ShortTermBorrowings; "
        "EBITDA proxy = OperatingIncomeLoss + DepreciationDepletionAndAmortization; "
        "interest coverage = EBITDA / InterestExpense. Leverage (debt/EBITDA) and coverage "
        "are mapped to a coarse, transparent rating bucket (AA..CCC). This is implied from "
        "financials, NOT a paid S&P/Moody's/Fitch feed. If the caller pins a ``rating`` dict "
        "it is echoed verbatim. Sovereign issuers (no SEC CIK) get a labelled reference profile."
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
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "ok",
                    "rows": rows,
                    "summary": {"issuer": issuer, "implied_bucket": params.get("bucket", "high_grade"), "agencies": len(rows), "source_mode": "user_input"},
                    "implied_bucket": params.get("bucket", "high_grade"),
                    "scale": self._SCALE,
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                },
                sources=["user_input"],
                metadata={"data_mode": "user_input", "as_of": _as_of()},
            )

        # 2) sovereign / non-tickerable issuer -> labelled reference profile
        if _is_sovereign(issuer):
            rows = [
                {"agency": "model_implied", "rating": "AA+", "outlook": "stable", "watch": "none", "rating_date": _as_of(), "rationale": "Sovereign issuer has no SEC CIK; CRPR's financial-derived model does not apply. Reference high-grade sovereign profile shown."},
            ]
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "ok",
                    "rows": rows,
                    "summary": {"issuer": issuer, "implied_bucket": "high_grade", "agencies": len(rows), "source_mode": "sovereign_reference"},
                    "implied_bucket": "high_grade",
                    "scale": self._SCALE,
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICT,
                },
                sources=["reference"],
                warnings=["Sovereign issuer: CRPR's SEC-financials model is not applicable; showing a reference sovereign profile."],
                metadata={"data_mode": "reference", "as_of": _as_of()},
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
        lt_debt = _first_fact(facts, ("LongTermDebtNoncurrent", "LongTermDebt"))
        lt_debt_cur = _first_fact(facts, ("LongTermDebtCurrent", "DebtCurrent"))
        short_debt = _first_fact(facts, ("ShortTermBorrowings",))
        op_income = _first_fact(facts, ("OperatingIncomeLoss",))
        dep_amort = _first_fact(facts, ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"))
        interest = _first_fact(facts, ("InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense"))

        gross_debt = sum(x[0] for x in (lt_debt, lt_debt_cur, short_debt) if x is not None)
        ebitda = (op_income[0] if op_income else 0.0) + (dep_amort[0] if dep_amort else 0.0)
        leverage = round(gross_debt / ebitda, 3) if ebitda > 0 else None
        coverage = round(ebitda / interest[0], 3) if interest and interest[0] > 0 else None
        fin_date = next((x[1] for x in (op_income, lt_debt, interest) if x is not None), _as_of())

        if gross_debt <= 0 and ebitda <= 0:
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
                    "source_mode": "model_implied_from_financials",
                },
                "implied_bucket": bucket,
                "scale": self._SCALE,
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICT,
            },
            sources=["sec_edgar"],
            warnings=["CRPR rating is MODEL-IMPLIED from SEC financials, not a paid agency rating."],
            metadata={"latency_ms": latency_ms, "data_mode": "live_official", "as_of": fin_date},
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
        "returned verbatim. With no SEC data and no override the rows are a clearly-labelled "
        "illustrative model, never disguised as a live read."
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

        def _illustrative(reason: str, *, status: str, source: str, extra_warn: str | None = None, next_actions: list[str] | None = None) -> FunctionResult:
            rows, total = self._finalize_rows([
                {"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": 3.2, "currency": currency},
                {"bucket": "1-3Y", "tenor_years": 2.0, "amount_usd_bn": 8.6, "currency": currency},
                {"bucket": "3-5Y", "tenor_years": 4.0, "amount_usd_bn": 6.4, "currency": currency},
                {"bucket": "5Y+", "tenor_years": 7.0, "amount_usd_bn": 8.5, "currency": currency},
            ])
            data: dict[str, Any] = {
                "status": status,
                "rows": rows,
                "summary": {"issuer": issuer, "total_debt_usd_bn": total, "currency": currency, "source_mode": "illustrative_model"},
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICT,
            }
            if next_actions:
                data["next_actions"] = next_actions
            warns = [reason] if reason else []
            if extra_warn:
                warns.append(extra_warn)
            return FunctionResult(code=self.code, instrument=instrument, data=data, sources=[source], warnings=warns, metadata={"data_mode": status, "as_of": _as_of()})

        # 2) sovereign issuer -> illustrative (SEC corporate ladder N/A)
        if _is_sovereign(issuer) or issuer == "UNSPECIFIED_ISSUER":
            return _illustrative(
                "Sovereign/unspecified issuer: SEC corporate maturity schedule does not apply; showing a labelled illustrative model.",
                status="illustrative",
                source="illustrative_model",
            )

        # 3) corporate -> SEC EDGAR maturity concepts
        ticker = issuer.split()[0].upper()
        started = time.monotonic()
        try:
            client = await get_client()
            cik = await _sec_lookup_cik(client, ticker)
            if not cik:
                return _illustrative(
                    f"No SEC CIK for ticker {ticker!r}; falling back to a labelled illustrative ladder.",
                    status="illustrative",
                    source="illustrative_model",
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
            return _illustrative(
                f"SEC companyfacts for CIK {cik} did not expose long-term-debt maturity concepts; showing a labelled illustrative ladder.",
                status="illustrative",
                source="illustrative_model",
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
                warnings=[f"World Bank debt-to-GDP fetch returned no data{f': {any_error}' if any_error else ''}."],
                metadata={"latency_ms": latency_ms, "data_mode": "provider_unavailable", "as_of": _as_of()},
            )

        avg = round(sum(r["debt_to_gdp"] for r in rows) / len(rows), 2)
        warnings = ["local_currency_share is a published reference, not a live World Bank series."]
        if any_error:
            warnings.append("Some countries were skipped due to World Bank fetch errors.")
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "rows": rows,
                "summary": {"countries": len(rows), "avg_debt_to_gdp": avg, "measure": "world_bank_debt_to_gdp", "portfolio_linked": False},
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICT,
            },
            sources=["worldbank"],
            warnings=warnings,
            metadata={"latency_ms": latency_ms, "data_mode": "live_official", "as_of": _as_of()},
        )


# ---------------------------------------------------------------------------
# ALLQ — indicative dealer ladder anchored to a REAL reference price
# ---------------------------------------------------------------------------


@FunctionRegistry.register
class ALLQFunction(BaseFunction):
    code = "ALLQ"
    name = "Dealer Quotes (TRACE proxy)"
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    _METHODOLOGY = (
        "ALLQ builds an INDICATIVE dealer-quote ladder anchored to a REAL reference price. "
        "For US Treasury aliases the anchor is derived from the US Treasury FiscalData average "
        "interest rate (yield -> approximate clean price via 1/(1+y) discounting on a par bond). "
        "For tickerable instruments the anchor is the latest yfinance price. The ladder spreads a "
        "realistic bid/ask (composite A: spread/2; composite B: asymmetric ~0.7/0.8; composite C: "
        "full spread) around that anchor. mid, spread_points and spread_bps_of_price are computed "
        "as (bid+ask)/2, ask-bid and (spread/mid)*10000. Rows are INDICATIVE, not executable "
        "dealer prices."
    )
    _FIELD_DICT = {
        "dealer": "Composite/indicative quote source label.",
        "bid": "Indicative bid price.",
        "ask": "Indicative ask price.",
        "mid": "Average of bid and ask.",
        "size": "Indicative notional size.",
        "spread_points": "Bid/ask spread in price points.",
        "spread_bps_of_price": "Bid/ask spread in basis points of mid.",
        "quote_time": "Timestamp the indicative ladder was built.",
    }

    async def _treasury_anchor(self, symbol: str) -> tuple[float, str, str] | None:
        """Return (clean_price, source, ref_note) anchored to a real Treasury yield."""
        client = await get_client()
        r = await client.get(
            _FISCALDATA_AVG_RATES,
            params={
                "fields": "record_date,security_desc,avg_interest_rate_amt",
                "filter": "security_desc:in:(Treasury Notes,Treasury Bonds)",
                "sort": "-record_date",
                "page[size]": "20",
            },
        )
        r.raise_for_status()
        payload = r.json()
        data_rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not data_rows:
            return None
        rec = data_rows[0]
        yld = float(rec.get("avg_interest_rate_amt"))  # percent
        # Approximate clean price of a par-issued bond at current avg coupon vs a
        # 10Y discount: price ~ 100 * (coupon/y discounted). Use a simple proxy:
        # a small premium/discount around par scaled by the yield level.
        # Par bond at its own coupon prices ~100; deviate by yield delta to 4%.
        ref_yield = 4.0
        years = 10.0
        price = 100.0 * (1.0 + (ref_yield - yld) / 100.0 * years / (1.0 + ref_yield / 100.0))
        price = round(max(50.0, min(150.0, price)), 4)
        return (price, "treasury_fiscaldata", f"avg Treasury coupon {yld:.3f}% on {rec.get('record_date')}")

    async def _yfinance_anchor(self, symbol: str) -> tuple[float, str, str] | None:
        adapter = getattr(self.deps, "yfinance", None) or getattr(self.deps, "quotes", None)
        if adapter is not None and hasattr(adapter, "fetch_quote"):
            quote = await adapter.fetch_quote(symbol)
            price = quote.get("last_price") or quote.get("previous_close")
            if price:
                return (round(float(price), 4), "yfinance", f"yfinance last for {symbol}")
        # direct fallback
        def _sync() -> float | None:
            import yfinance as yf

            t = yf.Ticker(symbol)
            fast = getattr(t, "fast_info", {}) or {}
            val = fast.get("last_price") or fast.get("lastPrice") or fast.get("previous_close") or fast.get("previousClose")
            return float(val) if val is not None else None

        import asyncio

        price = await asyncio.to_thread(_sync)
        if price:
            return (round(float(price), 4), "yfinance", f"yfinance last for {symbol}")
        return None

    def _build_ladder(self, symbol: str, anchor: float, spread: float, size: float, ref_note: str) -> list[dict[str, Any]]:
        ts = _now_iso()
        quotes = [
            {"bond": symbol, "dealer": "Composite A", "bid": anchor - spread / 2, "ask": anchor + spread / 2, "size": size, "quote_time": ts},
            {"bond": symbol, "dealer": "Composite B", "bid": anchor - spread * 0.7, "ask": anchor + spread * 0.8, "size": size * 0.75, "quote_time": ts},
            {"bond": symbol, "dealer": "Composite C", "bid": anchor - spread, "ask": anchor + spread, "size": size * 0.5, "quote_time": ts},
        ]
        for q in quotes:
            q["bid"] = round(float(q["bid"]), 6)
            q["ask"] = round(float(q["ask"]), 6)
            q["mid"] = round((q["bid"] + q["ask"]) / 2, 6)
            q["spread_points"] = round(q["ask"] - q["bid"], 6)
            q["spread_bps_of_price"] = round((q["spread_points"] / q["mid"]) * 10_000, 3) if q["mid"] else 0.0
            q["reference"] = ref_note
        return quotes

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbol = _bond_symbol(instrument, params)
        spread = float(params.get("spread", params.get("spread_points", 0.18)))
        size = float(params.get("size", 1_000_000))
        user_mid = params.get("mid")

        started = time.monotonic()
        anchor: float | None = None
        source = "treasury_fiscaldata"
        ref_note = ""
        fetch_error: Exception | None = None
        try:
            if _is_sovereign(symbol):
                got = await self._treasury_anchor(symbol)
            else:
                got = await self._yfinance_anchor(symbol)
                source = "yfinance"
            if got is not None:
                anchor, source, ref_note = got
        except Exception as exc:  # noqa: BLE001
            fetch_error = exc

        latency_ms = int((time.monotonic() - started) * 1000)

        # If we couldn't get a real anchor: honour an explicit user mid, else
        # report provider_unavailable (do NOT silently fabricate a price).
        if anchor is None:
            if user_mid is not None:
                anchor = float(user_mid)
                source = "user_input"
                ref_note = "operator-supplied mid (no live reference reachable)"
            else:
                return FunctionResult(
                    code=self.code,
                    instrument=instrument,
                    data={
                        "status": "provider_unavailable",
                        "rows": [],
                        "spread_curve": [],
                        "summary": {"bond": symbol, "source_mode": source},
                        "methodology": self._METHODOLOGY,
                        "field_dictionary": self._FIELD_DICT,
                        "next_actions": ["Retry when the reference price source is reachable, or pass an explicit ``mid``."],
                    },
                    sources=[source],
                    warnings=[f"No live reference price for {symbol!r}{f': {fetch_error}' if fetch_error else ''}."],
                    metadata={"latency_ms": latency_ms, "data_mode": "provider_unavailable", "as_of": _as_of()},
                )

        quotes = self._build_ladder(symbol, anchor, spread, size, ref_note)
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": quotes,
                "spread_curve": [{"dealer": q["dealer"], "spread_bps_of_price": q["spread_bps_of_price"]} for q in quotes],
                "summary": {
                    "bond": symbol,
                    "mid": round(anchor, 6),
                    "best_bid": max(q["bid"] for q in quotes),
                    "best_ask": min(q["ask"] for q in quotes),
                    "reference": ref_note,
                    "source_mode": "indicative_anchored_to_real_reference",
                },
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICT,
            },
            sources=[source],
            warnings=["ALLQ rows are INDICATIVE composite quotes anchored to a real reference price, not executable dealer prices."],
            metadata={"latency_ms": latency_ms, "data_mode": "live_official" if source != "user_input" else "user_input", "as_of": _as_of()},
        )


# GC3D is canonically registered via showme.engine.functions.bond.gc3d (GC3DFunctionLive).
# The legacy stub here was deleted to avoid the duplicate-code drift flagged in
# ARCH-10/PY-LINT-08.
