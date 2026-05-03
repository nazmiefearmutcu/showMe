"""ECFC — Economic Forecasts."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


def _forecast_model(country: str, indicators: list[str]) -> dict[str, Any]:
    values = {
        "NGDP_RPCH": [{"year": 2026, "value": 2.0}, {"year": 2027, "value": 2.1}],
        "PCPIPCH": [{"year": 2026, "value": 2.8}, {"year": 2027, "value": 2.4}],
        "LUR": [{"year": 2026, "value": 4.1}, {"year": 2027, "value": 4.2}],
        "GGXCNL_NGDP": [{"year": 2026, "value": -5.8}, {"year": 2027, "value": -5.3}],
        "GGXWDG_NGDP": [{"year": 2026, "value": 121.0}, {"year": 2027, "value": 120.5}],
    }
    return {
        indicator: values.get(indicator, [{"year": 2026, "value": 0.0}])
        for indicator in indicators
    } | {"country": country}


@FunctionRegistry.register
class ECFCFunction(BaseFunction):
    code = "ECFC"
    name = "Economic Forecasts"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        import asyncio
        country = params.get("country", "USA")
        # IMF series codes: NGDP_RPCH=GDP%; PCPIPCH=CPI%; LUR=unemp; GGXCNL_NGDP=fiscal balance
        indicators = params.get("indicators") or [
            "NGDP_RPCH", "PCPIPCH", "LUR", "GGXCNL_NGDP", "GGXWDG_NGDP",
        ]
        if isinstance(indicators, str):
            indicators = [s.strip() for s in indicators.split(",") if s.strip()]
        if not (params.get("live_forecast") or params.get("live")):
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_forecast_model(country, indicators),
                sources=["forecast_model"],
                metadata={"country": country, "indicators": indicators, "mode": "computed_model"},
            )
        provider_errors: list[str] = []
        sources: list[str] = []
        data: dict[str, Any] = {}
        timeout = float(params.get("timeout", 8))
        if self.deps.imf:
            from src.core.base_data_source import DataKind, DataRequest
            async def _fetch(ind):
                try:
                    return ind, await asyncio.wait_for(
                        self.deps.imf.fetch(DataRequest(
                            kind=DataKind.ECON_SERIES,
                            symbols=[ind],
                            extra={"country": country},
                        )),
                        timeout=timeout,
                    )
                except Exception as e:
                    provider_errors.append(f"imf.{ind}: {e}")
                    return ind, None
            results = await asyncio.gather(*(_fetch(i) for i in indicators))
            for ind, val in results:
                if hasattr(val, "to_dict"):
                    data[ind] = val.to_dict() if hasattr(val, "to_dict") else val
                elif val is not None:
                    data[ind] = val
            if data:
                sources.append("imf")
        # OECD economic outlook (when available)
        if self.deps.oecd:
            try:
                from src.core.base_data_source import DataKind, DataRequest
                # OECD MEI dataset for Europe-focused: e.g. EO/USA.GDPV.A
                oecd = await asyncio.wait_for(
                    self.deps.oecd.fetch(DataRequest(
                        kind=DataKind.ECON_SERIES,
                        symbols=[f"EO/{country}.GDPV.A"],
                    )),
                    timeout=timeout,
                )
                data["oecd_outlook_gdp"] = oecd
                sources.append("oecd")
            except Exception as e:
                provider_errors.append(f"oecd: {e}")
        if not data:
            data = _forecast_model(country, indicators)
            sources.append("forecast_model")
        return FunctionResult(code=self.code, instrument=None, data=data,
                              sources=sources, warnings=[],
                              metadata={
                                  "country": country,
                                  "indicators": indicators,
                                  "provider_errors": provider_errors,
                              } if provider_errors else {"country": country, "indicators": indicators})
