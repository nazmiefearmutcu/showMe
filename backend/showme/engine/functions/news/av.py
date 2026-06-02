"""AV — Audio / Video Archive (investor-relevant media + filings events).

The manifest (``manifest/seeds/av_seed.py``) promises a *playable archive of
investor-relevant audio and video — earnings call audio, central bank
pressers, conference replays, podcast episodes — with real, time-anchored
URLs* and, when a ``symbol`` is supplied, an archive filtered to that name.

Historically ``execute()`` returned a hardcoded ``_media_template()`` placeholder
list with ``status="model"`` whenever the (undocumented) ``live_media`` flag was
absent — i.e. the DEFAULT path was a "coming soon" stub, the exact thing the
manifest forbids. This module now fetches REAL keyless media on the default
path:

* **Symbol supplied** → SEC EDGAR submissions feed (keyless, needs a descriptive
  User-Agent) gives the company's most recent investor-relevant filings
  (8-K material events, 10-Q/10-K results, ARS annual reports, DEF 14A). Each
  becomes a real, time-anchored, openable archive row whose ``play_url`` /
  ``url`` is the live SEC filing-index HTTPS link. These are the analyst-
  relevant "events" for the name.
* **No symbol (global archive)** → public finance/markets podcast RSS feeds
  (NPR Planet Money / The Indicator / Up First) give real, playable audio
  episodes with verifiable enclosure URLs and durations.

On a genuine network outage the function returns ``status="provider_unavailable"``
with an honest warning and ``next_actions`` — it never fabricates rows.
"""

from __future__ import annotations

import re
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


_PODCAST_FEEDS = [
    "https://feeds.npr.org/510289/podcast.xml",  # Planet Money
    "https://feeds.npr.org/510325/podcast.xml",  # The Indicator from Planet Money
    "https://feeds.npr.org/510318/podcast.xml",  # Up First, for current audio headlines
    "https://feeds.simplecast.com/3hnxp7yk",      # Finance/business interview archive
]

# SEC EDGAR form code -> human media_type the manifest enumerates / understands.
_FORM_MEDIA_TYPE = {
    "8-K": "earnings_call",       # material events incl. earnings releases / calls
    "8-K/A": "earnings_call",
    "10-Q": "earnings_call",
    "10-K": "earnings_call",
    "ARS": "conference",          # annual report to shareholders
    "DEF 14A": "conference",      # proxy / annual meeting
    "DEFA14A": "conference",
    "6-K": "earnings_call",       # foreign-issuer interim report
    "20-F": "earnings_call",      # foreign-issuer annual report
}

_FIELD_DICTIONARY = {
    "event_date": "Filing / recording timestamp (ISO-8601, UTC).",
    "symbol": "Primary ticker for the issuer (uppercase).",
    "title": "Display title for the media / filing event.",
    "media_type": "earnings_call / central_bank_presser / conference / podcast / interview.",
    "duration_seconds": "Asset duration in seconds when known (podcast enclosures); null for filings.",
    "play_url": "Verifiable HTTPS link to open / play the asset (SEC filing index or audio enclosure).",
    "url": "Alias of play_url for table action columns.",
    "source": "Source publisher (sec.gov, NPR Planet Money, ...).",
    "has_transcript": "True when a textual transcript/document is directly attached.",
}

_METHODOLOGY = (
    "AV returns a playable archive of investor-relevant media — never a 'coming "
    "soon' placeholder. When a symbol is supplied, the default path queries the "
    "keyless SEC EDGAR submissions feed "
    "(https://data.sec.gov/submissions/CIK##########.json, descriptive "
    "User-Agent required) and turns the issuer's most recent material filings "
    "(8-K events, 10-Q/10-K results, ARS, DEF 14A) into real, time-anchored "
    "rows whose play_url is the live HTTPS SEC filing-index page. When no symbol "
    "is supplied, public finance/markets podcast RSS feeds (NPR Planet Money / "
    "The Indicator / Up First) supply real playable audio episodes with "
    "enclosure URLs and durations. Empty filter results return rows=[] with a "
    "warning, never a synthetic row. On a genuine network outage the function "
    "reports status='provider_unavailable' with an honest warning."
)


