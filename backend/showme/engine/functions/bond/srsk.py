"""SRSK — Sovereign Risk (CDS-implied PD)."""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


@FunctionRegistry.register
class SRSKFunction(BaseFunction):
    code = "SRSK"
    name = "Sovereign Risk"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Approximation: PD ≈ CDS / (1 - R), R = 0.4 (Hull). CDS data not in free feed;
        # placeholder uses sovereign yield − UST10Y as a proxy spread.
        raw_countries = params.get("countries") or params.get("country") or "TR, US, DE, JP"
        if isinstance(raw_countries, str):
            countries = [item.strip().upper() for item in raw_countries.split(",") if item.strip()]
        else:
            countries = [str(item).strip().upper() for item in raw_countries if str(item).strip()]
        countries = countries[:12] or ["TR"]
        fallback_spread = float(params.get("proxy_spread_pct", 3.25))
        recovery = float(params.get("recovery", 0.4))
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        ust_y: float | None = None
        if self.deps.fred:
            try:
                ust = await self.deps.fred.series("DGS10")
                ust_y = float(ust["value"].iloc[-1])
            except Exception as e:
                warnings.append(f"fred: {e}")
        from showme.engine.functions.bond.wb import _SOVEREIGN_FRED_IDS  # type: ignore
        for country in countries:
            proxy_spread = fallback_spread
            source_mode = "sovereign_risk_model"
            if self.deps.fred and ust_y is not None:
                fid = _SOVEREIGN_FRED_IDS.get(country)
                if fid:
                    try:
                        target = await self.deps.fred.series(fid)
                        target_y = float(target["value"].iloc[-1])
                        proxy_spread = target_y - ust_y
                        source_mode = "fred"
                    except Exception as e:
                        warnings.append(f"{country}: {e}")
            pd_1y = proxy_spread / 100 / max(0.01, (1 - recovery))
            rows.append({
                "country": country,
                "proxy_spread_pct": proxy_spread,
                "pd_1y_proxy": pd_1y,
                "pd_1y_pct": pd_1y * 100,
                "recovery": recovery,
                "source_mode": source_mode,
            })
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "rows": rows,
                "summary": {"countries": len(rows), "recovery": recovery, "formula": "PD ~= spread / (1 - recovery)"},
                "methodology": "SRSK estimates a proxy one-year sovereign default probability using PD ~= spread / (1 - recovery). When CDS is unavailable, spread is proxied from sovereign 10Y yield minus UST 10Y or from the visible proxy spread input.",
                "field_dictionary": {
                    "proxy_spread_pct": "Yield/CDS proxy spread in percentage points.",
                    "pd_1y_proxy": "One-year default-probability proxy as a decimal.",
                    "pd_1y_pct": "One-year default-probability proxy in percent.",
                    "recovery": "Assumed recovery rate in the reduced-form approximation.",
                },
            },
            sources=["fred" if any(row["source_mode"] == "fred" for row in rows) else "sovereign_risk_model"],
            warnings=warnings,
        )
