"""Open-Meteo adapter — keyless daily forecast (WEATHER).

Open-Meteo (https://api.open-meteo.com) is a keyless public weather API.
The WETR handler was originally wired to OpenWeatherMap only, which
requires ``OPENWEATHERMAP_API_KEY``; without the key WETR always fell
back to its labelled seasonal model. The config already declared the
``open_meteo`` adapter (``config/data_sources.yaml``) but no adapter
class existed — this module implements it and ``FunctionFactory`` binds
it to ``FunctionDeps.open_meteo`` so WETR defaults to real live rows.

``onecall(lat, lon, days=...)`` returns the OpenWeather One-Call-shaped
``{"daily": [...]}`` envelope so the existing WETR normaliser can keep
working unchanged:

    {"daily": [
        {"dt": <epoch s>, "temp": {"day": .., "min": .., "max": ..},
         "precipitation": <mm>},
        ...
    ]}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from showme.engine.core.base_data_source import (
    BaseDataSource,
    DataKind,
    DataRequest,
    DataSourceError,
)


def open_meteo_to_onecall(payload: Any) -> dict[str, Any]:
    """Translate an Open-Meteo forecast payload to the one-call shape.

    Raises ``DataSourceError`` when the payload has no usable daily rows —
    callers degrade to their labelled fallback instead of fabricating.
    """
    if not isinstance(payload, dict):
        raise DataSourceError("unexpected Open-Meteo payload")
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise DataSourceError("Open-Meteo payload has no daily block")
    times = daily.get("time")
    if not isinstance(times, list) or not times:
        raise DataSourceError("Open-Meteo payload has no daily timestamps")
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    precip = daily.get("precipitation_sum") or []

    rows: list[dict[str, Any]] = []
    for index, day in enumerate(times):
        high = highs[index] if index < len(highs) else None
        low = lows[index] if index < len(lows) else None
        values = [float(v) for v in (high, low) if isinstance(v, (int, float))]
        if not values:
            continue
        mean = sum(values) / len(values)
        rain = precip[index] if index < len(precip) else None
        try:
            dt = datetime.strptime(str(day)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        rows.append({
            "dt": dt.timestamp(),
            "temp": {
                "day": round(mean, 2),
                "min": float(low) if isinstance(low, (int, float)) else round(mean, 2),
                "max": float(high) if isinstance(high, (int, float)) else round(mean, 2),
            },
            "precipitation": float(rain) if isinstance(rain, (int, float)) else 0.0,
        })
    if not rows:
        raise DataSourceError("Open-Meteo payload contained no usable daily rows")
    return {"daily": rows}


class OpenMeteoAdapter(BaseDataSource):
    """Keyless Open-Meteo daily forecast adapter."""

    name = "open_meteo"
    supported_kinds = (DataKind.WEATHER,)
    rate_limit_rps = 1.0
    requires_api_key = False
    api_key_env = ""

    #: Open-Meteo free tier caps ``forecast_days`` at 16.
    _MAX_FORECAST_DAYS = 16

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get("base_url", "https://api.open-meteo.com/v1")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def daily_forecast(self, lat: float, lon: float, days: int = 10) -> dict[str, Any]:
        """Fetch a daily forecast, normalised to the one-call envelope."""
        horizon = max(1, min(int(days or 10), self._MAX_FORECAST_DAYS))
        client = await self._client_()
        url = f"{self.base_url.rstrip('/')}/forecast"
        r = await client.get(url, params={
            "latitude": f"{float(lat):.4f}",
            "longitude": f"{float(lon):.4f}",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "forecast_days": horizon,
            "timezone": "UTC",
        })
        r.raise_for_status()
        return open_meteo_to_onecall(r.json())

    async def onecall(self, lat: float, lon: float, days: int = 10) -> dict[str, Any]:
        """One-Call-compatible alias used by the WETR handler."""
        return await self.daily_forecast(lat, lon, days=days)

    async def fetch(self, request: DataRequest) -> Any:
        lat = request.extra.get("lat")
        lon = request.extra.get("lon")
        if lat is None or lon is None:
            raise DataSourceError("Open-Meteo requires lat/lon")
        days = request.extra.get("days", 10)
        return await self.daily_forecast(float(lat), float(lon), days=int(days or 10))


__all__ = ["OpenMeteoAdapter", "open_meteo_to_onecall"]
