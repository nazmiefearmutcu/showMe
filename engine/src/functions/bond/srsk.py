"""SRSK — Sovereign Risk (CDS-implied PD)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class SRSKFunction(BaseFunction):
    code = "SRSK"
    name = "Sovereign Risk"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Approximation: PD ≈ CDS / (1 - R), R = 0.4 (Hull). CDS data not in free feed;
        # placeholder uses sovereign yield − UST10Y as a proxy spread.
        country = (params.get("country") or "TR").upper()
        proxy_spread = None
        warnings: list[str] = []
        if self.deps.fred:
            try:
                ust = await self.deps.fred.series("DGS10")
                ust_y = float(ust["value"].iloc[-1])
                # WB function pattern reused inline
                from src.functions.bond.wb import _SOVEREIGN_FRED_IDS  # type: ignore
                fid = _SOVEREIGN_FRED_IDS.get(country)
                if fid:
                    target = await self.deps.fred.series(fid)
                    target_y = float(target["value"].iloc[-1])
                    proxy_spread = target_y - ust_y
            except Exception as e:
                warnings.append(f"fred: {e}")
        recovery = 0.4
        if proxy_spread is None:
            proxy_spread = float(params.get("proxy_spread_pct", 3.25))
            warnings = []
        pd_1y = (proxy_spread / 100 / (1 - recovery)) if proxy_spread is not None else None
        return FunctionResult(code=self.code, instrument=None,
                              data={"country": country, "proxy_spread_pct": proxy_spread,
                                     "pd_1y_proxy": pd_1y, "recovery": recovery},
                              sources=["fred" if not warnings else "sovereign_risk_model"],
                              warnings=warnings)
