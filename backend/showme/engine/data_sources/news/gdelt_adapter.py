"""GDELT DOC plus official Article List, with bounded background refresh.

DOC can require a slow TLS handshake and enforces per-IP throttling.
One factory-owned adapter coordinates direct function calls in this process.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


class GDELTAdapter(BaseDataSource):
    name = "gdelt"
    supported_kinds = (DataKind.NEWS,)
    rate_limit_rps = 0.2
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url", "https://api.gdeltproject.org/api/v2/doc/doc"
        )
        self._client: httpx.AsyncClient | None = None
        self._gate = asyncio.Lock()
        self._next_request = 0.0
        self._backoff = 0
        self._inflight: dict[tuple, asyncio.Task] = {}
        self._cache: dict[tuple, tuple[float, list]] = {}
        self._world_task: asyncio.Task | None = None
        self._world_result: tuple[list, str, str | None] = ([], "gdelt", None)
        self._world_checked = 0.0

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(25.0, connect=15.0),
            )
        return self._client

    async def search(
        self, query: str, *,
        max_records: int = 50,
        start: datetime | None = None,
        end: datetime | None = None,
        sort: str = "DateDesc",
        mode: str = "ArtList",
    ) -> list[dict[str, Any]]:
        client = await self._client_()
        params: dict[str, Any] = {
            "query": query,
            "format": "json",
            "maxrecords": max(1, min(int(max_records), 250)),
            "sort": sort,
            "mode": mode,
        }
        if start:
            params["startdatetime"] = start.strftime("%Y%m%d%H%M%S")
        if end:
            params["enddatetime"] = end.strftime("%Y%m%d%H%M%S")
        key = tuple(sorted(params.items()))
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return list(cached[1])
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._request(client, params, key))
            self._inflight[key] = task
            def finished(done):
                self._inflight.pop(key, None)
                if not done.cancelled():
                    done.exception()  # retrieve failures even after caller cancellation
            task.add_done_callback(finished)
        return list(await asyncio.shield(task))

    async def _request(self, client, params, key):
        async with self._gate:
            delay = self._next_request - time.monotonic()
            if self._backoff and delay > 0:
                raise DataSourceError(f"GDELT HTTP 429 backoff: {delay:.0f}s remaining")
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request = time.monotonic() + 5.1
            r = await client.get(self.base_url, params=params)
            if r.status_code == 429:
                self._backoff = min(self._backoff + 1, 6)
                wait = min(30 * 2 ** (self._backoff - 1), 900)
                retry = r.headers.get("Retry-After", "")
                try:
                    wait = max(wait, float(retry))
                except ValueError:
                    try:
                        wait = max(wait, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError):
                        pass
                self._next_request = time.monotonic() + wait
            r.raise_for_status()
            payload = r.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
                raise DataSourceError("GDELT returned an invalid article response")
            self._backoff = 0
            rows = [a for a in payload["articles"] if isinstance(a, dict) and a.get("title") and a.get("url")]
            rows = [{**a, "source": "gdelt", "timestamp_basis": "gdelt_seen_time"} for a in rows]
            self._cache[key] = (time.monotonic(), rows)
            while len(self._cache) > 64:
                self._cache.pop(next(iter(self._cache)))
            return rows

    async def world_snapshot(self, query: str, now: datetime, limit: int = 1000):
        """Return promptly; DOC and official GAL refresh outside the UI deadline."""
        # `done()` guard: if a refresh died before reaching its finally
        # block, a dead task reference must not lock the snapshot forever.
        if (self._world_task is None or self._world_task.done()) and time.monotonic() - self._world_checked >= 60:
            self._world_task = asyncio.create_task(self._refresh_world(query, now, limit))
        if time.monotonic() - self._world_checked > 180:
            return [], "gdelt", "GDELT background refresh pending; no fresh snapshot"
        rows, source, note = self._world_result
        return list(rows), source, note

    async def _refresh_world(self, query, now, limit):
        try:
            from datetime import timedelta
            from urllib.parse import urlparse
            from showme.engine.data_sources.news.rss_adapter import _parse_feed, _world_wire_relevant
            from showme.engine.services.world_events import parse_when_utc
            gal_url = "https://data.gdeltproject.org/gdeltv3/gal/feed.rss"

            async def gal():
                client = await self._client_()
                response = await client.get(gal_url, timeout=8)
                response.raise_for_status()
                if len(response.content) > 5_000_000:
                    raise DataSourceError("GDELT GAL feed exceeds size budget")
                articles = await asyncio.to_thread(_parse_feed, response.text, gal_url)
                accepted, seen = [], set()
                for article in articles:
                    url = article.get("link", "")
                    stamp = parse_when_utc(article.get("published_at"))
                    if (url in seen or urlparse(url).scheme not in {"https", "http"}
                            or not stamp or not  -300 <= (now - stamp).total_seconds() <= 7200
                            or not _world_wire_relevant(article)):
                        continue
                    seen.add(url)
                    article.update(publisher=urlparse(url).hostname, source="gdelt_gal",
                                   language_basis="unknown", timestamp_basis="provider_feed_time")
                    accepted.append(article)
                accepted.sort(key=lambda a: a["published_at"], reverse=True)
                return accepted[:limit]

            async def doc():
                return await self.search(query, start=(now - timedelta(days=2)).replace(second=0, microsecond=0), max_records=75)

            tasks = {asyncio.create_task(gal()): "gdelt_gal", asyncio.create_task(doc()): "gdelt"}
            results, errors = {}, []
            try:
                pending = set(tasks)
                async with asyncio.timeout(40):
                    while pending:
                        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            source = tasks[task]
                            try:
                                results[source] = task.result()
                            except Exception as exc:
                                errors.append(f"{source}: {type(exc).__name__}: {str(exc)[:160]}")
                        rows, seen = [], set()
                        for source in ("gdelt", "gdelt_gal"):
                            for item in results.get(source, []):
                                url = item.get("url") or item.get("link")
                                if url not in seen:
                                    seen.add(url)
                                    rows.append(item)
                        if rows:
                            source = "+".join(s for s in ("gdelt", "gdelt_gal") if results.get(s))
                            note = "; ".join(errors)
                            if results.get("gdelt_gal"):
                                note += "; GAL language is not supplied; keyword relevance is heuristic, feed times may be discovery times"
                            self._world_result = (rows[:limit], source, note.strip("; ") or None)
                            self._world_checked = time.monotonic()
            except TimeoutError:
                errors.append("GDELT background refresh timed out")
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if not any(results.values()):
                    self._world_result = ([], "gdelt", "; ".join(errors) or "GDELT returned no usable rows")
                    self._world_checked = time.monotonic()
        finally:
            # Clear the slot whatever happened above — a prologue failure
            # (e.g. an import error) must not leave a dead task reference
            # that blocks every future refresh.
            self._world_task = None

    async def aclose(self):
        tasks = [*self._inflight.values()]
        if self._world_task:
            tasks.append(self._world_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._client:
            await self._client.aclose()

    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        q = request.extra.get("query") or (
            request.instrument.symbol if request.instrument else None
        ) or (request.symbols[0] if request.symbols else None)
        if not q:
            raise DataSourceError("GDELT requires a query")
        return await self.search(
            q, start=request.start, end=request.end,
            max_records=request.limit or 50,
        )
