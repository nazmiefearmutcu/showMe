"""DPF — Dark Pool / ATS Volume.

Plan §6.4: FINRA OTC Transparency üzerinden ATS volume ve dark pool %.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class DPFFunction(BaseFunction):
    code = "DPF"
    name = "Dark Pool / ATS Volume"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"
    description = "FINRA-reported off-exchange (ATS) volume + dark-pool % of total."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("DPF requires instrument")
        weeks = int(params.get("weeks", 12))
        warnings: list[str] = []
        sources: list[str] = []
        df = pd.DataFrame()
        if getattr(self.deps, "finra", None):
            try:
                df = await self.deps.finra.ats_weekly(instrument.symbol, limit=weeks * 4)
                sources.append("finra")
            except Exception as e:
                warnings.append(f"finra: {e}")
        # Aggregate by week & ATS code
        agg = pd.DataFrame()
        if not df.empty and "weekStartDate" in df.columns:
            qty_col = next((c for c in df.columns if "ShareQuantity" in c), None)
            tc_col = next((c for c in df.columns if "TradeCount" in c), None)
            if qty_col:
                df = df.copy()
                df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce")
                if tc_col:
                    df[tc_col] = pd.to_numeric(df[tc_col], errors="coerce")
                grp = df.groupby("weekStartDate")
                agg = grp[qty_col].sum().reset_index().rename(
                    columns={qty_col: "ats_share_volume"}
                )
                if tc_col:
                    agg["ats_trade_count"] = grp[tc_col].sum().values
                agg = agg.sort_values("weekStartDate", ascending=False).head(weeks)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "weekly": (
                    agg.to_dict(orient="records")
                    if hasattr(agg, "to_dict") and not agg.empty
                    else [{"weekStartDate": None, "ats_share_volume": 0, "status": "provider_unavailable"}]
                ),
                "raw_rows": int(len(df)),
            },
            sources=sources or ["dark_pool_model"],
            metadata={
                "note": "Anonymous FINRA endpoint may rate-limit; OAuth recommended.",
                "provider_errors": warnings,
            },
        )
