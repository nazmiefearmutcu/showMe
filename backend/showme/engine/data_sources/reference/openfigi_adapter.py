"""OpenFIGI adapter — universal symbol → FIGI/exchange resolution.

Public API: https://www.openfigi.com/api
Anonymous: 25 req/min. With API key: 250 req/min.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest
from showme.engine.utils.throttle import throttle


class OpenFIGIRateLimited(Exception):
    """OpenFIGI refused or would not wait for a request (HTTP 429 or pacing budget).

    Raised instead of returning an empty match list, so a caller can report the
    identifiers as unresolved rather than as "no match".
    """

    def __init__(self, message: str, retry_after: float | None = None, *, local_pacing: bool = False) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        # True when the refusal came from this process's pacing budget, so no
        # request was sent. False when OpenFIGI itself answered HTTP 429.
        self.local_pacing = local_pacing


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


class OpenFIGIAdapter(BaseDataSource):
    name = "openfigi"
    supported_kinds = (DataKind.REFDATA,)
    rate_limit_rps = 0.41
    requires_api_key = False
    api_key_env = "OPENFIGI_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url", "https://api.openfigi.com/v3"
        )
        self.api_key = os.environ.get(self.api_key_env)
        # Authenticated bumps the per-min budget to 250 → ~4 rps.
        if self.api_key:
            self.rate_limit_rps = 4.0
        self._client: httpx.AsyncClient | None = None
        # Monotonic time of the next free request slot (per-instance pacing).
        self._next_slot = 0.0

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["X-OPENFIGI-APIKEY"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.base_url, headers=headers,
                timeout=self.timeout_seconds,
            )
        return self._client

    @property
    def max_jobs_per_request(self) -> int:
        """Documented /mapping job limit per request: 10 anonymous, 100 with a key."""
        return 100 if self.api_key else 10

    async def lookup_batch(
        self, jobs: list[tuple[str, str]], *, max_wait_seconds: float,
    ) -> list[dict[str, Any]]:
        """Resolve ``(id_type, id_value)`` jobs in ONE /mapping request.

        Returns one entry per job, in order: ``{"data": [...], "warning": str|None}``.
        Pacing uses ``rate_limit_rps`` (anonymous 0.41 = 25 per minute). When the
        wait needed to stay inside the budget exceeds ``max_wait_seconds``, the
        call is refused before anything is sent. HTTP 429 raises
        ``OpenFIGIRateLimited`` with the retry-after value and never returns [].
        """
        if not jobs:
            return []
        if len(jobs) > self.max_jobs_per_request:
            raise ValueError(f"OpenFIGI accepts at most {self.max_jobs_per_request} jobs per request")
        now = time.monotonic()
        start = max(now, self._next_slot)
        wait = start - now
        if wait > max_wait_seconds:
            raise OpenFIGIRateLimited(
                "OpenFIGI rate limit pacing held the request back locally: "
                f"a {wait:.1f} s wait exceeds the {max_wait_seconds:.1f} s budget; no request was sent",
                retry_after=wait,
                local_pacing=True,
            )
        if wait > 0:
            await asyncio.sleep(wait)
        self._next_slot = start + 1.0 / self.rate_limit_rps
        client = await self._client_()
        body = [{"idType": t, "idValue": v} for t, v in jobs]
        try:
            r = await client.post("/mapping", json=body)
            r.raise_for_status()
            results = r.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                self._record_failure(exc)
                raise OpenFIGIRateLimited(
                    "OpenFIGI rate limit reached (HTTP 429)",
                    retry_after=_retry_after(exc.response),
                ) from exc
            raise
        out: list[dict[str, Any]] = []
        for idx in range(len(jobs)):
            item = results[idx] if isinstance(results, list) and idx < len(results) else {}
            if not isinstance(item, dict):
                item = {}
            out.append({"data": item.get("data") or [], "warning": item.get("warning")})
        return out

    @throttle(rps=4.0)
    async def lookup_by(
        self, *, id_type: str, id_value: str,
        exch_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """Look up by any OpenFIGI idType (ID_ISIN / ID_CUSIP / ID_SEDOL / TICKER)."""
        client = await self._client_()
        body: list[dict[str, Any]] = [{"idType": id_type, "idValue": id_value}]
        if exch_code:
            body[0]["exchCode"] = exch_code
        try:
            r = await client.post("/mapping", json=body)
            r.raise_for_status()
            results = r.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                self._record_failure(exc)
                raise OpenFIGIRateLimited(
                    "OpenFIGI rate limit reached (HTTP 429)",
                    retry_after=_retry_after(exc.response),
                ) from exc
            raise
        if not results:
            return []
        first = results[0].get("data") or []
        return first or []

    @throttle(rps=4.0)
    async def lookup(self, ticker: str, exch_code: str | None = None) -> dict[str, Any] | None:
        """Resolve a ticker to its OpenFIGI record. Returns first hit."""
        client = await self._client_()
        body = [{"idType": "TICKER", "idValue": ticker.upper()}]
        if exch_code:
            body[0]["exchCode"] = exch_code
        try:
            r = await client.post("/mapping", json=body)
            r.raise_for_status()
            results = r.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                self._record_failure(exc)
                raise OpenFIGIRateLimited(
                    "OpenFIGI rate limit reached (HTTP 429)",
                    retry_after=_retry_after(exc.response),
                ) from exc
            raise
        if not results:
            return None
        first = results[0].get("data") or []
        return first[0] if first else None

    async def fetch(self, request: DataRequest) -> Any:
        if request.kind != DataKind.REFDATA:
            return None
        if not request.symbols and request.instrument:
            request.symbols = [request.instrument.symbol]
        out: list[dict[str, Any]] = []
        for sym in request.symbols:
            r = await self.lookup(sym)
            if r:
                out.append(r)
        return out
