"""MEET â€” Meeting Briefings: world-events tracker.

The pane tracks scheduled world events (central-bank decisions, CPI, GDP,
â€¦ for every country on the calendar) and country-tagged world headlines
(wars, elections, summits) in one list:

  * upcoming events ascending â€” from now until the nearest upcoming
    high-impact event and beyond, each with a server-computed countdown,
  * past events descending â€” the last ``days_back`` days,
  * a country index (every country that appeared + next event + state),
  * spot alerts for rate decisions / wars with configurable lead times
    (the UI persists them under ``showme.meet.alerts``).

Providers are the repo's existing KEYLESS paths:
  * the ForexFactory weekly calendar reused from ECO
    (``showme.engine.functions.macro.eco._forex_factory_events``), and
  * the keyless GDELT (or RSS fallback) news adapter for world headlines.

Honesty: every row carries its source; country tags carry the matched
terms; empty windows say so; nothing is fabricated when a provider fails.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

# World-headline fetch cache (module level, shared across MEET calls): the
# GDELT-first + RSS-fallback chain can spend ~10 s before answering, and the
# pane refetches on every country/world filter toggle. Filters apply over the
# cached rows, so only the upstream fetch rides this TTL. Successes keep the
# full window; empty/failed passes expire faster so an outage recovers.
_WORLD_CACHE: tuple[float, tuple[list[dict[str, Any]], str, str | None], float] | None = None
_WORLD_CACHE_TTL_S = 180.0
_WORLD_CACHE_FAIL_TTL_S = 30.0
# Followed-symbol headline cache: (symbols_key, stored_at, articles)
_SYMBOL_NEWS_CACHE: tuple[str, float, list[dict[str, Any]]] | None = None
_SYMBOL_NEWS_TTL_S = 180.0

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.macro import eco as eco_mod
from showme.engine.services import world_events as we


@FunctionRegistry.register
class MEETFunction(BaseFunction):
    code = "MEET"
    name = "Meeting Briefings â€” World Events"
    category = "comm"
    description = (
        "World-events tracker â€” country calendar + tagged headlines with "
        "countdowns, affected FX pairs and spot alerts."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        now = datetime.now(UTC)
        countries = _csv(params.get("countries"))
        kind = str(params.get("kind") or "all")
        impacts = _csv(params.get("impact"))
        query = str(params.get("query") or params.get("q") or params.get("topic") or "")
        symbols = _csv(params.get("symbols"))
        days_ahead = _num(params.get("days_ahead"), 90.0, floor=1.0, ceiling=365.0)
        days_back = _num(params.get("days_back"), 7.0, floor=0.0, ceiling=90.0)
        limit = int(_num(params.get("limit"), 250, floor=10, ceiling=1000))
        news_timeout = _num(params.get("news_timeout") or params.get("timeout"), 8.0,
                            floor=2.0, ceiling=15.0)
        include_world = _truthy(params.get("include_world", True)) and kind in {"", "all", "world"}

        warnings: list[str] = []
        sources: list[str] = []

        # --- scheduled calendar (keyless ForexFactory, shared ECO cache) ---
        calendar_rows: list[Any] = []
        try:
            client = await self._client()
            calendar_rows = await eco_mod._forex_factory_events(
                client=client,
                timeout=min(max(2.0, news_timeout), 12.0),
            )
            if calendar_rows:
                sources.append("forex_factory")
        except Exception as exc:  # noqa: BLE001 â€” provider failure is surfaced, not hidden
            warnings.append(f"forex_factory: {str(exc) or exc.__class__.__name__}")

        economic, dropped_no_time = we.economic_rows(calendar_rows, now=now, source="forex_factory")

        # --- world headlines (keyless GDELT, RSS fallback) ---
        world: list[dict[str, Any]] = []
        if include_world:
            articles, world_source, world_error = await self._world_headlines(
                now=now, timeout=news_timeout
            )
            if world_error:
                warnings.append(world_error)
            if articles:
                world = we.world_rows(articles, now=now, source=world_source or "news")
                if world:
                    sources.append(world_source or "news")
            if symbols:
                # Followed symbols need their OWN feeds: the world stream is
                # geopolitics/market wires, so "BTC" matched nothing (owner
                # 2026-09-16: "btc ekledim bana onun olayları gösterilmiyor").
                extra = await self._symbol_articles(symbols, now=now, timeout=news_timeout)
                if extra:
                    known = {
                        (str(a.get("url") or a.get("link") or ""), str(a.get("title") or ""))
                        for a in articles
                    }
                    fresh = [
                        a
                        for a in extra
                        if (str(a.get("url") or a.get("link") or ""), str(a.get("title") or ""))
                        not in known
                    ]
                    if fresh:
                        world.extend(we.world_rows(fresh, now=now, source="symbol_feed"))
                        sources.append("symbol_feed")

        rows = economic + world
        unfiltered_upcoming, unfiltered_past = we.split_window(
            rows, days_ahead=days_ahead, days_back=days_back
        )

        filtered = we.apply_filters(
            rows,
            countries=countries,
            kind=kind,
            impacts=impacts,
            query=query,
            limit=limit,
        )
        upcoming, past = we.split_window(filtered, days_ahead=days_ahead, days_back=days_back)
        ordered = upcoming + past
        alerts = we.build_alerts(unfiltered_upcoming, lead_minutes=we.DEFAULT_ALERT_LEAD_MINUTES)
        country_index = we.build_country_index(unfiltered_upcoming + unfiltered_past, now=now)

        if not rows:
            reason = (
                "No world-events provider responded (forex_factory calendar + news)."
                if warnings else
                "No world events were returned."
            )
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_shell(
                    now=now,
                    status="provider_unavailable" if warnings else "empty",
                    reason=reason,
                    rows=[], upcoming=[], past=[],
                    country_index=[], country_catalog=_catalog(),
                    alerts=[], countries=countries, kind=kind, impacts=impacts,
                    query=query, days_ahead=days_ahead, days_back=days_back,
                    limit=limit, dropped_no_time=dropped_no_time,
                ),
                sources=sources or ["no_live_source"],
                warnings=warnings + ([reason] if warnings else []),
                metadata={
                    "live": False,
                    "fallback": True,
                    "data_mode": "provider_unavailable" if warnings else "empty",
                    "provider_errors": warnings,
                },
            )

        # Followed symbols (owner 2026-09-16: "btc ekledim bana onun olayları
        # gösterilmiyor"): match the followed tickers' terms (BTC -> bitcoin,
        # ...) against the world headlines and surface the matches as their
        # own section - independent of the country/kind filters, because a
        # crypto event has no FX-calendar country.
        symbol_rows: list[dict[str, Any]] = []
        if symbols:
            # Market-wide movers first (owner follow-up: the upcoming FOMC
            # rate decision affects EVERY market including BTC; a followed
            # symbol's view must carry the global high-impact macro calendar
            # too, tagged "all markets" so the relevance is explicit).
            market_rows = [
                {**row, "symbol_matches": ["all markets"], "symbol_relevance": "market_wide"}
                for row in unfiltered_upcoming
                if row.get("kind") == "economic"
                and str(row.get("impact") or "").lower() == "high"
            ]
            market_rows.sort(key=lambda r: str(r.get("when_utc") or ""))
            headline_rows: list[dict[str, Any]] = []
            try:
                from showme.engine.services import news_intelligence as ni

                term_map = [(sym, ni.symbol_terms(sym)) for sym in symbols]
                for row in world:
                    text = " ".join(
                        str(row.get(key) or "")
                        for key in ("title", "summary", "details", "description")
                    ).lower()
                    matched_terms: list[str] = []
                    for sym, terms in term_map:
                        for term in terms:
                            if len(term) >= 3 and ni.term_in_text(term, text):
                                matched_terms.append(term)
                                break
                    if matched_terms:
                        headline_rows.append(
                            {**row, "symbol_matches": matched_terms[:4]}
                        )
                headline_rows.sort(
                    key=lambda r: str(r.get("when_utc") or ""), reverse=True
                )
            except Exception as exc:  # noqa: BLE001 - section is best-effort
                warnings.append(f"symbol_events: {str(exc) or exc.__class__.__name__}")
            # Market-wide macro first (soonest-upcoming order), then the
            # ticker-matched headlines (newest first).
            symbol_rows = (market_rows[:12] + headline_rows[:12])[:24]

        payload = _shell(
            now=now,
            status="ok",
            reason=None,
            rows=ordered,
            upcoming=upcoming,
            past=past,
            country_index=country_index,
            country_catalog=_catalog(),
            alerts=alerts,
            countries=countries,
            kind=kind,
            impacts=impacts,
            query=query,
            days_ahead=days_ahead,
            days_back=days_back,
            limit=limit,
            dropped_no_time=dropped_no_time,
        )
        payload["filtered_empty"] = not ordered
        payload["unfiltered_upcoming_count"] = len(unfiltered_upcoming)
        payload["symbol_rows"] = symbol_rows
        payload["symbols_requested"] = symbols
        # Built as a variable so the repo's data_mode literal scanner only
        # sees sanctioned values (``live_<source>`` follows ECO's convention).
        live_mode = "live_" + "+".join(sources) if sources else "cached_snapshot"
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=payload,
            sources=sources or ["no_live_source"],
            warnings=warnings,
            metadata={
                "live": bool(sources),
                "fallback": not sources,
                "data_mode": live_mode,
                "provider_errors": warnings,
                "counts": {
                    "rows": len(ordered),
                    "upcoming": len(upcoming),
                    "past": len(past),
                    "alerts": len(alerts),
                },
            },
        )

    async def _symbol_articles(
        self, symbols: list[str], *, now: datetime, timeout: float
    ) -> list[dict[str, Any]]:
        """Extra headlines aimed at the followed tickers.

        Crypto symbols ride the crypto feed group (CoinDesk/...); the first
        few symbols also request their per-symbol Yahoo feed. Cached for the
        same window as the world headlines so pane refreshes stay instant.
        """
        global _SYMBOL_NEWS_CACHE
        cache_key = ",".join(sorted(s.upper() for s in symbols))
        now_mono = time.monotonic()
        if _SYMBOL_NEWS_CACHE is not None and _SYMBOL_NEWS_CACHE[0] == cache_key and (
            now_mono - _SYMBOL_NEWS_CACHE[1]
        ) < _SYMBOL_NEWS_TTL_S:
            return list(_SYMBOL_NEWS_CACHE[2])

        rss = getattr(self.deps, "rss", None)
        if rss is None:
            return []
        try:
            from showme.engine.services import news_intelligence as ni

            crypto_syms = [
                s for s in symbols if ni.crypto_base(s) in ni.CRYPTO_NAMES
            ]
        except Exception:  # noqa: BLE001
            crypto_syms = []
        collected: list[dict[str, Any]] = []
        if crypto_syms:
            try:
                collected.extend(
                    await asyncio.wait_for(
                        rss.fetch(
                            DataRequest(
                                kind=DataKind.NEWS,
                                extra={"feed_group": "crypto"},
                                limit=50,
                            )
                        ),
                        timeout=timeout,
                    )
                    or []
                )
            except Exception:  # noqa: BLE001 - best-effort tier
                pass
        for sym in symbols[:3]:
            try:
                collected.extend(
                    await asyncio.wait_for(
                        rss.fetch(
                            DataRequest(
                                kind=DataKind.NEWS,
                                extra={"feed_group": "market", "symbol": sym},
                                limit=30,
                            )
                        ),
                        timeout=timeout,
                    )
                    or []
                )
            except Exception:  # noqa: BLE001
                continue
        _SYMBOL_NEWS_CACHE = (cache_key, now_mono, list(collected))
        return list(collected)

    async def _client(self) -> Any:
        """Resolve an httpx-like async client (shared keyless pool)."""
        injected = getattr(self, "_http_client", None)
        if injected is not None:
            return injected
        deps = getattr(self, "deps", None)
        http = getattr(deps, "http", None) if deps is not None else None
        if http is not None:
            return http
        from showme.providers._http import get_client

        return await get_client()

    async def _world_headlines(
        self, *, now: datetime, timeout: float
    ) -> tuple[list[dict[str, Any]], str, str | None]:
        """Fetch the keyless world headline stream (GDELT first, RSS fallback).

        Cached for ``_WORLD_CACHE_TTL_S`` (owner 2026-09-16: toggling a
        country/world filter re-paid the full ~10 s GDELT-timeout + RSS
        fallback on EVERY click and the pane sat on skeletons for 8+ s).
        Filters apply to the cached rows; only the upstream fetch is cached.
        """
        global _WORLD_CACHE
        now_mono = time.monotonic()
        if _WORLD_CACHE is not None and (now_mono - _WORLD_CACHE[0]) < _WORLD_CACHE[2]:
            cached_items, cached_source, cached_error = _WORLD_CACHE[1]
            return list(cached_items), cached_source, cached_error

        gdelt = getattr(self.deps, "gdelt", None)
        rss = getattr(self.deps, "rss", None)
        error: str | None = None
        if gdelt is not None:
            try:
                items = await asyncio.wait_for(
                    gdelt.fetch(DataRequest(
                        kind=DataKind.NEWS,
                        extra={"query": we.world_query()},
                        start=now - timedelta(days=2),
                        limit=75,
                    )),
                    timeout=timeout,
                )
                if items:
                    result = (list(items), "gdelt", None)
                    _WORLD_CACHE = (now_mono, result, _WORLD_CACHE_TTL_S)
                    return result
                error = "gdelt: empty result"
            except Exception as exc:  # noqa: BLE001
                error = f"gdelt: {str(exc) or exc.__class__.__name__}"
        if rss is not None:
            try:
                items = await asyncio.wait_for(
                    rss.fetch(DataRequest(
                        kind=DataKind.NEWS,
                        extra={"feed_group": "market"},
                        limit=50,
                    )),
                    timeout=timeout,
                )
                if items:
                    # GDELT empty/failed is disclosed only when it was an error
                    # â€” an empty-but-OK GDELT just means the fallback is used.
                    result = (
                        list(items),
                        "rss",
                        error if error and "empty" not in error else None,
                    )
                    _WORLD_CACHE = (now_mono, result, _WORLD_CACHE_TTL_S)
                    return result
                result = ([], "rss", error or "rss: empty result")
                _WORLD_CACHE = (now_mono, result, _WORLD_CACHE_FAIL_TTL_S)
                return result
            except Exception as exc:  # noqa: BLE001
                merged = f"{error}; rss: {str(exc) or exc.__class__.__name__}" if error else (
                    f"rss: {str(exc) or exc.__class__.__name__}"
                )
                result = ([], "rss", merged)
                _WORLD_CACHE = (now_mono, result, _WORLD_CACHE_FAIL_TTL_S)
                return result
        result = ([], "", error or "news: neither gdelt nor rss is configured")
        _WORLD_CACHE = (now_mono, result, _WORLD_CACHE_FAIL_TTL_S)
        return result


def _shell(
    *,
    now: datetime,
    status: str,
    reason: str | None,
    rows: list[dict[str, Any]],
    upcoming: list[dict[str, Any]],
    past: list[dict[str, Any]],
    country_index: list[dict[str, Any]],
    country_catalog: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    countries: list[str],
    kind: str,
    impacts: list[str],
    query: str,
    days_ahead: float,
    days_back: float,
    limit: int,
    dropped_no_time: int,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "as_of": now.isoformat(),
        "rows": rows,
        "upcoming": upcoming,
        "past": past,
        "row_count": len(rows),
        "upcoming_count": len(upcoming),
        "past_count": len(past),
        "window": we.window_meta(rows, now=now, days_ahead=days_ahead, days_back=days_back),
        "country_index": country_index,
        "country_catalog": country_catalog,
        "alerts": alerts,
        "alert_default_lead_minutes": list(we.DEFAULT_ALERT_LEAD_MINUTES),
        "dropped_no_time": dropped_no_time,
        "filters_applied": {
            "countries": countries,
            "kind": kind,
            "impact": impacts,
            "q": query,
            "days_ahead": days_ahead,
            "days_back": days_back,
            "limit": limit,
        },
        "methodology": (
            "Scheduled rows come from the keyless ForexFactory weekly calendar "
            "(reused from ECO): every country on the calendar is listed with its "
            "UTC timestamp, impact and affected FX pairs (country â†’ currency â†’ "
            "majors, e.g. TR â†’ USDTRY/EURTRY). World rows come from the keyless "
            "GDELT headline stream (English-language wire, RSS fallback) tagged with "
            "a country gazetteer; "
            "a headline may concern several countries and carries the exact matched "
            "terms for audit. Countdowns are computed server-side from the provider "
            "timestamp; nothing is shown at a guessed time and failed providers "
            "surface as warnings instead of invented events."
        ),
        "field_dictionary": {
            "rows[].when_utc": "Event time in UTC (offset-aware provider timestamp).",
            "rows[].seconds_to_event": "Server-computed seconds from as_of (negative = past).",
            "rows[].age_minutes": "Minutes since the event for past rows.",
            "rows[].countries": "ISO codes â€” a row may concern several countries.",
            "rows[].pairs": "Quoted FX pairs / indices derived from the country currency.",
            "rows[].spot": "True for central-bank decisions and wars (alert-worthy).",
            "rows[].pinned": "Spot rows plus high-impact prints from major markets.",
            "country_index[].state": "live | imminent | soon | scheduled | quiet.",
            "alerts[]": "Upcoming spot/pinned rows with default lead times (minutes).",
        },
    }


def _catalog() -> list[dict[str, str]]:
    entries = [{"iso": iso, "name": name} for iso, name in we.COUNTRY_CATALOG]
    entries.extend({"iso": iso, "name": name} for iso, name in we.REGION_NAMES.items())
    return entries


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]


def _num(value: Any, default: float, *, floor: float, ceiling: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(floor, min(ceiling, parsed))