@FunctionRegistry.register
class AVFunction(BaseFunction):
    code = "AV"
    name = "Audio/Video Archive"
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        limit = max(1, min(int(params.get("limit", 25) or 25), 100))
        query = str(params.get("query") or "").strip()
        symbol = self._resolve_symbol(instrument, params)
        try:
            import asyncio
            return await asyncio.wait_for(
                self._execute_inner(instrument, symbol, query, limit, params),
                timeout=9.0,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            reason = f"AV execution timed out: {exc}"
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "items": [],
                    "query": query,
                    "symbol": symbol,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "cards": _cards([], data_mode="not_configured"),
                    "reason": reason,
                    "next_actions": [
                        "Retry once the media/filings provider is reachable.",
                    ],
                },
                sources=["sec_edgar" if symbol else "podcast_rss"],
                metadata={"provider_errors": [reason], "live": True, "data_mode": "not_configured"},
                warnings=[reason],
            )

    async def _execute_inner(
        self,
        instrument: Instrument | None,
        symbol: str,
        query: str,
        limit: int,
        params: dict[str, Any],
    ) -> FunctionResult:
        if symbol:
            return await self._symbol_archive(instrument, symbol, query, limit, params)
        return await self._podcast_archive(query, limit, params)

    # ------------------------------------------------------------------ symbol
    async def _symbol_archive(
        self,
        instrument: Instrument | None,
        symbol: str,
        query: str,
        limit: int,
        params: dict[str, Any],
    ) -> FunctionResult:
        """Build a per-symbol media/event archive from keyless SEC EDGAR."""
        errors: list[str] = []
        rows: list[dict[str, Any]] = []
        try:
            filings = await self._fetch_sec_submissions(symbol, params)
        except Exception as exc:  # noqa: BLE001
            return self._provider_unavailable(
                instrument,
                query,
                symbol,
                reason=(
                    f"SEC EDGAR is unreachable for {symbol}; cannot build the "
                    "filings/media archive right now."
                ),
                sources=["sec_edgar"],
                errors=[str(exc) or type(exc).__name__],
            )

        if filings is None:
            # Resolved cleanly but the ticker has no EDGAR mapping (e.g. crypto/FX).
            return await self._podcast_archive(
                query, limit, params, symbol=symbol,
                note=f"No SEC EDGAR filer maps to '{symbol}'; showing the global media archive.",
                instrument=instrument,
            )

        for f in filings:
            row = self._filing_row(symbol, f)
            if row and _matches_query(row, query):
                rows.append(row)

        rows = _dedupe(rows)[:limit]
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "rows": [],
                    "items": [],
                    "query": query,
                    "symbol": symbol,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "cards": _cards([], data_mode="live_official"),
                    "reason": f"No archive entries for {symbol} match these filters.",
                    "next_actions": [
                        "Clear or broaden the media query.",
                        "Try a different symbol with public SEC filings.",
                    ],
                },
                sources=["sec_edgar"],
                metadata={"provider_errors": errors, "live": True, "data_mode": "live_official"},
            )

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": rows,
                "items": rows,
                "query": query,
                "symbol": symbol,
                "count": len(rows),
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "cards": _cards(rows, data_mode="live_official"),
            },
            sources=["sec_edgar"],
            metadata={"provider_errors": errors, "live": True, "data_mode": "live_official"},
        )

    async def _fetch_sec_submissions(
        self, symbol: str, params: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """Return recent filings for ``symbol`` from SEC EDGAR (keyless).

        Returns ``None`` when the ticker cannot be mapped to a CIK (e.g. a
        non-US / non-equity instrument), so the caller can degrade to the
        global podcast archive. Raises on a real network error.
        """
        cik = await self._resolve_cik(symbol, params)
        if not cik:
            return None

        timeout = float(params.get("media_timeout", 8))
        ua = {"User-Agent": "showMe research showme@example.com"}
        url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"

        # Prefer a wired adapter if it exposes a usable fetch; else raw HTTP.
        adapter = getattr(self.deps, "sec_edgar", None)
        getter = getattr(adapter, "get_submissions", None) if adapter else None
        if callable(getter):
            data = getter(cik)
            data = await data if hasattr(data, "__await__") else data
        else:
            data = await _get_json(url, ua, timeout)

        recent = ((data or {}).get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        report_dates = recent.get("reportDate") or []
        accessions = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        primary_descs = recent.get("primaryDocDescription") or []
        items = recent.get("items") or []

        out: list[dict[str, Any]] = []
        n = min(len(forms), len(dates), len(accessions))
        for i in range(n):
            out.append(
                {
                    "cik": int(cik),
                    "form": forms[i],
                    "filing_date": dates[i],
                    "report_date": report_dates[i] if i < len(report_dates) else "",
                    "accession": accessions[i],
                    "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
                    "primary_desc": primary_descs[i] if i < len(primary_descs) else "",
                    "edgar_items": items[i] if i < len(items) else "",
                }
            )
        # Keep the investor-relevant forms; fall back to all when none match so
        # the archive is never empty for an active filer.
        relevant = [f for f in out if f.get("form") in _FORM_MEDIA_TYPE]
        return relevant or out

    async def _resolve_cik(self, symbol: str, params: dict[str, Any]) -> int | None:
        """Map a ticker to a SEC CIK via the keyless company_tickers feed.

        The wired ``SecEdgarAdapter`` exposes ``lookup_cik`` (returns a 10-digit
        zero-padded CIK string or ``None``); we fall back to a direct keyless
        fetch of ``company_tickers.json`` when no adapter is wired.
        """
        adapter = getattr(self.deps, "sec_edgar", None)
        resolver = getattr(adapter, "lookup_cik", None) if adapter else None
        if callable(resolver):
            cik = resolver(symbol)
            cik = await cik if hasattr(cik, "__await__") else cik
            if cik:
                return int(str(cik).lstrip("0") or "0")

        timeout = float(params.get("media_timeout", 8))
        ua = {"User-Agent": "showMe research showme@example.com"}
        table = await _get_json(
            "https://www.sec.gov/files/company_tickers.json", ua, timeout
        )
        want = symbol.upper()
        for rec in (table or {}).values():
            if not isinstance(rec, dict):
                continue
            if str(rec.get("ticker", "")).upper() == want and rec.get("cik_str") is not None:
                return int(rec.get("cik_str"))
        return None

    def _filing_row(self, symbol: str, f: dict[str, Any]) -> dict[str, Any] | None:
        form = str(f.get("form") or "").strip()
        accession = str(f.get("accession") or "").strip()
        if not accession:
            return None
        acc_nodash = accession.replace("-", "")
        cik = int(f.get("cik") or 0)
        # Live, human-openable SEC filing index page.
        index_url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={cik}&type={form}"
        )
        primary_doc = str(f.get("primary_doc") or "").strip()
        if primary_doc:
            play_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary_doc}"
            )
        else:
            play_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
                f"{accession}-index.htm"
            )
        media_type = _FORM_MEDIA_TYPE.get(form, "conference")
        desc = str(f.get("primary_desc") or "").strip()
        edgar_items = str(f.get("edgar_items") or "").strip()
        title_bits = [f"{symbol} {form}"]
        if desc:
            title_bits.append(desc)
        elif edgar_items:
            title_bits.append(f"Items {edgar_items}")
        event_date = str(f.get("report_date") or f.get("filing_date") or "").strip()
        return {
            "event_date": event_date,
            "filing_date": str(f.get("filing_date") or ""),
            "symbol": symbol,
            "title": " — ".join(title_bits),
            "media_type": media_type,
            "duration_seconds": None,
            "play_url": play_url,
            "url": play_url,
            "source_url": index_url,
            "source": "sec.gov",
            "feed": "SEC EDGAR",
            "form": form,
            "accession": accession,
            "has_transcript": bool(primary_doc),
        }

    # ----------------------------------------------------------------- podcast
    async def _podcast_archive(
        self,
        query: str,
        limit: int,
        params: dict[str, Any],
        *,
        symbol: str = "",
        note: str | None = None,
        instrument: Instrument | None = None,
    ) -> FunctionResult:
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        parsed_feeds = 0
        try:
            import asyncio

            import feedparser
            import httpx

            timeout = float(params.get("media_timeout", 6))
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": "showMe-media-archive/1.0"},
            ) as client:
                rs = await asyncio.gather(
                    *(client.get(u) for u in _PODCAST_FEEDS), return_exceptions=True
                )
            for feed_url, r in zip(_PODCAST_FEEDS, rs, strict=False):
                if isinstance(r, Exception):
                    errors.append(f"{feed_url}: {r}")
                    continue
                if getattr(r, "status_code", 0) >= 400:
                    errors.append(f"{feed_url}: HTTP {r.status_code}")
                    continue
                feed = feedparser.parse(r.text)
                if not feed.entries:
                    errors.append(f"{feed_url}: no RSS entries")
                    continue
                parsed_feeds += 1
                for entry in feed.entries[: max(limit * 3, 15)]:
                    row = _media_row(feed.feed, entry)
                    # _media_row returns {} for entries with no openable
                    # play_url — skip them so every emitted row has a real link.
                    if row and _matches_query(row, query):
                        items.append(row)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc) or type(exc).__name__)

        items = _dedupe(items)[:limit]
        warnings = [note] if note else []
        if not items:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "items": [],
                    "query": query,
                    "symbol": symbol,
                    "feed_count": parsed_feeds,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "cards": _cards([], data_mode="not_configured"),
                    "reason": "Podcast RSS feeds returned no matching playable media.",
                    "next_actions": [
                        "Clear or broaden the media query.",
                        "Open Raw function payload to inspect RSS provider errors.",
                    ],
                },
                sources=["podcast_rss"],
                metadata={"provider_errors": errors, "live": True, "data_mode": "not_configured"},
                warnings=warnings,
            )

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": items,
                "items": items,
                "query": query,
                "symbol": symbol,
                "feed_count": parsed_feeds,
                "count": len(items),
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "cards": _cards(items, data_mode="live_official"),
            },
            sources=["podcast_rss"],
            metadata={"provider_errors": errors, "live": True, "data_mode": "live_official"},
            warnings=warnings,
        )

    # ------------------------------------------------------------------ helpers
    def _resolve_symbol(self, instrument: Instrument | None, params: dict[str, Any]) -> str:
        sym = str(params.get("symbol") or "").strip()
        if not sym and instrument is not None:
            sym = str(getattr(instrument, "symbol", "") or "").strip()
        return sym.upper()

    def _provider_unavailable(
        self,
        instrument: Instrument | None,
        query: str,
        symbol: str,
        *,
        reason: str,
        sources: list[str],
        errors: list[str],
    ) -> FunctionResult:
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "provider_unavailable",
                "rows": [],
                "items": [],
                "query": query,
                "symbol": symbol,
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "cards": _cards([], data_mode="not_configured"),
                "reason": reason,
                "next_actions": [
                    "Retry in a moment — SEC EDGAR rate-limits aggressive polling.",
                    "Clear the symbol to browse the global podcast media archive instead.",
                ],
            },
            sources=sources,
            metadata={"provider_errors": errors, "live": True, "data_mode": "not_configured"},
        )


