"""OpenFIGI adapter — identifier mapping (ticker ↔ FIGI ↔ ISIN, etc).

The OpenFIGI mapping endpoint works anonymously at a low quota; a key
(``OPENFIGI_API_KEY``) just bumps the throughput. Either way the nominal
DataMode is ``LIVE_OFFICIAL`` — the *data* is official whether you queue
behind the anon limit or your own bucket.
"""
from __future__ import annotations

import os
import time
from typing import Any, ClassVar

from .base import AdapterError, DataMode, ProviderAdapter
from ._http import get_client

__all__ = ["OpenFigiAdapter"]


_MAPPING_URL = "https://api.openfigi.com/v3/mapping"


class OpenFigiAdapter(ProviderAdapter):
    """Adapter for the OpenFIGI /v3/mapping endpoint."""

    name: ClassVar[str] = "openfigi"
    nominal_mode: ClassVar[DataMode] = DataMode.LIVE_OFFICIAL

    def capabilities(self) -> set[str]:
        return {"identifier_mapping", "ticker_search"}

    def _api_key(self) -> str | None:
        # Resolved per-call so the host can rotate the key without a restart.
        key = os.environ.get("OPENFIGI_API_KEY")
        return key.strip() if key else None

    # auth_state stays at the default "not_required" — OpenFIGI explicitly
    # supports anonymous usage. The key is an opt-in throughput upgrade.

    async def map_identifiers(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """POST a batch of mapping jobs.

        Each ``job`` is a dict like ``{"idType": "TICKER", "idValue": "AAPL"}``.
        Returns the parsed list response (one entry per job, in order).
        """
        if not isinstance(jobs, list) or not jobs:
            raise AdapterError("jobs must be a non-empty list[dict]")
        if any(not isinstance(j, dict) for j in jobs):
            raise AdapterError("every job must be a dict")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        key = self._api_key()
        if key:
            headers["X-OPENFIGI-APIKEY"] = key

        client = await get_client()
        started = time.monotonic()
        try:
            r = await client.post(_MAPPING_URL, json=jobs, headers=headers)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001 — record-and-reraise
            self._record_failure(exc)
            raise AdapterError(f"openfigi mapping failed: {exc}") from exc
        self._record_success(int((time.monotonic() - started) * 1000))
        if not isinstance(data, list):
            self._record_failure(AdapterError("openfigi: response was not a list"))
            raise AdapterError("openfigi: response was not a list")
        return data
