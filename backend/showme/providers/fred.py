"""FRED (St Louis Fed) adapter — economic time series.

Requires an API key at ``FRED_API_KEY``. Without one, ``auth_state``
reports ``missing_key`` and ``mode()`` resolves to ``NOT_CONFIGURED`` so
the UI can render a "set your FRED key" CTA instead of trying upstream.
"""
from __future__ import annotations

import os
import time
from typing import Any, ClassVar, Literal

from .base import AdapterError, DataMode, ProviderAdapter
from ._http import get_client

__all__ = ["FredAdapter"]


_BASE = "https://api.stlouisfed.org/fred"
_SERIES_OBS = f"{_BASE}/series/observations"
_SERIES_META = f"{_BASE}/series"

_AuthState = Literal["ok", "missing_key", "invalid_key", "not_required"]


class FredAdapter(ProviderAdapter):
    """FRED REST API adapter."""

    name: ClassVar[str] = "fred"
    nominal_mode: ClassVar[DataMode] = DataMode.LIVE_OFFICIAL

    def capabilities(self) -> set[str]:
        return {"series_observations", "series_metadata", "release_dates"}

    def _api_key(self) -> str | None:
        # Resolved per-call so tests can monkeypatch the env between calls.
        key = os.environ.get("FRED_API_KEY")
        return key.strip() if key else None

    def auth_state(self) -> _AuthState:
        key = self._api_key()
        if not key:
            return "missing_key"
        # We never see the upstream's "invalid_key" verdict until a real
        # request roundtrips; we record that into _last_error and surface
        # it via mode() = PROVIDER_UNAVAILABLE.
        return "ok"

    async def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        key = self._api_key()
        if not key:
            exc = AdapterError("FRED_API_KEY is not configured")
            self._record_failure(exc)
            raise exc
        merged = {**params, "api_key": key, "file_type": "json"}
        client = await get_client()
        started = time.monotonic()
        try:
            r = await client.get(url, params=merged)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001 — record-and-reraise
            self._record_failure(exc)
            raise AdapterError(f"fred GET {url} failed: {exc}") from exc
        self._record_success(int((time.monotonic() - started) * 1000))
        return data

    async def get_series(
        self,
        series_id: str,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """Observations for ``series_id``; ``start``/``end`` are ``YYYY-MM-DD``."""
        if not series_id:
            raise AdapterError("series_id must be non-empty")
        params: dict[str, Any] = {"series_id": series_id}
        if start:
            params["observation_start"] = start
        if end:
            params["observation_end"] = end
        return await self._get_json(_SERIES_OBS, params)

    async def get_metadata(self, series_id: str) -> dict[str, Any]:
        """Metadata (title, units, frequency, …) for ``series_id``."""
        if not series_id:
            raise AdapterError("series_id must be non-empty")
        return await self._get_json(_SERIES_META, {"series_id": series_id})
