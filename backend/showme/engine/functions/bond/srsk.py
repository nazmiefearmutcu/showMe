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
        ust_error: str | None = None
        if self.deps.fred:
            try:
                ust = await self.deps.fred.series("DGS10")
                ust_y = float(ust["value"].iloc[-1])
            except Exception as e:
                ust_error = str(e)
                warnings.append(f"fred: {e}")
        # S12 BugHunt: when UST10Y is unavailable every country falls back to
        # the same flat 3.25 % proxy spread and the resulting table reports
        # identical PD for every sovereign — a false signal. Surface the
        # provider gap explicitly instead.
        if self.deps.fred and ust_y is None:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "FRED DGS10 (UST 10Y) unavailable; SRSK cannot compute sovereign spreads.",
                    "rows": [],
                    "summary": {"countries": 0, "recovery": recovery, "formula": "PD ~= spread / (1 - recovery)"},
                },
                sources=["sovereign_risk_model"],
                warnings=warnings,
                metadata={"live": False, "fallback": False, "provider_errors": [ust_error or "DGS10 unavailable"]},
            )
        from showme.engine.functions.bond.wb import _SOVEREIGN_FRED_IDS  # type: ignore
        any_country_with_mapping = False
        for country in countries:
            proxy_spread = fallback_spread
            source_mode = "sovereign_risk_model"
            row_note: str | None = None
            fid = _SOVEREIGN_FRED_IDS.get(country)
            if self.deps.fred and ust_y is not None and fid:
                any_country_with_mapping = True
                if country == "US":
                    # Self-spread is by definition zero; the resulting
                    # PD ≈ 0 is meaningless and was previously printed as a
                    # real risk reading. Explicitly mark it.
                    proxy_spread = 0.0
                    source_mode = "fred"
                    row_note = "US sovereign self-spread is zero; PD shown for completeness only and is not a credit-risk reading"
                else:
                    try:
                        target = await self.deps.fred.series(fid)
                        target_y = float(target["value"].iloc[-1])
                        proxy_spread = target_y - ust_y
                        source_mode = "fred"
                    except Exception as e:
                        warnings.append(f"{country}: {e}")
                        row_note = f"FRED {fid} unavailable; using fallback spread"
            elif self.deps.fred and ust_y is not None and not fid:
                row_note = f"no FRED long-rate mapping for {country}; row uses fallback proxy_spread_pct={fallback_spread}"
                warnings.append(row_note)
            pd_1y = proxy_spread / 100 / max(0.01, (1 - recovery))
            rows.append({
                "country": country,
                "proxy_spread_pct": proxy_spread,
                "pd_1y_proxy": pd_1y,
                "pd_1y_pct": pd_1y * 100,
                "recovery": recovery,
                "source_mode": source_mode,
                "note": row_note,
            })
        sources_used = ["fred"] if any_country_with_mapping and any(r["source_mode"] == "fred" for r in rows) else ["sovereign_risk_model"]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok" if any_country_with_mapping else "fallback",
                "rows": rows,
                "summary": {
                    "countries": len(rows),
                    "recovery": recovery,
                    "formula": "PD ~= spread / (1 - recovery)",
                    "mapped_countries": sum(1 for r in rows if r["source_mode"] == "fred" and r["country"] != "US"),
                    "fallback_countries": sum(1 for r in rows if r["source_mode"] != "fred"),
                },
                "methodology": "SRSK estimates a proxy one-year sovereign default probability using PD ~= spread / (1 - recovery). When CDS is unavailable, spread is proxied from sovereign 10Y yield minus UST 10Y or from the visible proxy spread input.",
                "field_dictionary": {
                    "proxy_spread_pct": "Yield/CDS proxy spread in percentage points.",
                    "pd_1y_proxy": "One-year default-probability proxy as a decimal.",
                    "pd_1y_pct": "One-year default-probability proxy in percent.",
                    "recovery": "Assumed recovery rate in the reduced-form approximation.",
                    "note": "Per-row caveat: missing FRED mapping, US self-spread, or fallback applied.",
                },
            },
            sources=sources_used,
            warnings=warnings,
            metadata={"live": any_country_with_mapping, "ust_10y_pct": ust_y},
        )
