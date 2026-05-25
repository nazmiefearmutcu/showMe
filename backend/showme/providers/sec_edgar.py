"""SEC EDGAR adapter — public company facts / submissions / ticker mapping.

All endpoints documented at https://www.sec.gov/edgar/sec-api-documentation.
SEC requires a real ``User-Agent`` on every request; we supply one via the
shared httpx client in ``_http.py``.
"""
from __future__ import annotations

import time
from typing import Any, ClassVar

from .base import AdapterError, DataMode, ProviderAdapter
from ._http import get_client

__all__ = ["SecEdgarAdapter"]


_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_CONCEPT_URL = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
)


def _pad_cik(cik: str) -> str:
    """SEC CIK paths use a 10-digit zero-padded form."""
    digits = "".join(c for c in str(cik) if c.isdigit())
    if not digits:
        raise AdapterError(f"invalid CIK: {cik!r}")
    return digits.zfill(10)


class SecEdgarAdapter(ProviderAdapter):
    """Adapter for the SEC EDGAR public APIs."""

    name: ClassVar[str] = "sec_edgar"
    nominal_mode: ClassVar[DataMode] = DataMode.LIVE_OFFICIAL

    def __init__(self) -> None:
        super().__init__()
        # Lightweight in-process cache of ticker→CIK so the bootstrap fetch
        # only runs once per process lifetime. Mutated under the asyncio
        # event loop only (no need for a lock).
        self._ticker_cache: dict[str, str] | None = None

    def capabilities(self) -> set[str]:
        return {
            "company_submissions",
            "company_facts",
            "company_concept",
            "ticker_to_cik",
        }

    # ---- internal HTTP -----------------------------------------------

    async def _get_json(self, url: str) -> Any:
        """GET a JSON payload, timing it + recording success/failure."""
        client = await get_client()
        started = time.monotonic()
        try:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001 — record-and-reraise
            self._record_failure(exc)
            raise AdapterError(f"sec_edgar GET {url} failed: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        self._record_success(latency_ms)
        return data

    # ---- public API ---------------------------------------------------

    async def lookup_cik(self, ticker: str) -> str | None:
        """Resolve ``ticker`` (case-insensitive) to a 10-digit CIK string.

        Returns ``None`` if the symbol isn't in EDGAR's company-tickers map.
        """
        if not ticker:
            return None
        symbol = ticker.strip().upper()
        if self._ticker_cache is None:
            payload = await self._get_json(_TICKERS_URL)
            # SEC's payload is ``{"0": {"cik_str": 320193, "ticker": "AAPL", ...}, ...}``
            mapping: dict[str, str] = {}
            iterable = payload.values() if isinstance(payload, dict) else payload
            for entry in iterable:
                if not isinstance(entry, dict):
                    continue
                t = entry.get("ticker")
                c = entry.get("cik_str")
                if t is None or c is None:
                    continue
                mapping[str(t).upper()] = _pad_cik(str(c))
            self._ticker_cache = mapping
        return self._ticker_cache.get(symbol)

    async def get_submissions(self, cik: str) -> dict[str, Any]:
        """Recent filings + company metadata for a CIK."""
        url = _SUBMISSIONS_URL.format(cik=_pad_cik(cik))
        return await self._get_json(url)

    async def get_facts(self, cik: str) -> dict[str, Any]:
        """All XBRL facts (every concept ever filed) for a CIK."""
        url = _FACTS_URL.format(cik=_pad_cik(cik))
        return await self._get_json(url)

    async def get_concept(self, cik: str, concept: str) -> dict[str, Any]:
        """A single us-gaap XBRL concept (e.g. ``Revenues``) for a CIK."""
        if not concept:
            raise AdapterError("concept must be non-empty")
        url = _CONCEPT_URL.format(cik=_pad_cik(cik), concept=concept)
        return await self._get_json(url)
