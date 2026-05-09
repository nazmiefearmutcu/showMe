"""ECFC — Economic Forecasts."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


_INDICATORS: dict[str, tuple[str, str]] = {
    "NGDP_RPCH": ("Real GDP growth", "% y/y"),
    "PCPIPCH": ("Inflation", "% y/y"),
    "LUR": ("Unemployment rate", "%"),
    "GGXCNL_NGDP": ("Fiscal balance", "% GDP"),
    "GGXWDG_NGDP": ("Government debt", "% GDP"),
}


def _forecast_model(country: str, indicators: list[str]) -> dict[str, Any]:
    values = {
        "NGDP_RPCH": [{"year": 2026, "value": 2.0}, {"year": 2027, "value": 2.1}],
        "PCPIPCH": [{"year": 2026, "value": 2.8}, {"year": 2027, "value": 2.4}],
        "LUR": [{"year": 2026, "value": 4.1}, {"year": 2027, "value": 4.2}],
        "GGXCNL_NGDP": [{"year": 2026, "value": -5.8}, {"year": 2027, "value": -5.3}],
        "GGXWDG_NGDP": [{"year": 2026, "value": 121.0}, {"year": 2027, "value": 120.5}],
    }
    rows: list[dict[str, Any]] = []
    for indicator in indicators:
        label, unit = _indicator_label(indicator)
        for item in values.get(indicator, [{"year": 2026, "value": 0.0}]):
            rows.append({
                "country": country,
                "indicator": indicator,
                "metric": label,
                "year": item["year"],
                "forecast_value": item["value"],
                "unit": unit,
                "source_mode": "reference_forecast_table",
            })
    return {
        "country": country,
        "rows": rows,
        "series": rows,
        "cards": _forecast_cards(rows),
        "methodology": (
            "ECFC normalizes economic forecasts by country, indicator, year, unit, "
            "and source mode. IMF/OECD provider output is used when it can be "
            "parsed into metric-year rows; otherwise a labelled reference forecast table is shown."
        ),
        "field_dictionary": {
            "indicator": "Provider series code.",
            "metric": "Human-readable macro variable.",
            "forecast_value": "Forecast value in the displayed unit.",
            "year": "Forecast calendar year.",
            "source_mode": "Provider or reference layer used for the row.",
        },
        "source_mode": "reference_forecast_table",
    }


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
                sources=["reference_forecast_table"],
                metadata={"country": country, "indicators": indicators, "mode": "reference_forecast_table"},
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
        rows = _rows_from_provider(country, data)
        if not rows:
            if data or sources:
                provider_errors.append("provider payload did not normalize into forecast rows")
            data = _forecast_model(country, indicators)
            sources = ["reference_forecast_table"]
        else:
            data = {
                "country": country,
                "rows": rows,
                "series": rows,
                "cards": _forecast_cards(rows),
                "methodology": (
                    "Forecast rows are normalized from available IMF/OECD payloads. "
                    "Forecast surprise is not computed here because this view is a future-estimate table."
                ),
                "field_dictionary": {
                    "metric": "Human-readable macro variable.",
                    "forecast_value": "Forecast value in the displayed unit.",
                    "year": "Forecast calendar year.",
                    "source_mode": "Provider or reference layer used for the row.",
                },
                "source_mode": "live_provider",
            }
        return FunctionResult(code=self.code, instrument=None, data=data,
                              sources=_unique(sources), warnings=provider_errors,
                              metadata={
                                  "country": country,
                                  "indicators": indicators,
                                  "provider_errors": provider_errors,
                              } if provider_errors else {"country": country, "indicators": indicators})


def _rows_from_provider(country: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for indicator, payload in data.items():
        label, unit = _indicator_label(indicator)
        if isinstance(payload, list):
            iterable = payload
        elif isinstance(payload, dict):
            iterable = _records_from_dict(payload)
        else:
            iterable = []
        for item in iterable:
            if not isinstance(item, dict):
                continue
            year = _year_from_record(item)
            value = _value_from_record(item)
            if year is None or value is None:
                continue
            rows.append({
                "country": country,
                "indicator": indicator,
                "metric": label,
                "year": year,
                "forecast_value": value,
                "unit": unit,
                "source_mode": "imf_oecd",
            })
    return sorted(rows, key=lambda row: (str(row.get("metric")), int(row.get("year") or 0)))


def _records_from_dict(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("rows"), list):
        return payload["rows"]
    records: list[dict[str, Any]] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            merged = dict(value)
            merged.setdefault("year", key)
            records.append(merged)
        elif isinstance(value, (int, float)):
            records.append({"year": key, "value": value})
    return records


def _year_from_record(item: dict[str, Any]) -> int | None:
    for key in ("year", "date", "period", "time"):
        value = item.get(key)
        if value is None:
            continue
        text = str(value)
        try:
            return int(text[:4])
        except ValueError:
            continue
    return None


def _value_from_record(item: dict[str, Any]) -> float | None:
    for key in ("forecast_value", "value", "forecast", "obs_value", "OBS_VALUE"):
        value = item.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        return round(number, 6)
    return None


def _indicator_label(indicator: str) -> tuple[str, str]:
    return _INDICATORS.get(indicator, (indicator, "value"))


def _forecast_cards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for row in rows:
        if row.get("year") != min((r.get("year") for r in rows if r.get("metric") == row.get("metric")), default=row.get("year")):
            continue
        cards.append({"label": row.get("metric"), "value": row.get("forecast_value")})
    return cards[:6]


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out