async def _get_json(url: str, headers: dict[str, str], timeout: float) -> Any:
    """GET ``url`` as JSON via the shared keyless httpx client.

    ``showme.providers._http.get_client`` is an async factory returning the
    shared ``httpx.AsyncClient`` (which already sends a default User-Agent); we
    still pass a descriptive SEC-friendly User-Agent per request. Raises on a
    non-2xx response or any transport error so callers map it to
    ``provider_unavailable``.
    """
    from showme.providers._http import get_client

    client = await get_client()
    resp = await client.get(url, headers=headers, timeout=timeout)
    raise_for_status = getattr(resp, "raise_for_status", None)
    if callable(raise_for_status):
        raise_for_status()
    elif getattr(resp, "status_code", 200) >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} for {url}")
    return resp.json()


def _cards(rows: list[dict[str, Any]], *, data_mode: str) -> dict[str, Any]:
    with_transcript = sum(1 for r in rows if r.get("has_transcript"))
    dates = [str(r.get("event_date") or "") for r in rows if r.get("event_date")]
    latest = max(dates) if dates else None
    return {
        "total_items": len(rows),
        "items_with_transcript": with_transcript,
        "latest_event_date": latest,
        "data_mode": data_mode,
    }


def _media_row(feed: Any, entry: Any) -> dict[str, Any]:
    enclosures = list(entry.get("enclosures") or [])
    enclosure = enclosures[0] if enclosures else {}
    article_url = entry.get("link")
    audio_url = enclosure.get("href")
    duration = entry.get("itunes_duration") or entry.get("duration")
    summary = _strip_html(entry.get("summary") or entry.get("description") or "")
    play_url = audio_url or article_url
    if not play_url:
        # A media row with no openable URL is useless and violates the AV
        # contract (every row must carry a real http(s) play_url). Signal the
        # caller to skip this malformed RSS entry rather than emit a dead row.
        return {}
    # Honest media_type: surface the real enclosure MIME type (e.g. audio/mpeg)
    # when the feed provides one, so consumers can pick a player; fall back to the
    # generic "podcast" label only when the enclosure omits a type.
    media_type = enclosure.get("type") or "podcast"
    return {
        "event_date": entry.get("published"),
        "feed": feed.get("title"),
        "source": feed.get("title"),
        "symbol": "",
        "title": entry.get("title"),
        "media_type": media_type,
        "url": play_url,
        "play_url": play_url,
        "source_url": article_url,
        "published": entry.get("published"),
        "duration_seconds": _parse_duration(duration),
        "duration": duration,
        "audio_url": audio_url,
        "has_transcript": False,
        "summary": summary[:700],
    }


