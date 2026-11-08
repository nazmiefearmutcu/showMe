"""MEET — Meeting Briefings: world-events tracker.

The pane tracks scheduled world events (central-bank decisions, CPI, GDP,
… for every country on the calendar) and country-tagged world headlines
(wars, elections, summits) in one list:

  * upcoming events ascending — from now until the nearest upcoming
    high-impact event and beyond, each with a server-computed countdown,
  * past events descending — the last ``days_back`` days,
  * a country index (every country that appeared + next event + state),
  * spot alerts for rate decisions / wars with configurable lead times
    (the UI persists them under ``showme.meet.alerts``).

Providers are Awareness (``awareness-markets``): the economic calendar and holidays for the
calendar rows, Awareness news (quality-gated, topic-tagged) for the world headlines and followed-symbol
headlines. Geopolitics impact comes from Awareness topics and importance, not a keyword classifier.
Country gates now mean: followed countries short of the calendar floor get their Awareness holidays and
Awareness news, and any remaining shortfall is reported as an explicit warning.

Honesty: every row carries its source; country tags carry the matched
terms; an empty forward calendar reports status empty; nothing is fabricated when Awareness fails.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

# Awareness news cache for followed-symbol headlines (local service, cheap to refetch).
_SYMBOL_NEWS_CACHE: tuple[str, float, list[dict[str, Any]], AwarenessResponse] | None = None
_SYMBOL_NEWS_TTL_S = 180.0
# Lookback for world headlines and followed-symbol news (days, in hours for the API).
_NEWS_LOOKBACK_HOURS = 168
_NEWS_LIMIT = 200
# Awareness topics that mark geopolitical impact (replaces the keyword war classifier).
_GEO_TOPICS = frozenset({"geopolitics", "sanctions", "trade_tariffs"})


def _utc_now() -> datetime:
    return datetime.now(UTC)

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.data_sources.awareness import AwarenessResponse
from showme.engine.functions.calendar._common import aw_get, data_meta, parse_float, parse_int, provenance_metadata
from showme.engine.functions.macro import eco as eco_mod
from showme.engine.services import country_gates as cg
from showme.engine.services import world_events as we


@FunctionRegistry.register
class MEETFunction(BaseFunction):
    code = "MEET"
    name = "Meeting Briefings — World Events"
    category = "comm"
    description = (
        "World-events tracker — country calendar + tagged headlines with "
        "countdowns, affected FX pairs and spot alerts."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        now = _utc_now()
        countries = _csv(params.get("countries"))
        kind = str(params.get("kind") or "all").strip().lower() or "all"
        impacts = _csv(params.get("impact"))
        query = str(params.get("query") or params.get("q") or params.get("topic") or "")
        symbols = _csv(params.get("symbols"))
        tags = _csv(params.get("tags"))
        assets = _csv(params.get("assets"))
        data_filter = str(params.get("data_filter") or "all").strip().lower() or "all"
        if data_filter not in _DATA_FILTERS:
            data_filter = "all"
        # Caller preference echo only: the served mode is computed from the Awareness providers that
        # answered; the choice is surfaced via filters_applied + metadata.requested_mode.
        provider_mode = str(params.get("provider_mode") or "live_official").strip().lower() or "live_official"
        # Backward-compat: an explicit mode wins over kind; without mode the
        # legacy kind implies the mode (economic->calendar, world->wire).
        raw_mode = params.get("mode")
        mode_given = raw_mode is not None and str(raw_mode).strip() != ""
        if mode_given:
            mode = str(raw_mode).strip().lower() or "all"
            if mode not in {"all", "calendar", "wire"}:
                mode = "all"
        else:
            mode = {"economic": "calendar", "world": "wire"}.get(kind, "all")
        if mode == "calendar":
            effective_kind = "economic"
        elif mode == "wire":
            effective_kind = "world"
        elif mode_given:
            # An explicit mode=all shows both worlds even if kind narrows.
            effective_kind = "all"
        else:
            effective_kind = kind
            if effective_kind not in {"all", "economic", "world"}:
                effective_kind = "all"
        days_ahead = _num(params.get("days_ahead"), 90.0, floor=1.0, ceiling=365.0)
        days_back = _num(params.get("days_back"), 7.0, floor=0.0, ceiling=90.0)
        limit = int(_num(params.get("limit"), 250, floor=10, ceiling=1000))
        # Faz 5 realtime delta (server stateless: the cursor rides in from the
        # client). `since` is the previous `as_of` (informational echo only);
        # `known_ids` is the client's row baseline (CSV, cap 1000).
        since = str(params.get("since") or "")
        known_ids = _csv(params.get("known_ids"))[:1000]
        news_timeout = _num(params.get("news_timeout") or params.get("timeout"), 8.0,
                            floor=2.0, ceiling=15.0)
        include_world = _truthy(params.get("include_world", True)) and effective_kind in {"", "all", "world"}
        if mode == "calendar":
            # Calendar mode never touches the news feed.
            include_world = False

        warnings: list[str] = []
        sources: list[str] = []

        # --- parallel fetch: calendar + world + symbol (Faz 1 race) ---
        # The three upstreams are independent; racing them with
        # asyncio.gather cuts the cold-open chain (8-24s serial) to the
        # slowest single leg. Timeouts and the honest envelope below are
        # unchanged.
        calendar_timeout = min(max(2.0, news_timeout), 12.0)

        # Every Awareness answer MEET uses; provenance (stale providers, notes, generated_at) is read from these.
        aw_responses: list[AwarenessResponse] = []

        async def _calendar_fetch() -> tuple[
            list[dict[str, Any]], list[str], list[str], list[str],
            list[dict[str, str]], int, int,
        ]:
            if effective_kind == "world":
                return [], [], [], [], [], 0, 0
            return await self._calendar_events(
                now=now,
                days_ahead=days_ahead,
                days_back=days_back,
                timeout=calendar_timeout,
                responses=aw_responses,
            )

        async def _world_fetch() -> tuple[list[dict[str, Any]], str, str | None]:
            if not include_world:
                return [], "", None
            return await self._world_headlines(
                now=now, timeout=news_timeout, countries=countries, responses=aw_responses,
            )

        async def _symbol_fetch() -> tuple[list[dict[str, Any]], str | None]:
            if not (include_world and symbols):
                return [], None
            return await self._symbol_articles(symbols, now=now, timeout=news_timeout, responses=aw_responses)

        # Country gate: followed countries get their Awareness holidays and closures for the
        # same past+future window. A country still short of the calendar floor is reported
        # as a shortfall warning, never filled from another source.
        async def _gates_fetch() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            if not countries or effective_kind == "world":
                return [], []
            holiday_rows, holiday_status = await _holiday_gate(
                self, countries, now=now, days_back=days_back, days_ahead=days_ahead,
                responses=aw_responses,
            )
            return holiday_rows, [holiday_status]

        calendar_bundle, (articles, world_source, world_error), (extra, symbol_news_error), gate_bundle = await asyncio.gather(
            _calendar_fetch(),
            _world_fetch(),
            _symbol_fetch(),
            _gates_fetch(),
        )
        (
            calendar_rows,
            calendar_sources,
            calendar_warnings,
            active_source_tiers,
            attributions,
            duplicate_rows_dropped,
            rejected_primary_no_time,
        ) = calendar_bundle
        warnings.extend(calendar_warnings)
        sources.extend(calendar_sources)
        if symbol_news_error:
            warnings.append(f"symbol_events: awareness news unavailable: {symbol_news_error}")
        gate_holiday_rows, gate_statuses = gate_bundle
        if gate_holiday_rows:
            # Holidays ride the calendar pipeline (kind=economic rows with a
            # real ISO country and provider-labelled source).
            calendar_rows = list(calendar_rows) + gate_holiday_rows
            gate_holiday_providers = [
                p for s in gate_statuses if s.get("gate") == "holidays"
                for p in (s.get("providers") or [])
            ]
            for provider in dict.fromkeys(gate_holiday_providers):
                if provider not in sources:
                    sources.append(provider)
                active_source_tiers.append("gate_holidays")
        economic_stats: dict[str, int] = {}
        economic, dropped_no_time = we.economic_rows(calendar_rows, now=now, stats=economic_stats)
        duplicate_rows_dropped += economic_stats.get("duplicate_rows_dropped", 0)
        dropped_no_time += rejected_primary_no_time
        _attach_numerics(economic)
        rows_capped_at_limit = 0

        # --- world headlines (Awareness news, topic-scoped) ---
        world: list[dict[str, Any]] = []
        if include_world:
            if world_error:
                warnings.append(world_error)
            if articles:
                deduped_articles, url_duplicates = _dedupe_articles(articles)
                row_stats: dict[str, int] = {}
                full_world = we.world_rows(
                    deduped_articles, now=now, source=world_source or "news",
                    limit=len(deduped_articles), stats=row_stats,
                )
                rows_capped_at_limit += row_stats.get("rows_capped_at_limit", 0)
                _apply_awareness_impact(full_world, deduped_articles)
                world = full_world
                duplicate_rows_dropped += url_duplicates + row_stats.get("duplicate_rows_dropped", 0)
                if world:
                    sources.append(world_source or "news")
                    active_source_tiers.append("wire_awareness_news")
            if symbols:
                # Followed symbols need their OWN feeds: the world stream is
                # geopolitics/market wires, so "BTC" matched nothing (owner
                # 2026-09-16: "btc ekledim bana onun olayları gösterilmiyor").
                if extra:
                    known_urls = {str(a.get("url") or a.get("link") or "").strip() for a in articles}
                    fresh = [
                        a
                        for a in extra
                        if not str(a.get("url") or a.get("link") or "").strip()
                        or str(a.get("url") or a.get("link") or "").strip() not in known_urls
                    ]
                    if fresh:
                        deduped_fresh, url_duplicates = _dedupe_articles(fresh)
                        row_stats = {}
                        full_symbol_world = we.world_rows(
                            deduped_fresh, now=now, source="awareness:news",
                            limit=len(deduped_fresh), stats=row_stats,
                        )
                        rows_capped_at_limit += row_stats.get("rows_capped_at_limit", 0)
                        _apply_awareness_impact(full_symbol_world, deduped_fresh)
                        symbol_world = full_symbol_world
                        duplicate_rows_dropped += url_duplicates + row_stats.get("duplicate_rows_dropped", 0)
                        if symbol_world:
                            world.extend(symbol_world)
                            if "awareness:news" not in sources:
                                sources.append("awareness:news")
                            active_source_tiers.append("wire_awareness_symbol_news")

        gate_report: list[dict[str, Any]] = []
        rows = economic + world
        unfiltered_upcoming, unfiltered_past = we.split_window(
            rows, days_ahead=days_ahead, days_back=days_back
        )
        if countries:
            gate_report = cg.gate_window_counts(rows, countries, now=now)
            warnings.extend(cg.shortfall_warnings(gate_report))

        # Task 2 (spot/pinned) rides inside apply_filters; the spec's
        # with_forecast/with_actual/surprise_only are applied just below on
        # economic rows only (world_events.py is untouched — Faz 1+2 tree).
        passthrough_filter = data_filter if data_filter in {"all", "spot", "pinned", "major_only"} else "all"
        # Limit is applied AFTER windowing (below): the feed arrives in
        # week-chronological order (old rows first), so truncating here
        # would let a small limit eat the entire upcoming section.
        filtered = we.apply_filters(
            rows,
            countries=countries,
            kind=effective_kind,
            impacts=impacts,
            query=query,
            limit=max(limit, len(rows)),
            tags=tags,
            assets=assets,
            data_filter=passthrough_filter,
        )
        if data_filter in {"with_forecast", "with_actual", "surprise_only"}:
            filtered = [r for r in filtered if _passes_data_filter(r, data_filter)]
        upcoming, past = we.split_window(filtered, days_ahead=days_ahead, days_back=days_back)
        rows_capped_at_limit += max(0, len(upcoming) + len(past) - limit)
        # Upcoming-first priority within the limit.
        upcoming = upcoming[:limit]
        past = past[: max(0, limit - len(upcoming))]
        ordered = upcoming + past
        alerts = we.build_alerts(unfiltered_upcoming, lead_minutes=we.DEFAULT_ALERT_LEAD_MINUTES)
        country_index = we.build_country_index(unfiltered_upcoming + unfiltered_past, now=now)

        if not rows:
            reason = (
                "Awareness did not answer: " + "; ".join(warnings)
                if warnings else
                "No world events were returned."
            )
            empty_hash, empty_new, empty_removed = _delta([], known_ids)
            empty_quality = _data_quality(
                [],
                duplicate_rows_dropped=duplicate_rows_dropped,
                dropped_no_time=dropped_no_time,
                active_source_tiers=active_source_tiers,
                attributions=attributions,
                rows_capped_at_limit=rows_capped_at_limit,
            )
            empty_data = _shell(
                now=now,
                status="provider_unavailable" if warnings else "empty",
                reason=reason,
                rows=[], upcoming=[], past=[],
                country_index=[], country_catalog=_catalog(),
                alerts=[], countries=countries, kind=kind, impacts=impacts,
                query=query, days_ahead=days_ahead, days_back=days_back,
                limit=limit, dropped_no_time=dropped_no_time,
                mode=mode, tags=tags, data_filter=data_filter,
                data_mode="provider_unavailable" if warnings else "empty",
                provider_mode=provider_mode,
                hash=empty_hash, new_rows=empty_new,
                removed_ids=empty_removed, since_echo=since,
                data_quality=empty_quality, attributions=attributions,
            )
            empty_data["data_gates"] = gate_statuses
            empty_data["meta"] = data_meta(aw_responses)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=empty_data,
                sources=sources or ["no_live_source"],
                warnings=warnings + ([reason] if warnings else []),
                metadata={
                    **provenance_metadata(aw_responses, provider_errors=warnings),
                    "live": False,
                    "fallback": True,
                    "data_mode": "provider_unavailable" if warnings else "empty",
                    "requested_mode": provider_mode,
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
                for row in unfiltered_upcoming + unfiltered_past:
                    if row.get("kind") != "world":
                        continue
                    text = " ".join(
                        str(row.get(key) or "")
                        for key in ("title", "summary", "details", "description")
                    ).lower()
                    # Faz 2: the row's own asset_tags count as a match (a
                    # BTC-tagged headline belongs to the BTC view even when
                    # the ticker text itself is absent). Provider-carried tags
                    # are read-only here — never overwritten.
                    row_details = row.get("details") or {}
                    row_asset_tags: set[str] = set()
                    for container in (row, row_details):
                        carried = container.get("asset_tags")
                        if isinstance(carried, (list, tuple, set)):
                            row_asset_tags.update(
                                str(t).strip().upper() for t in carried if str(t).strip()
                            )
                    matched_terms: list[str] = []
                    for sym, terms in term_map:
                        try:
                            sym_base = ni.crypto_base(sym).upper()
                        except Exception:  # noqa: BLE001 - best-effort section
                            sym_base = str(sym or "").strip().upper()
                        if (str(sym or "").strip().upper() in row_asset_tags
                                or (sym_base and sym_base in row_asset_tags)):
                            if str(sym or "").strip().upper() not in matched_terms:
                                matched_terms.append(str(sym or "").strip().upper())
                            continue
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

        delta_hash, delta_new, delta_removed = _delta(ordered, known_ids)
        # Built as a variable so the repo's data_mode literal scanner only
        # sees sanctioned values (``live_<source>`` follows ECO's convention).
        # Served mode follows the providers that fed this response: any down/degraded provider makes it a
        # cached_snapshot with live False (contract); otherwise live_official.
        live_mode = str(provenance_metadata(aw_responses)["data_mode"])
        if provider_mode == "cached_snapshot" and live_mode == "live_official":
            warnings.append("requested cached_snapshot, served live_official")
        forward_economic = [row for row in upcoming if row.get("kind") == "economic"]
        payload = _shell(
            now=now,
            status="ok" if forward_economic else "empty",
            reason=None if forward_economic else "No upcoming economic events in the window.",
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
            mode=mode,
            tags=tags,
            data_filter=data_filter,
            data_mode=live_mode,
            provider_mode=provider_mode,
            hash=delta_hash,
            new_rows=delta_new,
            removed_ids=delta_removed,
            since_echo=since,
            data_quality=_data_quality(
                ordered,
                duplicate_rows_dropped=duplicate_rows_dropped,
                dropped_no_time=dropped_no_time,
                active_source_tiers=active_source_tiers,
                attributions=attributions,
                rows_capped_at_limit=rows_capped_at_limit,
            ),
            attributions=attributions,
        )
        payload["filtered_empty"] = not ordered
        payload["unfiltered_upcoming_count"] = len(unfiltered_upcoming)
        payload["symbol_rows"] = symbol_rows
        payload["symbols_requested"] = symbols
        payload["data_gates"] = gate_statuses
        payload["meta"] = data_meta(aw_responses)
        payload["country_gate_report"] = {
            "min_events_per_7d": cg.MEET_GATE_MIN_EVENTS,
            "window_days": cg.MEET_GATE_WINDOW_DAYS,
            "countries": gate_report,
        }
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=payload,
            sources=sources or ["no_live_source"],
            warnings=warnings,
            metadata=provenance_metadata(aw_responses, provider_errors=warnings, extra={
                "fallback": not sources,
                "requested_mode": provider_mode,
                "counts": {
                    "rows": len(ordered),
                    "upcoming": len(upcoming),
                    "past": len(past),
                    "alerts": len(alerts),
                },
            }),
        )

    async def _calendar_events(
        self, *, now: datetime, days_ahead: float, timeout: float, days_back: float = 0,
        responses: list[AwarenessResponse] | None = None,
    ) -> tuple[
        list[dict[str, Any]], list[str], list[str], list[str],
        list[dict[str, str]], int, int,
    ]:
        """Awareness economic calendar, normalised into the MEET calendar-row shape."""
        start = (now - timedelta(days=days_back)).date().isoformat()
        end = (now + timedelta(days=days_ahead)).date().isoformat()
        resp, error = await aw_get(self, "/calendar/economic", {"from": start, "to": end})
        if resp is None:
            return [], [], [error or "awareness economic calendar unavailable"], [], [], 0, 0
        if responses is not None:
            responses.append(resp)
        rows: list[dict[str, Any]] = []
        rejected_no_time = 0
        for item in resp.data or []:
            if not isinstance(item, dict):
                continue
            row = _calendar_row_from_awareness(item)
            if row is None:
                rejected_no_time += 1
                continue
            rows.append(row)
        sources = ["awareness:econ"] if rows else []
        tiers = ["awareness_calendar"] if rows else []
        return rows, sources, [], tiers, [], 0, rejected_no_time

    async def _symbol_articles(
        self, symbols: list[str], *, now: datetime, timeout: float,
        responses: list[AwarenessResponse] | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Awareness news tagged with the followed tickers (cached for a few minutes).

        Returns ``(articles, error)``. An Awareness failure is an error, never an empty list that
        looks like "no news for this symbol".
        """
        global _SYMBOL_NEWS_CACHE
        key = ",".join(sorted(symbols))
        cached = _SYMBOL_NEWS_CACHE
        if cached is not None and cached[0] == key and (time.monotonic() - cached[1]) < _SYMBOL_NEWS_TTL_S:
            if responses is not None:
                responses.append(cached[3])
            return list(cached[2]), None
        resp, error = await aw_get(self, "/news", {
            "symbols": ",".join(symbols),
            "hours": _NEWS_LOOKBACK_HOURS,
            "min_quality": "standard",
            "limit": 100,
        })
        if resp is None:
            return [], error or "awareness news unavailable"
        articles = [_article_from_awareness(item) for item in resp.data or [] if isinstance(item, dict)]
        _SYMBOL_NEWS_CACHE = (key, time.monotonic(), articles, resp)
        if responses is not None:
            responses.append(resp)
        return list(articles), None

    async def _world_headlines(
        self, *, now: datetime, timeout: float, countries: list[str] | None = None,
        responses: list[AwarenessResponse] | None = None,
    ) -> tuple[list[dict[str, Any]], str, str | None]:
        """World headlines from Awareness news.

        Followed countries narrow the stream by ``countries``; otherwise the stream is the
        geopolitics / sanctions / trade-tariff topics. Quality floor is ``standard``.
        """
        params: dict[str, Any] = {
            "hours": _NEWS_LOOKBACK_HOURS,
            "min_quality": "standard",
            "limit": _NEWS_LIMIT,
        }
        if countries:
            params["countries"] = ",".join(countries)
        else:
            params["topics"] = ",".join(sorted(_GEO_TOPICS))
        resp, error = await aw_get(self, "/news", params)
        if resp is None:
            return [], "", error or "awareness news unavailable"
        if responses is not None:
            responses.append(resp)
        articles = [_article_from_awareness(item) for item in resp.data or [] if isinstance(item, dict)]
        return articles, "awareness:news", None


