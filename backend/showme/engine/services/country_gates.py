"""Keyless per-country data gates for the MEET pane.

The shared calendar chain (ForexFactory weekly → FinanceCalendar supplement)
only tags ~10 major currencies, so followed countries outside that set (TR,
IN, BR, …) rendered an empty MEET pane even though keyless sources exist for
them. This module adds three gates — all keyless, all real-data, all
failure-tolerant:

  * holiday gate   — Nager.Date public holidays (≈80 of the catalog
                     countries, full past+future year), with a Google
                     public-holiday ICS fallback for the few countries
                     Nager does not cover;
  * country wire   — GDELT DOC queries scoped to each followed country over
                     the 7-day lookback (the shared world query is global and
                     rarely returns enough per-country rows);
  * country RSS    — Google News RSS per followed country, fired only when
                     the wire gate still leaves the country short of the
                     20-events-per-7-days floor.

Honesty rules carried over from world_events:
  * nothing is invented — a gate that fails or returns nothing is reported
    in its status entry, never papered over,
  * rows keep their provider label (``provider`` / ``source``) so the UI's
    source-traceability audit stays intact,
  * a country the gates cannot fill to the floor is reported as an explicit
    shortfall (``shortfall`` entries), never stuffed with padding rows.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from showme.engine.services import world_events as we

# The pane must be able to list at least this many events for a followed
# country inside a 7-day window (past and future are reported separately).
MEET_GATE_MIN_EVENTS = 20
MEET_GATE_WINDOW_DAYS = 7.0

_NAGER_HOLIDAYS_URL = "https://date.nager.at/api/v3/publicholidays/{year}/{iso}"
_NAGER_TIMEOUT_S = 6.0
_HOLIDAY_TTL_S = 6 * 3600.0

# Nager.Date does not cover every catalog country; these Google public-holiday
# calendars are keyless too (probed live 2026-10-04). Countries missing from
# both simply carry no holiday rows — reported, never faked.
_GOOGLE_HOLIDAY_SLUGS: dict[str, str] = {
    "TW": "taiwan",
    "IN": "indian",
    "ID": "indonesian",
}
_GOOGLE_HOLIDAY_ICS_URL = (
    "https://calendar.google.com/calendar/ical/en.{slug}"
    "%23holiday%40group.v.calendar.google.com/public/basic.ics"
)

# Google News RSS: keyless per-country search (English edition so the
# gazetteer can tag the headlines).
_GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
_GOOGLE_NEWS_TIMEOUT_S = 6.0
_GOOGLE_NEWS_TTL_S = 180.0
_GOOGLE_NEWS_PER_COUNTRY_LIMIT = 75

# GDELT country wire: capped per pass so the DOC per-IP throttle (the adapter
# spaces requests ~5 s) cannot stack minutes of latency behind the pane.
_COUNTRY_WIRE_LIMIT = 75
_COUNTRY_WIRE_MAX_COUNTRIES = 4

_HOLIDAY_CACHE: dict[tuple[str, int], tuple[float, list[dict[str, Any]], str | None]] = {}
_GOOGLE_NEWS_CACHE: dict[str, tuple[float, list[dict[str, Any]], str | None]] = {}


def country_query_term(iso: str) -> str:
    """The gazetteer's primary English term for a country (query-ready)."""
    canonical = we.canonical_iso(iso)
    terms = we.COUNTRY_TERMS.get(canonical) or ()
    for term in terms:
        if len(term) >= 4:
            return term
    return we.country_name(canonical)


def _holiday_calendar_rows(raw: Any, *, iso: str, provider: str) -> list[dict[str, Any]]:
    """Normalize provider holiday payloads into calendar-row dicts."""
    rows: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or item.get("summary") or "").strip()
        date_raw = str(item.get("date") or item.get("date") or "").strip()
        if not name or not date_raw:
            continue
        stamp = date_raw
        if len(stamp) == 8 and stamp.isdigit():
            stamp = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        try:
            day = datetime.fromisoformat(stamp).date()
        except ValueError:
            continue
        rows.append({
            "country": iso,
            "event": f"Public Holiday: {name}",
            "date": f"{day.isoformat()}T00:00:00Z",
            "importance": "low",
            "actual": None,
            "forecast": None,
            "previous": None,
            "unit": "",
            "provider": provider,
            "country_basis": "provider",
        })
    return rows


