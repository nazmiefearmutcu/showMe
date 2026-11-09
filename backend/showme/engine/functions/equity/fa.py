"""FA — Financial Analysis (income / balance / cash flow).

DATA PIPELINE:
  Source: SEC EDGAR XBRL (primary, US-only canonical), yfinance (fallback, global)
  Cache:  DuckDB ``fundamentals`` (Faz 2 sonu) + 24h refdata cache
  Latency: <2s
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class FAFunction(BaseFunction):
    code = "FA"
    name = "Financial Analysis"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"
    description = "Income statement + balance sheet + cash flow, son 5 yıl trendi."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("FA requires an instrument")
        period = params.get("period", "annual")
        if period not in SUPPORTED_PERIODS:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "symbol": instrument.symbol,
                    "status": "input_error",
                    "period": period,
                    "income_statement": [],
                    "balance_sheet": [],
                    "cash_flow": [],
                    "ratios": {},
                    "filing_date": None,
                    "reason": f"Unsupported period {period!r}; FA supports annual or quarterly.",
                    "next_actions": ["Set period to annual or quarterly."],
                },
                sources=[],
                warnings=[],
                metadata={"period": period, "format": "input_error"},
            )
        warnings: list[str] = []
        sources_used: list[str] = []

        sec_data = None
        try:
            if self.deps.sec_edgar:
                sec_data = await asyncio.wait_for(
                    self.deps.sec_edgar.standard_fundamentals(instrument.symbol, period=period),
                    timeout=float(params.get("sec_timeout", 8)),
                )
        except Exception as e:
            warnings.append(f"sec_edgar: {str(e) or type(e).__name__}")
        # An empty SEC dict (no us-gaap facts, e.g. IFRS/ADR filers) is NOT usable
        # statement data: it must fall through to yfinance rather than be shown.
        sec_usable = _has_statement_payload(sec_data)
        if sec_usable:
            sources_used.append("sec_edgar")
        elif sec_data is not None:
            warnings.append(f"sec_edgar: no us-gaap statement facts for {instrument.symbol}")

        yfin_data = None
        if not sec_usable:
            try:
                if self.deps.yfinance:
                    yfin_data = await asyncio.wait_for(
                        self.deps.yfinance.fetch(DataRequest(
                            kind=DataKind.FUNDAMENTALS, instrument=instrument,
                            extra={"period": period},
                        )),
                        timeout=float(params.get("yfinance_timeout", 8)),
                    )
                    # Listed only when yfinance actually supplied statements.
                    if _has_statement_payload(yfin_data):
                        sources_used.append("yfinance")
            except Exception as e:
                warnings.append(f"yfinance: {str(e) or type(e).__name__}")

        if sec_usable and isinstance(sec_data, dict):
            data = _normalise_fa_payload(
                instrument.symbol,
                period,
                "sec_edgar",
                sec_data=sec_data,
            )
            return FunctionResult(
                code=self.code, instrument=instrument,
                data=data,
                sources=sources_used, warnings=[],
                metadata={"period": period, "format": "canonical_fa"},
            )

        if _has_statement_payload(yfin_data):
            warnings = []
        if not _has_statement_payload(yfin_data):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_financial_unavailable_payload(instrument.symbol, period, warnings),
                sources=sources_used or ["no_live_source"],
                metadata={
                    "period": period,
                    "format": "provider_unavailable",
                    "fallback": True,
                    "degraded": True,
                    "provider_errors": warnings,
                    "requires_statement_feed": True,
                },
            )
        data = _normalise_fa_payload(
            instrument.symbol,
            period,
            "yfinance",
            yfin_data=yfin_data,
        )
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=sources_used,
            metadata={"period": period, "format": "canonical_fa", "provider_errors": warnings},
        )

    def _render_html(self, r: FunctionResult) -> str:
        data = r.data or {}
        rows: list[str] = []
        if isinstance(data, dict) and "income" in data:
            for label, df in data.items():
                if isinstance(df, pd.DataFrame) and not df.empty:
                    rows.append(f"<h3>{label.title()}</h3>{df.head(15).to_html(classes='showme-table')}")
        elif isinstance(data, dict):
            top = list(data.items())[:15]
            rows.append("<table class='showme-table'><thead><tr><th>field</th><th>latest</th></tr></thead><tbody>")
            for k, series in top:
                latest = series.iloc[-1] if hasattr(series, "iloc") and len(series) else "—"
                rows.append(f"<tr><td>{k}</td><td>{latest}</td></tr>")
            rows.append("</tbody></table>")
        return f"<section class='showme-fn fn-fa'><h2>FA — {r.instrument and r.instrument.symbol}</h2>{''.join(rows)}</section>"


SUPPORTED_PERIODS = ("annual", "quarterly")


def _sec_filed_date_for_period_end(data: dict[str, Any], period_end: str | None) -> str | None:
    """SEC ``filed`` date of the facts at ``period_end`` (never invented).

    The adapter attaches ``attrs["filed_by_end"]`` (period end -> filed date) to
    each series. Only the statement period shown is considered, so a later
    amendment to an older period does not become this period's filing date.
    Returns ``None`` when no series carries that date for ``period_end``.
    """
    if not period_end:
        return None
    filed: list[str] = []
    for value in data.values():
        attrs = getattr(value, "attrs", None)
        by_end = attrs.get("filed_by_end") if isinstance(attrs, dict) else None
        if isinstance(by_end, dict):
            day = by_end.get(period_end)
            if day:
                filed.append(str(day)[:10])
    return max(filed) if filed else None


def _has_statement_payload(payload: Any) -> bool:
    """True when a provider returned at least one non-empty statement / series."""
    if not isinstance(payload, dict):
        return bool(payload)
    for value in payload.values():
        if hasattr(value, "empty"):
            if not value.empty:
                return True
        elif value:
            return True
    return False


def _financial_unavailable_payload(
    symbol: str,
    period: Any,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "status": "provider_unavailable",
        "period": period,
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow": [],
        "ratios": {},
        "filing_date": None,
        "reason": "No SEC EDGAR or yfinance statement payload was returned.",
        "provider_errors": warnings,
        "next_actions": [
            "Connect a fundamentals provider or retry with a supported US equity ticker.",
        ],
    }


def _normalise_fa_payload(
    symbol: str,
    period: Any,
    source: str,
    *,
    sec_data: dict[str, Any] | None = None,
    yfin_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if sec_data is not None:
        canonical = _latest_canonical_values(sec_data)
        income_rows = _rows_from_canonical(sec_data, "income")
        balance_rows = _rows_from_canonical(sec_data, "balance")
        cash_rows = _rows_from_canonical(sec_data, "cash_flow")
        period_end = _latest_filing_date(sec_data)
        # The SEC ``filed`` date of the facts at the period end shown; period end is the data date.
        filing_date = _sec_filed_date_for_period_end(sec_data, period_end)
    else:
        yfin_data = yfin_data or {}
        canonical = _latest_yfinance_values(yfin_data)
        income_rows = _rows_from_frame(yfin_data.get("income"))
        balance_rows = _rows_from_frame(yfin_data.get("balance"))
        cash_rows = _rows_from_frame(yfin_data.get("cashflow"))
        period_end = _latest_filing_date(
            {
                k: v
                for k, v in {
                    "income": yfin_data.get("income"),
                    "balance": yfin_data.get("balance"),
                    "cashflow": yfin_data.get("cashflow"),
                }.items()
                if v is not None
            },
            from_frames=True,
        )
        # yfinance frames carry period-end columns only; no filing date is supplied.
        filing_date = None

    ratios = _compute_ratios(canonical)
    status = "ok" if ratios else "calc_error"
    retrieved_at = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "symbol": symbol,
        "status": status,
        "period": period,
        "source": source,
        "asOf": retrieved_at,
        "retrieved_at": retrieved_at,
        "period_end": period_end,
        "filing_date": filing_date,
        "income_statement": income_rows,
        "balance_sheet": balance_rows,
        "cash_flow": cash_rows,
        "ratios": ratios,
        "statement_counts": {
            "income_statement": len(income_rows),
            "balance_sheet": len(balance_rows),
            "cash_flow": len(cash_rows),
            "ratios": len(ratios),
        },
        "methodology": "FA normalizes income statement, balance sheet, and cash-flow rows into canonical line items, then computes ratios from latest available values. Ratios tab is only meaningful when the ratios payload is non-empty.",
        # Flow ratios (margins, ROA, ROE) use the period's own flows: a quarter for
        # period=quarterly, so they are single-quarter values and not annualized.
        "ratio_basis": (
            "single quarter flows over period-end balances; not annualized"
            if period == "quarterly"
            else "fiscal-year flows over period-end balances"
        ),
        "field_dictionary": {
            "gross_margin": "gross_profit / revenue.",
            "net_margin": "net_income / revenue.",
            "roe": "net_income / total_equity.",
            "debt_to_equity": "long_term_debt / total_equity; omitted when long-term debt is not reported.",
            "current_ratio": "current_assets / current_liabilities.",
            "free_cash_flow": "cash from operations minus capital expenditure when available.",
            "period_end": "Latest statement period end date (the data date).",
            "filing_date": "SEC filed date of the facts at period_end; null when not supplied by the source.",
            "retrieved_at": "Time this payload was built (retrieval time, not data date).",
        },
    }
    if status != "ok":
        payload["reason"] = "Unable to compute financial ratios from returned statement fields."
        payload["next_actions"] = [
            "Connect a provider that returns revenue, income, assets, equity, and cash-flow fields.",
        ]
    return payload


SEC_INCOME_FIELDS = {
    "revenue",
    "gross_profit",
    "grossProfit",
    "operating_income",
    "net_income",
    "eps_basic",
    "eps_diluted",
    "cost_of_revenue",
    "interest_expense",
    "income_tax_expense",
}
SEC_BALANCE_FIELDS = {
    "total_assets",
    "assetsCurrent",
    "total_liabilities",
    "liabilitiesCurrent",
    "total_equity",
    "cash",
    "accountsReceivableNetCurrent",
    "inventoryNet",
    "long_term_debt",
    "accountsPayableCurrent",
}
SEC_CASH_FIELDS = {
    "cfo",
    "cfi",
    "cff",
    "capex",
    "depreciationAndAmortization",
    "paymentsForRepurchaseOfCommonStock",
}


YF_CANONICAL_ALIASES = {
    "totalrevenue": "revenue",
    "revenue": "revenue",
    "grossprofit": "gross_profit",
    "costofrevenue": "cost_of_revenue",
    "operatingincome": "operating_income",
    "operatingincomeloss": "operating_income",
    "netincome": "net_income",
    "netincomeloss": "net_income",
    "totalassets": "total_assets",
    "currentassets": "current_assets",
    "totalcurrentassets": "current_assets",
    "totalliabilitiesnetminorityinterest": "total_liabilities",
    "totalliab": "total_liabilities",
    "currentliabilities": "current_liabilities",
    "totalcurrentliabilities": "current_liabilities",
    "stockholdersequity": "total_equity",
    "totalstockholderequity": "total_equity",
    "commonstockequity": "total_equity",
    "cashandcashequivalents": "cash",
    "cashcashequivalentsandshortterminvestments": "cash",
    "longtermdebt": "long_term_debt",
    "totaldebt": "long_term_debt",
    "operatingcashflow": "cfo",
    "totalcashfromoperatingactivities": "cfo",
    "capitalexpenditure": "capex",
    "capitalexpenditures": "capex",
    "freecashflow": "free_cash_flow",
}


SEC_CANONICAL_ALIASES = {
    "grossProfit": "gross_profit",
    "assetsCurrent": "current_assets",
    "liabilitiesCurrent": "current_liabilities",
    "accountsReceivableNetCurrent": "accounts_receivable",
    "inventoryNet": "inventory",
    "accountsPayableCurrent": "accounts_payable",
    "depreciationAndAmortization": "depreciation_amortization",
    "paymentsForRepurchaseOfCommonStock": "buybacks",
}


def _rows_from_canonical(data: dict[str, Any], section: str) -> list[dict[str, Any]]:
    if section == "income":
        wanted = SEC_INCOME_FIELDS
    elif section == "balance":
        wanted = SEC_BALANCE_FIELDS
    else:
        wanted = SEC_CASH_FIELDS
    rows = [
        _row_from_series(key, value)
        for key, value in data.items()
        if key in wanted and _row_from_series(key, value)
    ]
    return rows


def _row_from_series(label: str, value: Any) -> dict[str, Any]:
    if hasattr(value, "dropna"):
        series = value.dropna()
        if hasattr(series, "sort_index"):
            series = series.sort_index()
        if len(series) == 0:
            return {}
        row: dict[str, Any] = {"line_item": label, "latest": _to_number(series.iloc[-1])}
        for idx, item in series.tail(5).items():
            row[_date_label(idx)] = _to_number(item)
        return row
    numeric = _to_number(value)
    return {"line_item": label, "latest": numeric} if numeric is not None else {}


def _rows_from_frame(frame: Any) -> list[dict[str, Any]]:
    if frame is None or not hasattr(frame, "empty") or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for metric, values in frame.iterrows():
        row = _row_from_series(str(metric), values)
        if row:
            rows.append(row)
    return rows


def _latest_canonical_values(data: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in data.items():
        canonical = SEC_CANONICAL_ALIASES.get(key, key)
        numeric = _latest_value(value)
        if numeric is not None:
            out[canonical] = numeric
    return out


def _latest_yfinance_values(data: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for frame_key in ("income", "balance", "cashflow"):
        frame = data.get(frame_key)
        if frame is None or not hasattr(frame, "empty") or frame.empty:
            continue
        for metric, values in frame.iterrows():
            canonical = YF_CANONICAL_ALIASES.get(_normalise_label(str(metric)))
            if not canonical:
                continue
            numeric = _latest_value(values)
            if numeric is not None:
                out[canonical] = numeric
    return out


def _latest_value(value: Any) -> float | None:
    if hasattr(value, "dropna"):
        series = value.dropna()
        if hasattr(series, "sort_index"):
            series = series.sort_index()
        if len(series) == 0:
            return None
        return _to_number(series.iloc[-1])
    return _to_number(value)


def _compute_ratios(values: dict[str, float]) -> dict[str, float]:
    revenue = values.get("revenue")
    gross_profit = values.get("gross_profit")
    operating_income = values.get("operating_income")
    net_income = values.get("net_income")
    total_assets = values.get("total_assets")
    total_equity = values.get("total_equity")
    current_assets = values.get("current_assets")
    current_liabilities = values.get("current_liabilities")
    cfo = values.get("cfo")
    capex = values.get("capex")
    # debt_to_equity is long-term debt only. No fallback to total liabilities:
    # a missing long-term debt leaves the ratio absent instead of silently
    # reporting a different ratio under the same name.
    debt = values.get("long_term_debt")

    ratios = {
        "gross_margin": _safe_div(gross_profit, revenue),
        "operating_margin": _safe_div(operating_income, revenue),
        "net_margin": _safe_div(net_income, revenue),
        "return_on_assets": _safe_div(net_income, total_assets),
        "return_on_equity": _safe_div(net_income, total_equity),
        "debt_to_equity": _safe_div(debt, total_equity),
        "current_ratio": _safe_div(current_assets, current_liabilities),
    }
    if cfo is not None and capex is not None:
        free_cash_flow = cfo + capex if capex < 0 else cfo - abs(capex)
        ratios["free_cash_flow_margin"] = _safe_div(free_cash_flow, revenue)
    return {
        key: round(value, 4)
        for key, value in ratios.items()
        if value is not None
    }


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _to_number(value: Any) -> float | None:
    try:
        if value in (None, "", "N/A"):
            return None
        number = float(value)
        if number != number:
            return None
        return number
    except Exception:
        return None


def _normalise_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _date_label(value: Any) -> str:
    if hasattr(value, "date"):
        try:
            return value.date().isoformat()
        except Exception:
            pass
    return str(value)[:10]


def _latest_filing_date(data: Any, *, from_frames: bool = False) -> str | None:
    """Derive the most recent real period/filing date from statement data.

    SEC: ``data`` is ``{canonical_key: pd.Series}`` where each series is
    indexed by the XBRL period ``end`` date. yfinance (``from_frames``):
    ``data`` is ``{section: DataFrame}`` whose columns are period dates.

    Returns the latest period end as an ISO ``YYYY-MM-DD`` string, or
    ``None`` when no real date is available (never fabricated).
    """
    if not isinstance(data, dict):
        return None
    latest: Any = None
    for value in data.values():
        candidates: Any = []
        if from_frames:
            if value is None or not hasattr(value, "columns"):
                continue
            candidates = list(value.columns)
        else:
            index = getattr(value, "index", None)
            if index is None:
                continue
            candidates = list(index)
        for raw in candidates:
            # Parse tz-aware (utc=True) then drop tz so every stamp is naive
            # and mutually comparable — mixing tz-aware and tz-naive
            # Timestamps in ``stamp > latest`` otherwise raises TypeError.
            stamp = pd.to_datetime(raw, errors="coerce", utc=True)
            if stamp is None or pd.isna(stamp):
                continue
            stamp = stamp.tz_localize(None)
            if latest is None or stamp > latest:
                latest = stamp
    if latest is None:
        return None
    try:
        return latest.date().isoformat()
    except Exception:
        return str(latest)[:10]