def _parse_duration(value: Any) -> int | None:
    """Turn an iTunes duration ('HH:MM:SS' or seconds) into integer seconds."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    parts = raw.split(":")
    if all(p.isdigit() for p in parts) and 1 < len(parts) <= 3:
        secs = 0
        for p in parts:
            secs = secs * 60 + int(p)
        return secs
    return None


def _matches_query(row: dict[str, Any], query: str) -> bool:
    """Return True when the row matches the user's query.

    BugHunt 2026-05-24: the previous implementation short-circuited TRUE for
    any query containing one of {market, markets, market news, audio, video,
    podcast}. New rule: only an empty/whitespace query returns every row.
    Otherwise extract meaningful terms (>2 chars, excluding broad-noise stop
    words) and require each to appear in the row text; if every token is a stop
    word, fall back to substring match so terse one-word queries still work.
    """
    q = (query or "").strip().lower()
    if not q:
        return True
    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("feed", "title", "summary", "form", "symbol", "media_type")
    ).lower()
    stop = {"podcast", "podcasts", "audio", "video", "media", "market", "markets", "news", "the", "and"}
    raw_terms = [term for term in re.findall(r"[a-z0-9]+", q) if len(term) > 2]
    terms = [term for term in raw_terms if term not in stop]
    if not terms:
        for term in raw_terms:
            if term in haystack:
                return True
        return False
    return all(term in haystack for term in terms[:4])


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(
            row.get("accession")
            or row.get("audio_url")
            or row.get("play_url")
            or row.get("link")
            or row.get("title")
            or ""
        )
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()
