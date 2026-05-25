"""TreasuryDirect (Fiscal Service) adapter — auction calendar + results.

No auth required. The Fiscal Service "Datasets" API takes filters as a
single comma-separated string per parameter; we accept Python-native
dicts/lists/strings and serialise them into the expected wire format.
"""
from __future__ import annotations

import time
from typing import Any, ClassVar

from .base import AdapterError, DataMode, ProviderAdapter
from ._http import get_client

__all__ = ["TreasuryDirectAdapter"]


_AUCTIONS_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
    "/v2/accounting/od/auctions_query"
)


def _serialise_filters(filters: dict[str, Any] | None) -> str | None:
    """Turn ``{"security_type": "Bill"}`` into ``"security_type:eq:Bill"``."""
    if not filters:
        return None
    parts: list[str] = []
    for k, v in filters.items():
        if v is None:
            continue
        # User can pass either bare values ({security_type: "Bill"}) or
        # pre-formed operator strings ({record_date: "gte:2024-01-01"}).
        sv = str(v)
        if ":" in sv:
            parts.append(f"{k}:{sv}")
        else:
            parts.append(f"{k}:eq:{sv}")
    return ",".join(parts) if parts else None


class TreasuryDirectAdapter(ProviderAdapter):
    """Adapter for the public Treasury Fiscal Data auctions_query dataset."""

    name: ClassVar[str] = "treasury_direct"
    nominal_mode: ClassVar[DataMode] = DataMode.LIVE_OFFICIAL

    def capabilities(self) -> set[str]:
        return {"auctions_upcoming", "auctions_results", "auctions_query"}

    async def query_auctions(
        self,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        sort: str | None = None,
    ) -> dict[str, Any]:
        """Run an auctions_query against the Fiscal Service dataset.

        Returns the raw envelope (``{"data": [...], "meta": {...}, ...}``)
        so callers can decide how to project. Pass ``filters={"record_date": "gte:2026-01-01"}``
        to scope. Either bare values (treated as ``eq``) or full operator
        strings (``"gte:2026-01-01"``) are accepted.
        """
        params: dict[str, Any] = {}
        f = _serialise_filters(filters)
        if f:
            params["filter"] = f
        if fields:
            if not isinstance(fields, list) or any(not isinstance(x, str) for x in fields):
                raise AdapterError("fields must be a list[str]")
            params["fields"] = ",".join(fields)
        if sort:
            params["sort"] = sort

        client = await get_client()
        started = time.monotonic()
        try:
            r = await client.get(_AUCTIONS_URL, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001 — record-and-reraise
            self._record_failure(exc)
            raise AdapterError(f"treasury_direct query failed: {exc}") from exc
        self._record_success(int((time.monotonic() - started) * 1000))
        return data
