"""ECO — Economic Calendar."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

_FOREX_FACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
# ForexFactory publishes a weekly snapshot; 30 minutes keeps us polite and
# fresh enough for a calendar pane without hammering the keyless endpoint.
_FOREX_FACTORY_TTL_S = 1800.0
_ff_cache: dict[str, Any] = {"fetched_at": 0.0, "rows": []}

# ForexFactory tags rows by currency; the calendar's canonical country
# tokens (see _COUNTRY_ALIASES below) use ISO-ish region codes.
_CURRENCY_TO_COUNTRY: dict[str, str] = {
    "USD": "US", "EUR": "EU", "GBP": "UK", "JPY": "JP", "CHF": "CH",
    "CAD": "CA", "AUD": "AU", "NZD": "NZ", "CNY": "CN", "TRY": "TR",
}


@FunctionRegistry.register
class ECOFunction(BaseFunction):
    code = "ECO"
    name = "Economic Calendar"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = params.get("country")
        importance = params.get("importance")
        days = _int_param(params.get("days"), default=30, floor=1, ceiling=180)
        events: list = []
        provider_errors: list[str] = []
        # Default-polarity flip (2026-09-08): ECO serves real calendar
        # feeds by default (tradingeconomics → finnhub → keyless
        # ForexFactory weekly JSON). ``reference=true`` serves the
        # labelled illustrative schedule template. When every live
        # provider fails the payload is an honest empty/error state — the
        # invented calendar is NEVER shown at HTTP 200 unlabelled.
        reference = _truthy(params.get("reference"))
        source_mode = "calendar_feed_model"

        if reference:
            events = _calendar_feed_model(country, importance)

        if not reference and self.deps.tradingeconomics:
            try:
                events = await asyncio.wait_for(
                    self.deps.tradingeconomics.calendar(
                        country=country,
                        importance=importance,
                    ),
                    timeout=float(params.get("timeout", 8)),
                )
                if events:
                    source_mode = "tradingeconomics"
            except Exception as exc:
                provider_errors.append(f"tradingeconomics: {exc}")

        if not reference and not events and self.deps.finnhub:
            try:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                end_str = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
                events = await asyncio.wait_for(
                    self.deps.finnhub.economic_calendar(
                        start=today_str,
                        end=end_str,
                    ),
                    timeout=float(params.get("timeout", 8)),
                )
                if events:
                    source_mode = "finnhub"
            except Exception as exc:
                provider_errors.append(f"finnhub: {exc}")

        if not reference and not events:
            try:
                ff_events = await _forex_factory_events(
                    client=await self._client(),
                    timeout=max(2.0, min(float(params.get("timeout", 8)), 12.0)),
                )
                if ff_events:
                    events = ff_events
                    source_mode = "forex_factory"
            except Exception as exc:  # noqa: BLE001 - provider error is surfaced in warnings
                provider_errors.append(f"forex_factory: {exc}")

        if not events and not reference:
            # H-3 honesty fix: no invented calendar at HTTP 200. Every
            # live provider failed, so the pane gets an honest
            # provider_unavailable envelope instead of synthetic rows.
            reason = "No economic-calendar provider responded (tradingeconomics, finnhub, forex_factory)."
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": reason,
                    "events": [],
                    "rows": [],
                    "surface": [],
                    "cards": [
                        {"label": "Events", "value": 0},
                        {"label": "Country", "value": country or "ALL"},
                        {"label": "Importance", "value": importance or "ALL"},
                    ],
                    "next_actions": [
                        "Retry once the network or calendar providers recover.",
                        "Set TRADINGECONOMICS_API_KEY or FINNHUB_API_KEY for the keyed calendar feeds.",
                        "Pass reference=true to inspect the labelled illustrative schedule template.",
                    ],
                    "methodology": (
                        "ECO filters economic calendar events by country, importance, and forward date window. "
                        "When no live calendar provider responds, no schedule is shown at all rather than an "
                        "invented one."
                    ),
                    "field_dictionary": {
                        "date": "Scheduled event date.",
                        "importance": "Provider impact bucket.",
                        "forecast": "Consensus estimate when available.",
                        "actual": "Released value when available.",
                        "surprise": "Actual minus forecast.",
                    },
                    "source_mode": "provider_unavailable",
                    "as_of": datetime.now(timezone.utc).isoformat(),
                },
                sources=["no_live_source"],
                warnings=provider_errors + [reason],
                metadata={"country": country, "importance": importance, "days": days,
                          # R2 C-1: a failed live ATTEMPT is not a live claim.
                          # ``live=True`` here used to ride the sanitizer's
                          # metadata voucher to a LIVE pill on an empty
                          # provider_unavailable envelope.
                          "live": False, "fallback": True,
                          "data_mode": "provider_unavailable"},
            )

        rows = _normalize_events(events, country=country, importance=importance, days=days)
        for row in rows:
            row.setdefault("source_mode", source_mode)
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "events": rows,
                "rows": rows,
                "surface": _importance_surface(rows),
                "cards": [
                    {"label": "Events", "value": len(rows)},
                    {"label": "Country", "value": country or "ALL"},
                    {"label": "Importance", "value": importance or "ALL"},
                ],
                "methodology": (
                    "ECO filters economic calendar events by country, importance, and forward date window. "
                    "Surprise is actual minus forecast when both values exist; blank actual/forecast fields "
                    "mean the event has not printed or the provider did not supply estimates."
                ),
                "field_dictionary": {
                    "date": "Scheduled event date.",
                    "importance": "Provider impact bucket.",
                    "forecast": "Consensus estimate when available.",
                    "actual": "Released value when available.",
                    "surprise": "Actual minus forecast.",
                },
                "source_mode": source_mode,
                # Machine-readable freshness so the UI shows REAL data age
                # (server fetch time), not the client render clock.
                "as_of": datetime.now(timezone.utc).isoformat(),
            },
            sources=[source_mode],
            warnings=provider_errors,
            metadata={
                "country": country,
                "importance": importance,
                "days": days,
                "live": not reference,
                "data_mode": "modeled" if reference else f"live_{source_mode}",
            },
        )

    async def _client(self) -> Any:
        """Resolve an httpx-like async client (shared keyless pool).

        Resolution order: an explicitly injected ``self._http_client``
        (used by tests), then ``self.deps.http`` if a host wired one,
        then the shared keyless httpx pool.
        """
        injected = getattr(self, "_http_client", None)
        if injected is not None:
            return injected
        deps = getattr(self, "deps", None)
        http = getattr(deps, "http", None) if deps is not None else None
        if http is not None:
            return http
        from showme.providers._http import get_client

        return await get_client()


async def _forex_factory_events(*, client: Any, timeout: float) -> list[dict[str, Any]]:
    """Fetch the keyless ForexFactory weekly calendar JSON (with TTL cache).

    The endpoint returns a JSON array of that week's events with
    country/impact/actual/forecast/prior fields. Rows are normalized into
    the calendar schema used by ``_normalize_events``.
    """
    now = time.monotonic()
    cached = _ff_cache.get("rows") or []
    if cached and (now - float(_ff_cache.get("fetched_at") or 0.0)) < _FOREX_FACTORY_TTL_S:
        return list(cached)
    try:
        resp = await client.get(_FOREX_FACTORY_URL, timeout=timeout)
    except TypeError:
        # Minimal test fakes may not accept a per-request timeout.
        resp = await client.get(_FOREX_FACTORY_URL)
    resp.raise_for_status()
    raw = resp.json()
    rows = _normalize_ff_rows(raw)
    if rows:
        _ff_cache["fetched_at"] = now
        _ff_cache["rows"] = list(rows)
    return list(rows)


def _normalize_ff_rows(raw: Any) -> list[dict[str, Any]]:
    """Normalize the ForexFactory weekly JSON into calendar-event dicts."""
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        currency = str(item.get("country") or "").strip().upper()
        rows.append({
            "country": _CURRENCY_TO_COUNTRY.get(currency, currency),
            "event": title,
            "date": str(item.get("date") or "").strip(),
            "importance": str(item.get("impact") or "medium").strip().lower() or "medium",
            "forecast": item.get("forecast") or None,
            "actual": item.get("actual") or None,
            "previous": item.get("previous") or None,
            "forecast_raw": item.get("forecast"),
            "actual_raw": item.get("actual"),
            "previous_raw": item.get("previous"),
            "unit": "",
        })
    return rows


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _calendar_feed_model(country: str | None, importance: str | None) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    raw_events = [
        # --- US ---
        {"country": "US", "event": "FOMC Interest Rate Decision", "offset": -2, "importance": "high", "forecast": 4.5, "actual": 4.5, "previous": 4.75, "unit": "%"},
        {"country": "US", "event": "Non Farm Payrolls", "offset": -1, "importance": "high", "forecast": 180, "actual": 210, "previous": 175, "unit": "K"},
        {"country": "US", "event": "Unemployment Rate", "offset": -1, "importance": "high", "forecast": 3.9, "actual": 3.8, "previous": 3.9, "unit": "%"},
        {"country": "US", "event": "CPI MoM", "offset": 0, "importance": "high", "forecast": 0.2, "actual": 0.3, "previous": 0.1, "unit": "%"},
        {"country": "US", "event": "CPI YoY", "offset": 0, "importance": "high", "forecast": 3.1, "actual": 3.2, "previous": 3.0, "unit": "%"},
        {"country": "US", "event": "Initial Jobless Claims", "offset": 2, "importance": "low", "forecast": 215, "actual": None, "previous": 220, "unit": "K"},
        {"country": "US", "event": "Retail Sales MoM", "offset": 4, "importance": "medium", "forecast": 0.3, "actual": None, "previous": 0.1, "unit": "%"},
        {"country": "US", "event": "PPI MoM", "offset": 5, "importance": "medium", "forecast": 0.1, "actual": None, "previous": 0.2, "unit": "%"},
        {"country": "US", "event": "GDP Growth Rate QoQ (Est)", "offset": 10, "importance": "high", "forecast": 2.1, "actual": None, "previous": 1.8, "unit": "%"},
        {"country": "US", "event": "S&P Global Manufacturing PMI", "offset": 15, "importance": "medium", "forecast": 50.5, "actual": None, "previous": 49.9, "unit": ""},
        {"country": "US", "event": "Michigan Consumer Sentiment", "offset": 20, "importance": "low", "forecast": 72.5, "actual": None, "previous": 70.2, "unit": ""},

        # --- EU ---
        {"country": "EU", "event": "ECB Interest Rate Decision", "offset": -3, "importance": "high", "forecast": 3.75, "actual": 3.5, "previous": 3.75, "unit": "%"},
        {"country": "EU", "event": "Inflation Rate YoY (Flash)", "offset": -1, "importance": "high", "forecast": 2.4, "actual": 2.4, "previous": 2.6, "unit": "%"},
        {"country": "EU", "event": "Unemployment Rate", "offset": 1, "importance": "medium", "forecast": 6.5, "actual": None, "previous": 6.5, "unit": "%"},
        {"country": "EU", "event": "GDP Growth Rate QoQ (Flash)", "offset": 3, "importance": "high", "forecast": 0.2, "actual": None, "previous": 0.1, "unit": "%"},
        {"country": "EU", "event": "ZEW Economic Sentiment Index", "offset": 6, "importance": "medium", "forecast": 43.0, "actual": None, "previous": 42.9, "unit": ""},
        {"country": "EU", "event": "Industrial Production MoM", "offset": 12, "importance": "low", "forecast": 0.5, "actual": None, "previous": -0.2, "unit": "%"},
        {"country": "EU", "event": "HCOB Eurozone Manufacturing PMI", "offset": 18, "importance": "medium", "forecast": 47.2, "actual": None, "previous": 47.3, "unit": ""},

        # --- UK ---
        {"country": "UK", "event": "BoE Interest Rate Decision", "offset": -2, "importance": "high", "forecast": 5.0, "actual": 5.0, "previous": 5.25, "unit": "%"},
        {"country": "UK", "event": "Inflation Rate YoY", "offset": 0, "importance": "high", "forecast": 2.1, "actual": 2.0, "previous": 2.3, "unit": "%"},
        {"country": "UK", "event": "Unemployment Rate (3M)", "offset": 2, "importance": "medium", "forecast": 4.3, "actual": None, "previous": 4.2, "unit": "%"},
        {"country": "UK", "event": "GDP Growth Rate MoM", "offset": 5, "importance": "high", "forecast": 0.1, "actual": None, "previous": 0.2, "unit": "%"},
        {"country": "UK", "event": "Retail Sales MoM", "offset": 8, "importance": "medium", "forecast": -0.3, "actual": None, "previous": 0.5, "unit": "%"},
        {"country": "UK", "event": "S&P Global Services PMI", "offset": 14, "importance": "medium", "forecast": 52.9, "actual": None, "previous": 53.1, "unit": ""},

        # --- TR ---
        {"country": "TR", "event": "TCMB Interest Rate Decision", "offset": -4, "importance": "high", "forecast": 45.0, "actual": 45.0, "previous": 45.0, "unit": "%"},
        {"country": "TR", "event": "Inflation Rate YoY (CPI)", "offset": -1, "importance": "high", "forecast": 68.2, "actual": 69.8, "previous": 67.1, "unit": "%"},
        {"country": "TR", "event": "Unemployment Rate", "offset": 1, "importance": "medium", "forecast": 8.7, "actual": None, "previous": 8.8, "unit": "%"},
        {"country": "TR", "event": "Industrial Production YoY", "offset": 3, "importance": "medium", "forecast": 2.1, "actual": None, "previous": 1.3, "unit": "%"},
        {"country": "TR", "event": "GDP Growth Rate YoY", "offset": 7, "importance": "high", "forecast": 4.0, "actual": None, "previous": 4.5, "unit": "%"},
        {"country": "TR", "event": "Current Account Balance", "offset": 11, "importance": "medium", "forecast": -2.1, "actual": None, "previous": -1.8, "unit": "B USD"},
        {"country": "TR", "event": "Retail Sales YoY", "offset": 16, "importance": "low", "forecast": 9.5, "actual": None, "previous": 10.2, "unit": "%"},
    ]
    events = []
    for item in raw_events:
        event_date = today + timedelta(days=item["offset"])
        events.append({
            "country": item["country"],
            "event": item["event"],
            "date": event_date.isoformat(),
            "importance": item["importance"],
            "forecast": item["forecast"],
            # Honesty: never emit fabricated printed values from the synthetic
            # template. We show the SCHEDULE (forecast/previous as illustrative
            # context) but the `actual` print is always blank so a sample
            # calendar is never mistaken for real releases.
            "actual": None,
            "previous": item["previous"],
            "unit": item["unit"],
        })
    return events



# S05 BUGHUNT B4: trading-economics tags UK/EU/JP events with ISO 3166 alpha-2
# codes ("UK", "EU", "JP") AND human-readable forms ("United Kingdom",
# "European Union", "Japan"); the UI's SegmentedControl meanwhile defaults to
# "GB"/"EZ" etc. Without a canonical normalisation, picking "UK" silently
# drops every live row whose `country` field reads "United Kingdom". The map
# folds known aliases onto a single canonical token before equality matching.
_COUNTRY_ALIASES: dict[str, str] = {
    "GB": "UK", "GBR": "UK", "UK": "UK", "UNITED KINGDOM": "UK", "BRITAIN": "UK",
    "EZ": "EU", "EUR": "EU", "EU": "EU", "EUROZONE": "EU", "EUROPEAN UNION": "EU", "EMU": "EU",
    "US": "US", "USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US",
    "JP": "JP", "JPN": "JP", "JAPAN": "JP",
    "DE": "DE", "DEU": "DE", "GERMANY": "DE",
    "FR": "FR", "FRA": "FR", "FRANCE": "FR",
    "TR": "TR", "TUR": "TR", "TURKEY": "TR", "TÜRKIYE": "TR", "TURKIYE": "TR",
    "CN": "CN", "CHN": "CN", "CHINA": "CN",
    "IN": "IN", "IND": "IN", "INDIA": "IN",
    "BR": "BR", "BRA": "BR", "BRAZIL": "BR",
}


def _canonical_country(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    return _COUNTRY_ALIASES.get(raw, raw)


def _normalize_events(events: list[Any], *, country: Any, importance: Any, days: int) -> list[dict[str, Any]]:
    start = datetime.now(timezone.utc).date() - timedelta(days=1)
    end = start + timedelta(days=days + 1)
    wanted_country = _canonical_country(country)
    wanted_importance = str(importance or "").lower()
    rows: list[dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        row = {str(k).lower(): v for k, v in raw.items()}
        event_country = _canonical_country(row.get("country") or row.get("region"))
        event_importance = str(row.get("importance") or row.get("impact") or "").lower()
        if wanted_country and event_country and event_country != wanted_country:
            continue
        if wanted_importance and wanted_importance != "all" and event_importance and wanted_importance not in event_importance:
            continue
        date_text = str(row.get("date") or row.get("datetime") or row.get("time") or "")
        event_date = _parse_date(date_text)
        if event_date and not (start <= event_date <= end):
            continue
        forecast, _, _ = _parse_ff_number(row.get("forecast"))
        actual, _, _ = _parse_ff_number(row.get("actual"))
        previous, _, _ = _parse_ff_number(row.get("previous"))
        rows.append({
            "date": event_date.isoformat() if event_date else date_text[:16],
            "country": event_country or (wanted_country or "US"),
            "event": row.get("event") or row.get("name") or row.get("title") or "Economic event",
            "importance": row.get("importance") or row.get("impact") or "medium",
            "forecast": forecast,
            "actual": actual,
            "previous": previous,
            "surprise": round(actual - forecast, 6) if actual is not None and forecast is not None else None,
            "unit": row.get("unit") or "",
        })
    return sorted(rows, key=lambda item: str(item.get("date") or ""))


def _importance_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("importance") or "unknown").lower()
        counts[key] = counts.get(key, 0) + 1
    return [{"importance": key, "value": value} for key, value in sorted(counts.items())]


def _parse_date(value: str) -> Any:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


_FF_MULTIPLIERS: dict[str, float] = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}

_SCORE_RE = re.compile(r"^\d+-\d+-\d+$")


def _parse_ff_number(raw: Any) -> tuple[float | None, str, bool]:
    """Parse a ForexFactory numeric cell into ``(value, unit, capped)``.

    Preserves the legacy ``%``/``,`` stripping, then applies ``K/M/B/T``
    multipliers. A leading ``<`` is stripped and reported via
    ``capped=True``. When the cell contains ``|`` only the part before it
    is parsed. Score-like strings (``3-0-6``) are not numbers and yield
    ``(None, raw, False)``.
    """
    if raw is None:
        return (None, "", False)
    if isinstance(raw, bool):
        return (None, str(raw), False)
    if isinstance(raw, (int, float)):
        try:
            return (round(float(raw), 6), "", False)
        except (ValueError, OverflowError):
            return (None, str(raw), False)
    text = str(raw).strip()
    if not text:
        return (None, "", False)
    if "|" in text:
        text = text.split("|", 1)[0].strip()
        if not text:
            return (None, str(raw).strip(), False)
    capped = False
    work = text
    if work.startswith("<"):
        capped = True
        work = work[1:].strip()
    if _SCORE_RE.fullmatch(work):
        return (None, work, False)
    has_percent = "%" in work
    cleaned = work.replace("%", "").replace(",", "").strip()
    if not cleaned:
        return (None, text, capped)
    suffix = ""
    multiplier = 1.0
    if cleaned[-1] in "KMBTkmbt":
        suffix = cleaned[-1].upper()
        multiplier = _FF_MULTIPLIERS[suffix]
        cleaned = cleaned[:-1].strip()
        if not cleaned:
            return (None, text, capped)
    try:
        value = round(float(cleaned) * multiplier, 6)
    except ValueError:
        return (None, text, capped)
    if has_percent:
        unit = "%"
    elif suffix:
        unit = suffix
    else:
        unit = ""
    return (value, unit, capped)


def _num(value: Any) -> float | None:
    value_parsed, _, _ = _parse_ff_number(value)
    return value_parsed


def _int_param(value: Any, *, default: int, floor: int, ceiling: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(floor, min(ceiling, parsed))
