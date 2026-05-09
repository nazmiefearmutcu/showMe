"""FA — Financial Analysis (income / balance / cash flow).

DATA PIPELINE:
  Source: SEC EDGAR XBRL (primary, US-only canonical), yfinance (fallback, global)
  Cache:  DuckDB ``fundamentals`` (Faz 2 sonu) + 24h refdata cache
  Latency: <2s
"""

from __future__ import annotations

import asyncio
from datetime import datetime
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
        warnings: list[str] = []
        sources_used: list[str] = []

        sec_data = None
        try:
            if self.deps.sec_edgar:
                sec_data = await asyncio.wait_for(
                    self.deps.sec_edgar.standard_fundamentals(instrument.symbol),
                    timeout=float(params.get("sec_timeout", 8)),
                )
                sources_used.append("sec_edgar")
        except Exception as e:
            warnings.append(f"sec_edgar: {e}")

        yfin_data = None
        if not sec_data:
            try:
                if self.deps.yfinance:
                    yfin_data = await asyncio.wait_for(
                        self.deps.yfinance.fetch(DataRequest(
                            kind=DataKind.FUNDAMENTALS, instrument=instrument,
                            extra={"period": period},
                        )),
                        timeout=float(params.get("yfinance_timeout", 8)),
                    )
                    sources_used.append("yfinance")
            except Exception as e:
                warnings.append(f"yfinance: {e}")

        if sec_data is not None and isinstance(sec_data, dict):
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
        def _has_statement_payload(payload: Any) -> bool:
            if not isinstance(payload, dict):
                return bool(payload)
            for value in payload.values():
                if hasattr(value, "empty"):
                    if not value.empty:
                        return True
                elif value:
                    return True
            return False

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


def _financial_snapshot_model(symbol: str, period: Any) -> dict[str, Any]:
    seed = (sum(ord(ch) for ch in symbol.upper()) % 17) / 100
    revenue = 100_000_000_000 * (1 + seed)
    gross_margin = 0.36 + seed / 4
    operating_margin = 0.22 + seed / 5
    free_cash_flow_margin = 0.18 + seed / 6
    return {
        "symbol": symbol,
        "status": "computed_statement_snapshot",
        "period": period,
        "income": [
            {"line_item": "revenue", "latest": round(revenue, 2)},
            {"line_item": "gross_profit", "latest": round(revenue * gross_margin, 2)},
            {"line_item": "operating_income", "latest": round(revenue * operating_margin, 2)},
            {"line_item": "net_income", "latest": round(revenue * (operating_margin * 0.78), 2)},
        ],
        "cashflow": [
            {"line_item": "free_cash_flow", "latest": round(revenue * free_cash_flow_margin, 2)},
            {"line_item": "capex", "latest": round(-(revenue * 0.045), 2)},
        ],
        "balance": [
            {"line_item": "cash_and_equivalents", "latest": round(revenue * 0.18, 2)},
            {"line_item": "total_debt", "latest": round(revenue * 0.24, 2)},
        ],
        "quality": {
            "gross_margin": round(gross_margin, 4),
            "operating_margin": round(operating_margin, 4),
            "free_cash_flow_margin": round(free_cash_flow_margin, 4),
        },
    }


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
    else:
        yfin_data = yfin_data or {}
        canonical = _latest_yfinance_values(yfin_data)
        income_rows = _rows_from_frame(yfin_data.get("income"))
        balance_rows = _rows_from_frame(yfin_data.get("balance"))
        cash_rows = _rows_from_frame(yfin_data.get("cashflow"))

    ratios = _compute_ratios(canonical)
    status = "ok" if ratios else "calc_error"
    payload: dict[str, Any] = {
        "symbol": symbol,
        "status": status,
        "period": period,
        "source": source,
        "asOf": datetime.utcnow().isoformat(),
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
        "field_dictionary": {
            "gross_margin": "gross_profit / revenue.",
            "net_margin": "net_income / revenue.",
            "roe": "net_income / total_equity.",
            "current_ratio": "current_assets / current_liabilities.",
            "free_cash_flow": "cash from operations minus capital expenditure when available.",
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
    total_liabilities = values.get("total_liabilities")
    current_assets = values.get("current_assets")
    current_liabilities = values.get("current_liabilities")
    cfo = values.get("cfo")
    capex = values.get("capex")
    debt = values.get("long_term_debt") or total_liabilities

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
