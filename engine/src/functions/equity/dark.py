"""DARK — Dark pool / off-exchange ATS volume aggregation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class DARKFunction(BaseFunction):
    code = "DARK"
    name = "Dark Pool Volume"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"
    description = "FINRA ATS (Alternative Trading System) weekly off-exchange volume by venue."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (instrument.symbol if instrument else
               params.get("symbol") or "AAPL").upper()
        if not self.deps.finra:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_fallback_dark(sym),
                                  sources=["dark_pool_model"])
        try:
            df = await self.deps.finra.ats_weekly(
                symbol=sym, limit=int(params.get("limit", 100)))
        except Exception as e:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_fallback_dark(sym),
                                  sources=["dark_pool_model"],
                                  metadata={"provider_errors": [f"finra: {e}"]})
        if df is None or len(df) == 0:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_fallback_dark(sym),
                                  sources=["dark_pool_model"],
                                  metadata={"provider_errors": ["no ats weekly data"]})
        # Aggregate by venue and by week
        df = df.fillna(0)
        venues: list[dict[str, Any]] = []
        weeks: list[dict[str, Any]] = []
        venue_col = next(
            (c for c in ("ATSCode", "atsCode", "venue", "mpid") if c in df.columns),
            None,
        )
        if venue_col:
            grouped = df.groupby(venue_col).agg(
                total_share_qty=("totalWeeklyShareQuantity", "sum"),
                total_trade_count=("totalWeeklyTradeCount", "sum"),
                weeks=("weekStartDate", "nunique"),
            ).reset_index()
            if venue_col != "ATSCode":
                grouped = grouped.rename(columns={venue_col: "ATSCode"})
            grouped = grouped.sort_values("total_share_qty", ascending=False)
            venues = grouped.to_dict(orient="records")
        if "weekStartDate" in df.columns:
            agg = {
                "total_share_qty": ("totalWeeklyShareQuantity", "sum"),
                "total_trade_count": ("totalWeeklyTradeCount", "sum"),
            }
            if venue_col:
                agg["n_venues"] = (venue_col, "nunique")
            wgrp = df.groupby("weekStartDate").agg(**agg).reset_index()
            if "n_venues" not in wgrp.columns:
                wgrp["n_venues"] = 0
            wgrp = wgrp.sort_values("weekStartDate", ascending=False)
            weeks = wgrp.to_dict(orient="records")
        # Top venue concentration
        total = float(df.get("totalWeeklyShareQuantity", pd.Series()).sum() or 0)
        top_venue_share = (venues[0]["total_share_qty"] / total) if (venues and total) else 0.0
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "symbol": sym,
                "n_rows": int(len(df)),
                "total_shares_off_exchange": total,
                "top_venue_share_pct": top_venue_share * 100,
                "by_venue": venues,
                "by_week": weeks,
            },
            sources=["finra"],
        )


def _fallback_dark(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "n_rows": 1,
        "total_shares_off_exchange": 0.0,
        "top_venue_share_pct": 0.0,
        "by_venue": [{"ATSCode": "UNAVAILABLE", "total_share_qty": 0, "total_trade_count": 0, "weeks": 0}],
        "by_week": [{"weekStartDate": None, "total_share_qty": 0, "total_trade_count": 0, "n_venues": 0}],
        "status": "provider_unavailable",
    }
