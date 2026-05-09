"""CRPR, DDIS, DEBT, ALLQ, GC3D iskeletleri (tek dosyada özet)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


def _as_of() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _bond_symbol(instrument: Instrument | None, params: dict[str, Any], fallback: str = "US10Y") -> str:
    return str(params.get("symbol") or getattr(instrument, "symbol", None) or fallback).strip().upper()


@FunctionRegistry.register
class CRPRFunction(BaseFunction):
    code = "CRPR"
    name = "Credit Rating Profile"
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        issuer = str(params.get("issuer") or _bond_symbol(instrument, params, "US Treasury"))
        rating = params.get("rating") or {
            "sp": "AA+",
            "moodys": "Aa1",
            "fitch": "AA+",
            "outlook": "stable",
            "watch": "none",
        }
        rows = [
            {"agency": "S&P", "rating": rating.get("sp"), "outlook": rating.get("outlook"), "watch": rating.get("watch"), "rating_date": _as_of(), "rationale": "Public/default sovereign profile; replace with issuer-specific feed when configured."},
            {"agency": "Moody's", "rating": rating.get("moodys"), "outlook": rating.get("outlook"), "watch": rating.get("watch"), "rating_date": _as_of(), "rationale": "Public/default sovereign profile; replace with issuer-specific feed when configured."},
            {"agency": "Fitch", "rating": rating.get("fitch"), "outlook": rating.get("outlook"), "watch": rating.get("watch"), "rating_date": _as_of(), "rationale": "Public/default sovereign profile; replace with issuer-specific feed when configured."},
        ]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "rows": rows,
                "summary": {"issuer": issuer, "implied_bucket": params.get("bucket", "high_grade"), "agencies": len(rows)},
                "implied_bucket": params.get("bucket", "high_grade"),
                "scale": ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"],
                "methodology": "CRPR displays agency rating records for the selected issuer/security. The bundled fallback is a public/default profile, not a live paid ratings feed; the source and rationale are shown in each row.",
                "field_dictionary": {
                    "agency": "Rating agency.",
                    "rating": "Agency long-term credit rating.",
                    "outlook": "Stable/positive/negative agency outlook when available.",
                    "watch": "Watchlist state when available.",
                    "rating_date": "Date attached to the visible rating snapshot.",
                    "rationale": "Why this row is shown and whether it is fallback data.",
                },
            },
            sources=["manual_or_public_defaults"],
        )


@FunctionRegistry.register
class DDISFunction(BaseFunction):
    code = "DDIS"
    name = "Debt Distribution by Maturity"
    asset_classes = (AssetClass.EQUITY, AssetClass.BOND)
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        issuer = str(params.get("issuer") or _bond_symbol(instrument, params, "AAPL")).upper()
        rows = params.get("maturities") or [
            {"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": 3.2, "currency": "USD", "pct": 12.0},
            {"bucket": "1-3Y", "tenor_years": 2.0, "amount_usd_bn": 8.6, "currency": "USD", "pct": 32.2},
            {"bucket": "3-5Y", "tenor_years": 4.0, "amount_usd_bn": 6.4, "currency": "USD", "pct": 24.0},
            {"bucket": "5Y+", "tenor_years": 7.0, "amount_usd_bn": 8.5, "currency": "USD", "pct": 31.8},
        ]
        for row in rows:
            if "amount" in row and "amount_usd_bn" not in row:
                row["amount_usd_bn"] = row.pop("amount")
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "rows": rows,
                "summary": {
                    "issuer": issuer,
                    "total_debt_usd_bn": round(sum(float(r["amount_usd_bn"]) for r in rows), 4),
                    "currency": "USD",
                    "source_mode": "user_input_or_model",
                },
                "methodology": "DDIS buckets debt principal by remaining maturity. Amounts are shown in USD billions; when a filing/debt schedule is not connected the rows are an explicit model/input schedule rather than live issuer debt.",
                "field_dictionary": {
                    "bucket": "Remaining-maturity bucket.",
                    "tenor_years": "Representative tenor for chart ordering.",
                    "amount_usd_bn": "Principal amount in USD billions.",
                    "pct": "Share of total visible debt schedule.",
                },
            },
            sources=["user_input_or_debt_schedule_model"],
        )


@FunctionRegistry.register
class DEBTFunction(BaseFunction):
    code = "DEBT"
    name = "Sovereign Debt Exposure"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        raw_countries = params.get("countries")
        country_filter = {
            str(item).strip().upper()
            for item in (raw_countries if isinstance(raw_countries, (list, tuple, set)) else str(raw_countries or "").split(","))
            if str(item).strip()
        }
        rows = params.get("exposures") or [
            {"country": "US", "debt_to_gdp": 122.0, "local_currency_share": 99.0, "portfolio_weight_pct": 0.0},
            {"country": "JP", "debt_to_gdp": 255.0, "local_currency_share": 92.0, "portfolio_weight_pct": 0.0},
            {"country": "DE", "debt_to_gdp": 63.0, "local_currency_share": 96.0, "portfolio_weight_pct": 0.0},
            {"country": "TR", "debt_to_gdp": 29.0, "local_currency_share": 56.0, "portfolio_weight_pct": 0.0},
        ]
        if country_filter:
            rows = [row for row in rows if str(row.get("country", "")).upper() in country_filter]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "rows": rows,
                "summary": {"countries": len(rows), "measure": "sovereign macro baseline", "portfolio_linked": False},
                "methodology": "DEBT is a sovereign macro exposure table unless portfolio holdings are provided. portfolio_weight_pct is zero in the bundled baseline so it is not misrepresented as actual portfolio exposure.",
                "field_dictionary": {
                    "debt_to_gdp": "General government debt as percent of GDP.",
                    "local_currency_share": "Share of sovereign debt issued in local currency.",
                    "portfolio_weight_pct": "Portfolio country weight when holdings are provided; zero means macro-only baseline.",
                },
            },
            sources=["public_macro_baseline"],
        )


@FunctionRegistry.register
class ALLQFunction(BaseFunction):
    code = "ALLQ"
    name = "Dealer Quotes (TRACE proxy)"
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbol = _bond_symbol(instrument, params)
        mid = float(params.get("mid", 99.75))
        spread = float(params.get("spread", params.get("spread_points", 0.18)))
        size = float(params.get("size", 1_000_000))
        quotes = [
            {"bond": symbol, "dealer": "Composite A", "bid": mid - spread / 2, "ask": mid + spread / 2, "size": size, "quote_time": _as_of()},
            {"bond": symbol, "dealer": "Composite B", "bid": mid - spread * 0.7, "ask": mid + spread * 0.8, "size": size * 0.75, "quote_time": _as_of()},
            {"bond": symbol, "dealer": "TRACE proxy", "bid": mid - spread, "ask": mid + spread, "size": size * 0.5, "quote_time": _as_of()},
        ]
        for quote in quotes:
            quote["mid"] = round((float(quote["bid"]) + float(quote["ask"])) / 2, 6)
            quote["spread_points"] = round(float(quote["ask"]) - float(quote["bid"]), 6)
            quote["spread_bps_of_price"] = round((quote["spread_points"] / quote["mid"]) * 10_000, 3)
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "rows": quotes,
                "spread_curve": [{"dealer": q["dealer"], "spread_bps_of_price": q["spread_bps_of_price"]} for q in quotes],
                "summary": {"bond": symbol, "mid": mid, "best_bid": max(q["bid"] for q in quotes), "best_ask": min(q["ask"] for q in quotes), "source_mode": "trace_proxy_model"},
                "methodology": "ALLQ is a dealer-quote style view. Without an authenticated dealer/TRACE feed, rows are explicitly labelled composite/proxy quotes and include size, quote date, bid/ask, mid, and spread so they are not mistaken for executable dealer quotes.",
                "field_dictionary": {
                    "bid": "Indicative bid price.",
                    "ask": "Indicative ask price.",
                    "mid": "Average of bid and ask.",
                    "size": "Indicative notional size.",
                    "spread_bps_of_price": "Bid/ask spread divided by mid price, in basis points.",
                },
            },
            sources=["trace_proxy_model"],
        )


@FunctionRegistry.register
class GC3DFunction(BaseFunction):
    code = "GC3D"
    name = "Yield Curve 3D (curve × time)"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        return FunctionResult(code=self.code, instrument=None, data={},
                              warnings=["Plotly 3D surface UI Phase 4"])
