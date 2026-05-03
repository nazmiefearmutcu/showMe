"""CRPR, DDIS, DEBT, ALLQ, GC3D iskeletleri (tek dosyada özet)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class CRPRFunction(BaseFunction):
    code = "CRPR"
    name = "Credit Rating Profile"
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        rating = params.get("rating") or {
            "sp": "AA+",
            "moodys": "Aa1",
            "fitch": "AA+",
            "outlook": "stable",
            "watch": "none",
        }
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "issuer": params.get("issuer") or getattr(instrument, "symbol", "US Treasury"),
                "ratings": rating,
                "implied_bucket": params.get("bucket", "high_grade"),
                "scale": ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"],
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
        rows = params.get("maturities") or [
            {"bucket": "0-1Y", "amount": 3.2, "currency": "USD", "pct": 12.0},
            {"bucket": "1-3Y", "amount": 8.6, "currency": "USD", "pct": 32.2},
            {"bucket": "3-5Y", "amount": 6.4, "currency": "USD", "pct": 24.0},
            {"bucket": "5Y+", "amount": 8.5, "currency": "USD", "pct": 31.8},
        ]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={"maturity_buckets": rows, "total_debt": sum(float(r["amount"]) for r in rows)},
            sources=["user_input_or_debt_schedule_model"],
        )


@FunctionRegistry.register
class DEBTFunction(BaseFunction):
    code = "DEBT"
    name = "Sovereign Debt Exposure"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        rows = params.get("exposures") or [
            {"country": "US", "debt_to_gdp": 122.0, "local_currency_share": 99.0},
            {"country": "JP", "debt_to_gdp": 255.0, "local_currency_share": 92.0},
            {"country": "DE", "debt_to_gdp": 63.0, "local_currency_share": 96.0},
            {"country": "TR", "debt_to_gdp": 29.0, "local_currency_share": 56.0},
        ]
        return FunctionResult(code=self.code, instrument=None, data={"rows": rows},
                              sources=["public_macro_baseline"])


@FunctionRegistry.register
class ALLQFunction(BaseFunction):
    code = "ALLQ"
    name = "Dealer Quotes (TRACE proxy)"
    asset_classes = (AssetClass.BOND,)
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        mid = float(params.get("mid", 99.75))
        spread = float(params.get("spread", 0.18))
        quotes = [
            {"dealer": "Composite A", "bid": mid - spread / 2, "ask": mid + spread / 2},
            {"dealer": "Composite B", "bid": mid - spread * 0.7, "ask": mid + spread * 0.8},
            {"dealer": "TRACE proxy", "bid": mid - spread, "ask": mid + spread},
        ]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={"quotes": quotes, "mid": mid, "best_bid": max(q["bid"] for q in quotes),
                  "best_ask": min(q["ask"] for q in quotes)},
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
