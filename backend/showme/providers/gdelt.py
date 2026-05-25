"""GDELT 2.0 DOC API adapter (no auth required).

Documented at https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/.
Free, anonymous endpoint — rate limits are enforced per IP and are
loose enough for interactive use, but bulk scraping should batch
queries.
"""
from __future__ import annotations

import time
from typing import Any

from .base import AdapterError, DataMode, ProviderAdapter
from ._http import get_client

__all__ = ["GdeltAdapter"]

_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


class GdeltAdapter(ProviderAdapter):
    """GDELT DOC 2.0 query adapter.

    Capabilities:
      * ``doc_search`` — article-list search (mode=``artlist``)
      * ``timeline_volume`` — volume-over-time series (mode=``timelinevol``)
    """

    name = "gdelt"
    nominal_mode = DataMode.LIVE_OFFICIAL

    def capabilities(self) -> set[str]:
        return {"doc_search", "timeline_volume"}

    async def _request(self, params: dict[str, Any]) -> dict[str, Any] | str:
        """Issue a GET against the DOC endpoint, returning JSON if format
        was ``json`` else the raw text body.
        """
        client = await get_client()
        t0 = time.perf_counter()
        try:
            resp = await client.get(_BASE_URL, params=params)
            resp.raise_for_status()
        except Exception as exc:
            self._record_failure(exc)
            raise AdapterError(f"gdelt request failed: {exc}") from exc
        self._record_success(int((time.perf_counter() - t0) * 1000))
        if params.get("format") == "json":
            try:
                return resp.json()
            except Exception as exc:
                self._record_failure(exc)
                raise AdapterError(f"gdelt returned invalid JSON: {exc}") from exc
        return resp.text

    async def doc_search(
        self,
        query: str,
        timespan: str = "24h",
        mode: str = "artlist",
        maxrecords: int = 75,
        format: str = "json",
        sort: str = "datedesc",
    ) -> dict[str, Any]:
        """Run a DOC article search.

        Args:
            query: GDELT query string (Lucene-ish; see GDELT DOC docs).
            timespan: Look-back window (``"15min"``, ``"1h"``, ``"24h"``,
                ``"1w"``, ``"1m"``, ``"3m"``, ``"1y"``...).
            mode: GDELT API mode — defaults to ``artlist`` (article list).
            maxrecords: Cap on returned articles (GDELT max 250).
            format: ``"json"`` (default) or ``"html"``.
            sort: ``datedesc`` (newest first), ``dateasc``, ``tonedesc``,
                ``toneasc``, ``hybridrel``.

        Returns:
            JSON-decoded GDELT response (a dict with an ``articles`` list).
        """
        params: dict[str, Any] = {
            "query": query,
            "timespan": timespan,
            "mode": mode,
            "maxrecords": int(maxrecords),
            "format": format,
            "sort": sort,
        }
        payload = await self._request(params)
        if isinstance(payload, str):
            # Caller requested a non-JSON format; wrap in dict so the
            # method signature stays consistent.
            return {"raw": payload}
        return payload

    async def timeline_volume(
        self,
        query: str,
        timespan: str = "1w",
    ) -> dict[str, Any]:
        """Run a timeline-volume query (mode=``timelinevol``).

        Args:
            query: GDELT query string.
            timespan: Look-back window (see :meth:`doc_search`).

        Returns:
            JSON-decoded GDELT response.
        """
        params: dict[str, Any] = {
            "query": query,
            "timespan": timespan,
            "mode": "timelinevol",
            "format": "json",
        }
        payload = await self._request(params)
        if isinstance(payload, str):
            return {"raw": payload}
        return payload
