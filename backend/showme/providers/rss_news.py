"""RSS / Atom news-feed adapter.

Prefers the ``feedparser`` package when available (handles the long tail
of broken-but-common feed dialects); falls back to a lean
:mod:`xml.etree.ElementTree`-based parser when ``feedparser`` is missing
so the adapter never hard-errors on import.

Network I/O is performed via the shared :mod:`httpx` client; feedparser
itself is invoked only on the in-memory XML body and is wrapped in
:func:`asyncio.to_thread` because its C extension can briefly block.
"""
from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from .base import AdapterError, DataMode, ProviderAdapter
from ._http import get_client

__all__ = ["RssAdapter"]


def _detect_feedparser() -> bool:
    try:
        import feedparser  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


_HAVE_FEEDPARSER = _detect_feedparser()


def _coerce_iso(value: Any) -> str:
    """Best-effort: turn whatever a feed gave us into an ISO 8601 UTC string."""
    if not value:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        # RFC-822 first (most RSS), then ISO.
        try:
            dt = parsedate_to_datetime(value)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).isoformat()


def _parse_with_feedparser(xml_text: str, source_hint: str) -> list[dict[str, str]]:
    import feedparser  # type: ignore
    parsed = feedparser.parse(xml_text)
    source = (parsed.feed.get("title") if parsed.feed else None) or source_hint
    out: list[dict[str, str]] = []
    for entry in parsed.entries:
        published = entry.get("published") or entry.get("updated") or ""
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if struct:
            published_iso = datetime(*struct[:6], tzinfo=timezone.utc).isoformat()
        else:
            published_iso = _coerce_iso(published)
        out.append({
            "title": str(entry.get("title", "") or ""),
            "link": str(entry.get("link", "") or ""),
            "published": published_iso,
            "summary": str(entry.get("summary", "") or ""),
            "source": str(source),
        })
    return out


def _parse_with_stdlib(xml_text: str, source_hint: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except Exception:
        return []
    # RSS 2.0: <rss><channel><item> ... </item></channel></rss>
    # Atom 1.0: <feed><entry> ... </entry></feed>
    channel = root.find("channel")
    if channel is not None:
        feed_title_node = channel.find("title")
        feed_title = feed_title_node.text if feed_title_node is not None else None
        items = channel.findall("item")
        getters = ("title", "link", "pubDate", "description")
    else:
        feed_title_node = root.find("{http://www.w3.org/2005/Atom}title")
        feed_title = feed_title_node.text if feed_title_node is not None else None
        items = root.findall("{http://www.w3.org/2005/Atom}entry")
        getters = (
            "{http://www.w3.org/2005/Atom}title",
            "{http://www.w3.org/2005/Atom}link",
            "{http://www.w3.org/2005/Atom}published",
            "{http://www.w3.org/2005/Atom}summary",
        )
    source = feed_title or source_hint
    out: list[dict[str, str]] = []
    for node in items:
        title_node = node.find(getters[0])
        link_node = node.find(getters[1])
        date_node = node.find(getters[2])
        summary_node = node.find(getters[3])
        title = (title_node.text if title_node is not None else "") or ""
        # Atom links are usually in @href, RSS in element text.
        if link_node is not None:
            link = link_node.get("href") or (link_node.text or "")
        else:
            link = ""
        published = (date_node.text if date_node is not None else "") or ""
        summary = (summary_node.text if summary_node is not None else "") or ""
        out.append({
            "title": title.strip(),
            "link": (link or "").strip(),
            "published": _coerce_iso(published),
            "summary": summary.strip(),
            "source": str(source),
        })
    return out


class RssAdapter(ProviderAdapter):
    """Adapter that fetches and normalises RSS / Atom news feeds.

    Capabilities:
      * ``feed_fetch`` — fetch one feed URL, return normalised entries
      * ``feed_aggregate`` — fetch many URLs concurrently, dedupe + sort
    """

    name = "rss"
    nominal_mode = DataMode.DELAYED_REFERENCE

    def capabilities(self) -> set[str]:
        return {"feed_fetch", "feed_aggregate"}

    async def fetch(self, url: str) -> list[dict[str, str]]:
        """Fetch a single feed URL.

        Returns a list of dicts with keys: ``title``, ``link``,
        ``published`` (ISO 8601 UTC string), ``summary``, ``source``.
        """
        client = await get_client()
        t0 = time.perf_counter()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            xml_text = resp.text
        except Exception as exc:
            self._record_failure(exc)
            raise AdapterError(f"rss fetch failed for {url}: {exc}") from exc
        self._record_success(int((time.perf_counter() - t0) * 1000))
        if _HAVE_FEEDPARSER:
            try:
                # feedparser holds the GIL inside its C accelerator; offload.
                return await asyncio.to_thread(_parse_with_feedparser, xml_text, url)
            except Exception:
                # Soft-fallback to stdlib parser; don't mark adapter unhealthy.
                pass
        return _parse_with_stdlib(xml_text, url)

    async def aggregate(
        self,
        urls: list[str],
        dedupe_by: str = "link",
    ) -> list[dict[str, str]]:
        """Fetch several feeds concurrently; merge, dedupe, sort.

        Args:
            urls: Feed URLs to fetch in parallel.
            dedupe_by: Entry key to dedupe on (``"link"`` default,
                ``"title"`` also useful for feeds with synthetic links).

        Returns:
            List of entry dicts, newest-first (by ``published``).
            Failed feeds are silently skipped — the adapter's
            ``mode()`` only flips on a total-stack failure (no entries
            recovered AND every fetch failed).
        """
        if not urls:
            return []
        results = await asyncio.gather(
            *(self.fetch(u) for u in urls),
            return_exceptions=True,
        )
        merged: list[dict[str, str]] = []
        all_failed = True
        for r in results:
            if isinstance(r, BaseException):
                continue
            all_failed = False
            merged.extend(r)
        if all_failed:
            # Every single feed errored — keep the adapter degraded.
            return []
        # Restore healthy state if we got at least one feed back.
        self._last_error = None

        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for entry in merged:
            key = (entry.get(dedupe_by) or "").strip()
            if not key:
                deduped.append(entry)
                continue
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)

        deduped.sort(key=lambda e: e.get("published", ""), reverse=True)
        return deduped