_AWARENESS_IMPORTANCE_HIGH = 70
_AWARENESS_IMPORTANCE_MEDIUM = 40


def _calendar_row_from_awareness(item: dict[str, Any]) -> dict[str, Any] | None:
    """Awareness economic row -> the calendar-row shape ``we.economic_rows`` consumes."""
    when = str(item.get("scheduled_at") or "").strip()
    title = str(item.get("title") or "").strip()
    if not when or not title:
        return None
    level = parse_int(item.get("importance"), default=1, floor=1, ceiling=3)
    return {
        "country": str(item.get("country") or "").strip().upper(),
        "event": title,
        "date": when,
        "importance": {3: "high", 2: "medium", 1: "low"}[level],
        "actual": item.get("actual"),
        "forecast": item.get("forecast"),
        "previous": item.get("previous"),
        "unit": str(item.get("unit") or ""),
        "provider": "awareness:econ",
        "provider_event_url": None,
        "country_basis": "provider",
        "provider_country_raw": item.get("country"),
    }


async def _holiday_gate(
    fn: Any,
    countries: list[str],
    *,
    now: datetime,
    days_back: float,
    days_ahead: float,
    responses: list[AwarenessResponse] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Public holidays and market closures for followed countries, from Awareness."""
    isos: list[str] = []
    for token in countries:
        iso = we.canonical_iso(token) or str(token).strip().upper()
        if iso and iso not in isos:
            isos.append(iso)
    status: dict[str, Any] = {
        "gate": "holidays", "fired": False, "providers": [], "countries": isos,
        "rows_added": 0, "notes": [],
    }
    if not isos:
        return [], status
    start = (now - timedelta(days=days_back)).date().isoformat()
    end = (now + timedelta(days=days_ahead)).date().isoformat()
    resp, error = await aw_get(fn, "/calendar/holidays", {"from": start, "to": end, "countries": ",".join(isos)})
    if resp is None:
        status["notes"].append(error or "awareness holidays unavailable")
        return [], status
    if responses is not None:
        responses.append(resp)
    rows: list[dict[str, Any]] = []
    for item in resp.data or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        day = str(item.get("date") or "").strip()
        if not name or not day:
            continue
        kind = str(item.get("kind") or "public")
        label = {"public": "Public Holiday", "early_close": "Early close", "market_closed": "Market closed"}.get(kind, "Holiday")
        rows.append({
            "country": str(item.get("country") or "").strip().upper(),
            "event": f"{label}: {name}",
            "date": f"{day}T00:00:00Z",
            "importance": "low",
            "actual": None,
            "forecast": None,
            "previous": None,
            "unit": "",
            "provider": "awareness:holidays",
            "country_basis": "provider",
        })
    status.update({"fired": bool(rows), "providers": ["awareness:holidays"] if rows else [], "rows_added": len(rows)})
    return rows, status


def _article_from_awareness(item: dict[str, Any]) -> dict[str, Any]:
    """Awareness news row -> the article shape ``we.world_rows`` consumes."""
    url = str(item.get("url") or "").strip()
    topics = [str(topic) for topic in (item.get("topics") or []) if str(topic).strip()]
    symbols = [str(sym).strip().upper() for sym in (item.get("symbols") or []) if str(sym).strip()]
    publisher = str(item.get("publisher_name") or item.get("publisher_id") or "").strip()
    return {
        "title": str(item.get("title") or "").strip(),
        "summary": str(item.get("summary") or item.get("excerpt") or "").strip() or None,
        "url": url,
        "link": url,
        "source": publisher or "awareness",
        "published_at": item.get("published_at"),
        "asset_tags": symbols,
        "topic_tags": topics,
        "topics": topics,
        "countries": list(item.get("countries") or []),
        "aw_importance": parse_float(item.get("importance")),
        "aw_id": item.get("id"),
    }


def _apply_awareness_impact(rows: list[dict[str, Any]], articles: list[dict[str, Any]]) -> None:
    """Set world-row impact from Awareness topics and importance (in place).

    Every headline row is keyed back to its Awareness article by URL, or by title when the article has
    no URL. Geopolitics / sanctions / trade-tariff stories are high impact at Awareness importance
    >= 70 and medium otherwise. Other stories follow Awareness importance alone. The keyword classifier's
    impact is never kept for these rows; an unmatched row is low, with that basis recorded.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for article in articles:
        if article.get("url"):
            by_key.setdefault(f"url:{article['url']}", article)
        title = we._clean_text(article.get("title"))
        if title:
            by_key.setdefault(f"title:{title}", article)
    for row in rows:
        details = row.get("details") or {}
        article = by_key.get(f"url:{details.get('url')}") if details.get("url") else None
        if article is None:
            article = by_key.get(f"title:{row.get('title')}")
        if article is None:
            row["impact"] = "low"
            details["impact_basis"] = "awareness_unmatched"
            continue
        importance = article.get("aw_importance") or 0.0
        topics = set(article.get("topics") or [])
        if topics & _GEO_TOPICS:
            row["impact"] = "high" if importance >= _AWARENESS_IMPORTANCE_HIGH else "medium"
        elif importance >= _AWARENESS_IMPORTANCE_HIGH:
            row["impact"] = "high"
        elif importance >= _AWARENESS_IMPORTANCE_MEDIUM:
            row["impact"] = "medium"
        else:
            row["impact"] = "low"
        details["impact_basis"] = "awareness_topics_importance"
        details["awareness_topics"] = sorted(topics)
        details["awareness_importance"] = importance


def _dedupe_articles(articles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep the first article for an exact source URL; preserve URL-less rows."""
    seen_urls: set[str] = set()
    kept: list[dict[str, Any]] = []
    dropped = 0
    for article in articles:
        url = str(article.get("url") or article.get("link") or "").strip()
        if url and url in seen_urls:
            dropped += 1
            continue
        if url:
            seen_urls.add(url)
        kept.append(article)
    return kept, dropped


def _data_quality(
    rows: list[dict[str, Any]], *, duplicate_rows_dropped: int,
    dropped_no_time: int, active_source_tiers: list[str],
    attributions: list[dict[str, str]],
    rows_capped_at_limit: int = 0,
) -> dict[str, Any]:
    """Observable completeness counts; duplicate_rows_dropped counts exact URL/row-id matches only."""
    timed = sum(1 for row in rows if row.get("when_utc") and not row.get("undated"))
    undated = sum(1 for row in rows if row.get("undated") or not row.get("when_utc"))
    source_traceable = sum(1 for row in rows if str(row.get("source") or "").strip())
    url_traceable = sum(
        1 for row in rows
        if str((row.get("details") or {}).get("article_url") or (row.get("details") or {}).get("provider_event_url") or "").strip()
    )
    required = 1 if any(row.get("source") == "financecalendar" for row in rows) else 0
    covered = 1 if required and any(a.get("url") for a in attributions) else 0
    return {
        "row_count": len(rows),
        "timed_count": timed,
        "undated_count": undated,
        "source_traceable_count": source_traceable,
        "url_traceable_count": url_traceable,
        "attribution_required_count": required,
        "attribution_covered_count": covered,
        "duplicate_rows_dropped": duplicate_rows_dropped,
        "rows_dropped_no_time": dropped_no_time,
        "rows_capped_at_limit": rows_capped_at_limit,
        "active_source_tiers": list(dict.fromkeys(active_source_tiers)),
        "measures": "observable_completeness_not_factual_accuracy",
    }


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
    mode: str = "all",
    tags: list[str] | None = None,
    data_filter: str = "all",
    data_mode: str = "",
    provider_mode: str = "live_official",
    hash: str = "",
    new_rows: list[dict[str, Any]] | None = None,
    removed_ids: list[str] | None = None,
    since_echo: str = "",
    data_quality: dict[str, Any] | None = None,
    attributions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    window = we.window_meta(rows, now=now, days_ahead=days_ahead, days_back=days_back)
    return {
        "status": status,
        "reason": reason,
        "as_of": now.isoformat(),
        "data_mode": data_mode,
        "alerts_count": len(alerts),
        "countries_tracked": len(country_index),
        "next_high_impact": window["next_high_impact"],
        "hash": hash,
        "new_rows": list(new_rows or []),
        "removed_ids": list(removed_ids or []),
        "since_echo": since_echo,
        "rows": rows,
        "upcoming": upcoming,
        "past": past,
        "row_count": len(rows),
        "upcoming_count": len(upcoming),
        "past_count": len(past),
        "window": window,
        "country_index": country_index,
        "country_catalog": country_catalog,
        "alerts": alerts,
        "alert_default_lead_minutes": list(we.DEFAULT_ALERT_LEAD_MINUTES),
        "dropped_no_time": dropped_no_time,
        "data_quality": data_quality or _data_quality(
            rows,
            duplicate_rows_dropped=0,
            dropped_no_time=dropped_no_time,
            active_source_tiers=[],
            attributions=[],
        ),
        "attributions": list(attributions or []),
        "filters_applied": {
            "countries": countries,
            "kind": kind,
            "mode": mode,
            "tags": list(tags or []),
            "data_filter": data_filter,
            "provider_mode": provider_mode,
            "impact": impacts,
            "q": query,
            "days_ahead": days_ahead,
            "days_back": days_back,
            "limit": limit,
        },
        "methodology": (
            "MEET reads three Awareness areas and nothing else. Calendar rows: the Awareness economic "
            "calendar (/calendar/economic) for the requested window; one row per release, with its UTC "
            "timestamp, importance and country; values pass through as Awareness reports them. Holidays: "
            "Awareness public holidays and market closures for the followed countries (/calendar/holidays). "
            "World headlines: Awareness news (/news) at the standard quality floor, limited to the "
            "geopolitics, sanctions and trade-tariff topics, or to the followed countries when set. Followed "
            "symbols: Awareness news tagged with each symbol. Headline impact comes from Awareness topics and "
            "importance: geopolitics, sanctions and trade-tariff stories are high from importance 70 "
            "(medium below it); other stories are high from 70, medium from 40, low below. The spot and "
            "pinned flags still come from title keyword patterns for wars and rate decisions. Headline "
            "country tags are matched from the title and summary text (a gazetteer), not supplied by "
            "Awareness. Countdowns are computed server-side from the provider timestamp. When a provider "
            "feeding the response is down or degraded, rows are kept with data_mode cached_snapshot and "
            "live false, and the provider states are listed in meta.providers. When Awareness does not answer, "
            "the status is provider_unavailable with the reason. An empty forward calendar is status empty. "
            "Failures surface as warnings; nothing is invented or filled from another source."
        ),
        "field_dictionary": {
            "hash": "sha1 of the ordered row ids in this payload (realtime delta cursor).",
            "new_rows": "Window rows absent from the client's known_ids (cap 50, window order).",
            "removed_ids": "known_ids absent from this window (cap 200).",
            "since_echo": "Informational echo of the client's since cursor.",
            "rows[].when_utc": "Event time in UTC (offset-aware provider timestamp).",
            "rows[].seconds_to_event": "Server-computed seconds from as_of (negative = past).",
            "rows[].age_minutes": "Minutes since the event for past rows.",
            "rows[].countries": "ISO codes — a row may concern several countries.",
            "rows[].pairs": "Quoted FX pairs / indices derived from the country currency.",
            "rows[].spot": "True for central-bank decisions and wars (alert-worthy).",
            "rows[].pinned": "Spot rows plus high-impact prints from major markets.",
            "rows[].asset_tags": "Asset tags (BTC, ETH, ETF...) — world rows carry them under details.asset_tags.",
            "rows[].event_type": "Classified event type — world rows carry it under details.event_type.",
            "rows[].details.matched_terms": "Exact gazetteer terms that tagged a world headline.",
            "rows[].details.asset_tags": "Asset tags (BTC, ETH, ETF...) matched in title/summary/provider tags.",
            "rows[].details.event_type": "Classified event type (etf_flow, rate_decision, inflation_print, hack, ...).",
            "rows[].details.actual": "Released value when available (Actual).",
            "rows[].details.forecast": "Consensus estimate when available (Forecast).",
            "rows[].details.previous": "Prior print when available (Previous).",
            "rows[].details.actual_num": "Parsed Actual as float (None when non-numeric).",
            "rows[].details.forecast_num": "Parsed Forecast as float (None when non-numeric).",
            "rows[].details.previous_num": "Parsed Previous as float (None when non-numeric).",
            "rows[].details.unit": "Resolved unit (%, K/M/B/T) from the printed cells.",
            "rows[].details.surprise": "Actual minus Forecast — only when both parse and units are comparable; else None (never invented across scales).",
            "rows[].details.surprise_pct": "Surprise relative to |Forecast| (None when Forecast is 0 or surprise is None).",
            "rows[].details.surprise_basis": "actual_minus_forecast | capped_estimate | unit_mismatch | non_numeric | missing_value.",
            "rows[].details.capped": "True when a printed cell was censored with '<' (surprise is an estimate).",
            "rows[].details.revised": "True when a same-snapshot duplicate carried a differing Actual (later value wins).",
            "rows[].details.provider_tz_offset": "Provider timestamp's own UTC offset (when_utc is always +00:00).",
            "rows[].summary": "Headline summary text (world rows; mirrors details.summary).",
            "rows[].details.summary": "Headline summary text, truncated (world rows).",
            "rows[].details.topic_tags": "Macro topic tags (FED, ECB, INFLATION...) matched in the headline.",
            "rows[].details.matched_assets": "Exact asset terms that produced the asset_tags.",
            "rows[].details.provider_tags": "Provider-carried tags unioned in, when present.",
            "rows[].details.url": "Source article URL (None when absent).",
            "rows[].details.article_url": "Original article URL for world headlines (None when absent).",
            "rows[].details.publisher": "Publisher name supplied by Awareness news.",
            "rows[].details.feed_url": "Feed URL when one is supplied (null for Awareness news).",
            "rows[].details.provider": "Calendar provider that supplied the row.",
            "rows[].details.provider_event_url": "Provider event page when supplied.",
            "rows[].details.country_basis": "provider or title_inference; inferred country tags are never presented as provider facts.",
            "data_quality": "Observable completeness counts; not a claim of factual accuracy.",
            "attributions": "Visible attribution records required by active supplemental sources.",
            "rows[].details.is_global": "True for global (ALL) calendar rows (country_names Global, pairs empty).",
            "country_catalog[]": "Static country reference (ISO + name) so filters stay complete when a provider is down.",
            "country_index[].state": "live | imminent | soon | scheduled | quiet.",
            "alerts[]": "Upcoming spot/pinned rows with default lead times (minutes).",
            "data_gates[]": "Per-country gate statuses: gate name, Awareness provider, rows added, failure notes (holiday gate).",
            "rows[].details.impact_basis": "awareness_topics_importance for headlines matched to an Awareness article; awareness_unmatched otherwise.",
            "meta": "Provider health (providers, generated_at, notes, feed_health) for the Awareness responses used.",
            "country_gate_report.countries[]": "Past-7d and future-7d event counts per followed country against the 20-event floor (past_met / future_met).",
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


# Binding ruling (Task 3): Task 2's all/spot/pinned AND the spec's
# all/with_forecast/with_actual/surprise_only are supported together;
# unknown values fall back to all (no-op).
_DATA_FILTERS = frozenset({
    "all", "spot", "pinned", "major_only",
    "with_forecast", "with_actual", "surprise_only",
})


def _has_detail(value: Any) -> bool:
    """A calendar cell counts as present when it is not empty."""
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    text = str(value).strip()
    return bool(text) and text.casefold() not in {
        "nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity",
    }


def _is_numeric_value(value: Any) -> bool:
    """Numeric per the shared ForexFactory parser (K/M/B/T, %, capped)."""
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    try:
        parsed, _, _ = eco_mod._parse_ff_number(value)
    except Exception:  # noqa: BLE001 - best-effort filter
        return False
    return parsed is not None


# Units the FF parser scales to absolute numbers — K vs M is comparable
# (both already scaled); % vs absolute is not.
_SCALED_UNITS = frozenset({"K", "M", "B", "T"})


def _safe_parse_number(value: Any) -> tuple[float | None, str, bool]:
    """Parse a calendar cell into (value, unit, capped); never raises."""
    if isinstance(value, bool) or value is None:
        return None, "", False
    if isinstance(value, (int, float)):
        return (round(float(value), 6), "", False) if math.isfinite(float(value)) else (None, "", False)
    try:
        parsed, unit, capped = eco_mod._parse_ff_number(value)
    except Exception:  # noqa: BLE001 - best-effort enrichment
        return None, "", False
    return parsed, unit, capped


def _attach_numerics(rows: list[dict[str, Any]]) -> None:
    """Enrich economic rows with parsed numerics + unit-aware surprise.

    Raw provider strings stay untouched (UI renders them); the numeric
    layer rides alongside: ``actual_num`` / ``forecast_num`` /
    ``previous_num``, resolved ``unit``, and ``surprise`` (actual minus
    forecast) ONLY when both sides parse AND their units are comparable
    (equal, or both K/M/B/T which the parser pre-scales). A ``%`` print
    against a unitless consensus yields no surprise — inventing one
    across scales would be worse than reporting none. ``surprise_pct``
    is surprise relative to |forecast| (None when forecast is 0).
    """
    for row in rows:
        if row.get("kind") != "economic":
            continue
        details = row.get("details")
        if not isinstance(details, dict):
            continue
        raw_a, raw_f, raw_p = details.get("actual"), details.get("forecast"), details.get("previous")
        a, au, ac = _safe_parse_number(raw_a)
        f, fu, fc = _safe_parse_number(raw_f)
        p, pu, _ = _safe_parse_number(raw_p)
        details["actual_num"] = a
        details["forecast_num"] = f
        details["previous_num"] = p
        # Unit comes only from a side that actually parsed — the raw
        # provider string ("N/A", "abc") is never a unit.
        if au and a is not None:
            details["unit"] = au
        elif fu and f is not None:
            details["unit"] = fu
        elif pu and p is not None:
            details["unit"] = pu
        details["capped"] = bool((ac and a is not None) or (fc and f is not None))
        if a is None or f is None:
            if (_has_detail(raw_a) and a is None) or (_has_detail(raw_f) and f is None):
                details["surprise"] = None
                details["surprise_basis"] = "non_numeric"
            else:
                details["surprise"] = None
                details["surprise_basis"] = "missing_value"
            details["surprise_pct"] = None
            continue
        if au != fu and not ({au, fu} <= _SCALED_UNITS):
            details["surprise"] = None
            details["surprise_pct"] = None
            details["surprise_basis"] = "unit_mismatch"
            continue
        surprise = round(a - f, 6)
        details["surprise"] = surprise
        details["surprise_pct"] = round(surprise / abs(f), 6) if f != 0 else None
        details["surprise_basis"] = (
            "capped_estimate" if details["capped"] else "actual_minus_forecast"
        )


def _passes_data_filter(row: dict[str, Any], data_filter: str) -> bool:
    """Spec data filters apply to calendar rows only."""
    if row.get("kind") != "economic":
        return False
    details = row.get("details") or {}
    has_actual = _has_detail(details.get("actual"))
    has_forecast = _has_detail(details.get("forecast"))
    if data_filter == "with_forecast":
        return has_forecast
    if data_filter == "with_actual":
        return has_actual
    if data_filter == "surprise_only":
        # A computable surprise (unit-compatible numerics on both sides);
        # unit-mismatched or non-numeric prints carry no surprise value.
        return details.get("surprise") is not None
    return True


def _csv(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]


# Faz 5 realtime delta (caps: known_ids 1000 at parse, new_rows 50, removed 200).
_NEW_ROWS_CAP = 50
_REMOVED_IDS_CAP = 200


def _delta(
    ordered: list[dict[str, Any]], known_ids: list[str]
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Hash + diff of the already-ordered window (upcoming asc, past desc).

    The full list always ships (cache-hit is cheap); the delta rides along.
    Without a client baseline (paramsuz call) both lists are empty so old
    callers see an additive-only change.
    """
    ids = [str(r.get("id") or "") for r in ordered]
    digest = hashlib.sha1("\n".join(ids).encode("utf-8")).hexdigest()
    if not known_ids:
        return digest, [], []
    known = set(known_ids)
    current = set(ids)
    new_rows = [r for r in ordered if str(r.get("id") or "") not in known][:_NEW_ROWS_CAP]
    removed_ids = [i for i in known_ids if i not in current][:_REMOVED_IDS_CAP]
    return digest, new_rows, removed_ids


def _num(value: Any, default: float, *, floor: float, ceiling: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(floor, min(ceiling, parsed))