def _parse_ics_holidays(text: str) -> list[dict[str, Any]]:
    """Minimal VEVENT parse of a Google public-holiday ICS feed."""
    events: list[dict[str, Any]] = []
    summary = ""
    start = ""
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("BEGIN:VEVENT"):
            summary, start = "", ""
        elif line.upper().startswith("SUMMARY:"):
            summary = line[len("SUMMARY:"):].strip()
        elif line.upper().startswith("DTSTART"):
            start = line.split(":", 1)[-1].strip()
        elif line.upper().startswith("END:VEVENT") and summary and start:
            stamp = start.split("T")[0]
            events.append({"date": stamp, "name": summary})
    return events


async def holiday_gate_rows(
    client: Any,
    countries: list[str],
    *,
    now: datetime,
    days_back: float = MEET_GATE_WINDOW_DAYS,
    days_ahead: float = 90.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Public-holiday calendar rows for the followed countries.

    Rows are already normalized into the calendar schema (``economic_rows``
    consumes them directly). Cache TTL is 6 h per (country, year); failures
    are reported in the status entry and never raised.
    """
    status: dict[str, Any] = {
        "gate": "holidays",
        "providers": [],
        "countries": [],
        "rows_added": 0,
        "notes": [],
    }
    isos: list[str] = []
    for token in countries:
        iso = we.canonical_iso(token) or str(token).strip().upper()
        if iso and iso not in isos:
            isos.append(iso)
    if not isos:
        status["notes"].append("no followed countries")
        return [], status

    window_start = now - timedelta(days=days_back)
    window_end = now + timedelta(days=days_ahead)
    years = sorted({window_start.year, window_end.year})
    rows: list[dict[str, Any]] = []
    seen_holidays: set[tuple[str, str, str]] = set()
    for iso in isos:
        for year in years:
            cached = _HOLIDAY_CACHE.get((iso, year))
            provider = "nager_date"
            payload: list[dict[str, Any]] | None = None
            note: str | None = None
            if cached and (time.monotonic() - cached[0]) < _HOLIDAY_TTL_S:
                payload, note = cached[1], cached[2]
            else:
                fetched: list[dict[str, Any]] = []
                try:
                    response = await client.get(
                        _NAGER_HOLIDAYS_URL.format(year=year, iso=iso),
                        timeout=_NAGER_TIMEOUT_S,
                    )
                    response.raise_for_status()
                    fetched = _holiday_calendar_rows(
                        response.json(), iso=iso, provider="nager_date"
                    )
                except Exception as exc:  # noqa: BLE001 - gate is best-effort
                    note = f"nager_date {iso}/{year}: {str(exc) or exc.__class__.__name__}"
                if not fetched and iso in _GOOGLE_HOLIDAY_SLUGS:
                    provider = "google_holidays"
                    try:
                        response = await client.get(
                            _GOOGLE_HOLIDAY_ICS_URL.format(slug=_GOOGLE_HOLIDAY_SLUGS[iso]),
                            timeout=_NAGER_TIMEOUT_S,
                        )
                        response.raise_for_status()
                        fetched = _holiday_calendar_rows(
                            _parse_ics_holidays(response.text), iso=iso, provider=provider
                        )
                    except Exception as exc:  # noqa: BLE001 - gate is best-effort
                        note = (note + "; " if note else "") + (
                            f"google_holidays {iso}/{year}: {str(exc) or exc.__class__.__name__}"
                        )
                payload = fetched
                _HOLIDAY_CACHE[(iso, year)] = (time.monotonic(), list(fetched), note)
            if note:
                status["notes"].append(note)
            for row in payload or []:
                try:
                    when = datetime.fromisoformat(row["date"])
                except ValueError:  # pragma: no cover - rows are pre-validated
                    continue
                identity = (row["country"], row["date"], row["event"])
                if window_start <= when <= window_end and identity not in seen_holidays:
                    seen_holidays.add(identity)
                    rows.append(row)
                if provider not in status["providers"]:
                    status["providers"].append(provider)
    if rows:
        status["providers"] = [p for p in status["providers"] if p]
        status["countries"] = isos
    status["rows_added"] = len(rows)
    return rows, status


async def country_wire_articles(
    gdelt: Any,
    countries: list[str],
    *,
    now: datetime,
    lookback_days: float = MEET_GATE_WINDOW_DAYS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """GDELT DOC articles scoped to each followed country (7-day lookback)."""
    status: dict[str, Any] = {
        "gate": "country_wire",
        "provider": "gdelt",
        "fired": False,
        "countries": [],
        "rows_added": 0,
        "notes": [],
    }
    if gdelt is None:
        status["notes"].append("gdelt adapter unavailable")
        return [], status
    isos: list[str] = []
    for token in countries:
        iso = we.canonical_iso(token) or str(token).strip().upper()
        if iso and iso not in isos:
            isos.append(iso)
    if not isos:
        return [], status
    chosen = isos[:_COUNTRY_WIRE_MAX_COUNTRIES]
    if len(isos) > len(chosen):
        status["notes"].append(
            f"throttled to first {len(chosen)} countries ({', '.join(chosen)})"
        )
    start = (now - timedelta(days=lookback_days)).replace(second=0, microsecond=0)

    async def _leg(iso: str) -> tuple[str, list[dict[str, Any]], str | None]:
        query = f"{country_query_term(iso)} sourcelang:english"
        try:
            if hasattr(gdelt, "search"):
                items = await gdelt.search(query, start=start, max_records=_COUNTRY_WIRE_LIMIT)
            else:
                from showme.engine.core.base_data_source import DataKind, DataRequest

                items = await gdelt.fetch(DataRequest(
                    kind=DataKind.NEWS,
                    extra={"query": query},
                    start=start,
                    limit=_COUNTRY_WIRE_LIMIT,
                ))
            return iso, list(items or []), None
        except Exception as exc:  # noqa: BLE001 - gate is best-effort
            return iso, [], f"gdelt {iso}: {str(exc) or exc.__class__.__name__}"

    legs = [_leg(iso) for iso in chosen]
    articles: list[dict[str, Any]] = []
    for iso, items, note in await asyncio.gather(*legs, return_exceptions=True):
        if isinstance(iso, BaseException):  # pragma: no cover - legs catch
            status["notes"].append(f"gdelt leg: {type(iso).__name__}")
            continue
        if note:
            status["notes"].append(note)
        if items:
            status["countries"].append(iso)
            for item in items:
                if isinstance(item, dict):
                    item.setdefault("source", "gdelt")
                    articles.append(item)
    status["rows_added"] = len(articles)
    status["fired"] = bool(articles)
    return articles, status


async def google_news_articles(
    client: Any,
    countries: list[str],
    *,
    limit: int = _GOOGLE_NEWS_PER_COUNTRY_LIMIT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Google News RSS articles per followed country (keyless, TTL-cached)."""
    status: dict[str, Any] = {
        "gate": "country_rss",
        "provider": "google_news",
        "fired": False,
        "countries": [],
        "rows_added": 0,
        "notes": [],
    }
    isos: list[str] = []
    for token in countries:
        iso = we.canonical_iso(token) or str(token).strip().upper()
        if iso and iso not in isos:
            isos.append(iso)
    if not isos or client is None:
        status["notes"].append("no followed countries or no http client")
        return [], status
    from showme.engine.data_sources.news.rss_adapter import _parse_feed

    articles: list[dict[str, Any]] = []
    for iso in isos:
        term = country_query_term(iso)
        url = (
            f"{_GOOGLE_NEWS_URL}?q={term.replace(' ', '+')}"
            "&hl=en-US&gl=US&ceid=US:en"
        )
        cached = _GOOGLE_NEWS_CACHE.get(iso)
        if cached and (time.monotonic() - cached[0]) < _GOOGLE_NEWS_TTL_S:
            items, note = cached[1], cached[2]
        else:
            items, note = [], None
            try:
                response = await client.get(url, timeout=_GOOGLE_NEWS_TIMEOUT_S)
                response.raise_for_status()
                items = [
                    a for a in _parse_feed(response.text, url)
                    if str(a.get("title") or "").strip()
                ][:limit]
                if not items:
                    note = f"google_news {iso}: empty feed"
            except Exception as exc:  # noqa: BLE001 - gate is best-effort
                note = f"google_news {iso}: {str(exc) or exc.__class__.__name__}"
            _GOOGLE_NEWS_CACHE[iso] = (time.monotonic(), list(items), note)
        if note:
            status["notes"].append(note)
        if items:
            status["countries"].append(iso)
            articles.extend(items)
    status["rows_added"] = len(articles)
    status["fired"] = bool(articles)
    return articles, status


def gate_window_counts(
    rows: list[dict[str, Any]],
    countries: list[str],
    *,
    now: datetime,
    window_days: float = MEET_GATE_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Past/future event counts per followed country inside the 7-day window."""
    window_s = window_days * 86400.0
    isos: list[str] = []
    for token in countries:
        iso = we.canonical_iso(token) or str(token).strip().upper()
        if iso and iso not in isos:
            isos.append(iso)
    counts: dict[str, dict[str, int]] = {
        iso: {"past": 0, "future": 0} for iso in isos
    }
    for row in rows:
        row_isos = {str(c).upper() for c in (row.get("countries") or [])}
        seconds = float(row.get("seconds_to_event") or 0)
        is_past = bool(row.get("undated")) or seconds < 0
        for iso in isos:
            if iso not in row_isos:
                continue
            if is_past and (bool(row.get("undated")) or -seconds <= window_s):
                counts[iso]["past"] += 1
            elif not is_past and seconds <= window_s:
                counts[iso]["future"] += 1
    report: list[dict[str, Any]] = []
    for iso in isos:
        past = counts[iso]["past"]
        future = counts[iso]["future"]
        report.append({
            "iso": iso,
            "name": we.country_name(iso),
            "past_7d": past,
            "future_7d": future,
            "past_met": past >= MEET_GATE_MIN_EVENTS,
            "future_met": future >= MEET_GATE_MIN_EVENTS,
        })
    return report


def shortfall_warnings(report: list[dict[str, Any]]) -> list[str]:
    """Explicit warnings for followed countries the gates could not fill."""
    out: list[str] = []
    for entry in report:
        if not entry.get("past_met"):
            out.append(
                f"gate shortfall: {entry.get('iso')} past {MEET_GATE_WINDOW_DAYS:.0f}d "
                f"has {entry.get('past_7d')}/{MEET_GATE_MIN_EVENTS} events "
                "(wire gates exhausted; nothing invented)"
            )
        if not entry.get("future_met"):
            out.append(
                f"gate shortfall: {entry.get('iso')} future {MEET_GATE_WINDOW_DAYS:.0f}d "
                f"has {entry.get('future_7d')}/{MEET_GATE_MIN_EVENTS} events "
                "(no keyless scheduled provider covers this country beyond holidays)"
            )
    return out


__all__ = [
    "MEET_GATE_MIN_EVENTS",
    "MEET_GATE_WINDOW_DAYS",
    "country_query_term",
    "country_wire_articles",
    "gate_window_counts",
    "google_news_articles",
    "holiday_gate_rows",
    "shortfall_warnings",
]
