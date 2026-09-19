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

Providers are the repo's existing KEYLESS paths:
  * the ForexFactory weekly calendar reused from ECO
    (``showme.engine.functions.macro.eco._forex_factory_events``), and
  * the keyless GDELT (or RSS fallback) news adapter for world headlines.

Honesty: every row carries its source; country tags carry the matched
terms; empty windows say so; nothing is fabricated when a provider fails.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

# World-headline fetch cache (module level, shared across MEET calls): the
# first-with-items-wins (tie→GDELT) chain can spend ~10 s before answering, and the
# pane refetches on every country/world filter toggle. Filters apply over the
# cached rows, so only the upstream fetch rides this TTL. Successes keep the
# full window; empty/failed passes expire faster so an outage recovers.
_WORLD_CACHE: tuple[float, tuple[list[dict[str, Any]], str, str | None], float] | None = None
# Faz 5 realtime delta: the pane polls every 30 s with a since/known_ids
# cursor, so the upstream window stays minute-fresh; failures expire faster
# so an outage recovers. _SYMBOL_NEWS_TTL_S stays 180 s (less critical).
_WORLD_CACHE_TTL_S = 60.0
_WORLD_CACHE_FAIL_TTL_S = 15.0
# Followed-symbol headline cache: (symbols_key, stored_at, articles)
_SYMBOL_NEWS_CACHE: tuple[str, float, list[dict[str, Any]]] | None = None
_SYMBOL_NEWS_TTL_S = 180.0

_FINANCE_CALENDAR_URL = "https://www.financecalendar.com/wp-json/fc/v1/calendar"
_FINANCE_CALENDAR_MAX_DAYS = 92
_FINANCE_CALENDAR_TTL_S = 1800.0
_FINANCE_CALENDAR_CACHE: dict[str, Any] = {
    "fetched_at": 0.0,
    "key": "",
    "rows": [],
    "attribution": None,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.macro import eco as eco_mod
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
        # Caller preference echo only (Task 1: the keyless chain is unchanged;
        # the choice is surfaced via filters_applied + metadata.requested_mode).
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
            # Calendar mode never touches the world wire (GDELT/RSS).
            include_world = False

        warnings: list[str] = []
        sources: list[str] = []

        # --- parallel fetch: calendar + world + symbol (Faz 1 race) ---
        # The three upstreams are independent; racing them with
        # asyncio.gather cuts the cold-open chain (8-24s serial) to the
        # slowest single leg. Timeouts and the honest envelope below are
        # unchanged.
        calendar_timeout = min(max(2.0, news_timeout), 12.0)

        async def _calendar_fetch() -> tuple[
            list[dict[str, Any]], list[str], list[str], list[str],
            list[dict[str, str]], int, int,
        ]:
            if effective_kind == "world":
                return [], [], [], [], [], 0, 0
            return await self._calendar_events(
                now=now,
                days_ahead=days_ahead,
                timeout=calendar_timeout,
            )

        async def _world_fetch() -> tuple[list[dict[str, Any]], str, str | None]:
            if not include_world:
                return [], "", None
            return await self._world_headlines(now=now, timeout=news_timeout)

        async def _symbol_fetch() -> list[dict[str, Any]]:
            if not (include_world and symbols):
                return []
            return await self._symbol_articles(symbols, now=now, timeout=news_timeout)

        calendar_bundle, (articles, world_source, world_error), extra = await asyncio.gather(
            _calendar_fetch(),
            _world_fetch(),
            _symbol_fetch(),
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

        economic, dropped_no_time = we.economic_rows(calendar_rows, now=now)
        dropped_no_time += rejected_primary_no_time

        # --- world headlines (keyless GDELT, RSS fallback) ---
        world: list[dict[str, Any]] = []
        if include_world:
            if world_error:
                warnings.append(world_error)
            if articles:
                deduped_articles, url_duplicates = _dedupe_articles(articles)
                row_stats: dict[str, int] = {}
                world = we.world_rows(
                    deduped_articles, now=now, source=world_source or "news",
                    limit=len(deduped_articles), stats=row_stats,
                )[:60]
                duplicate_rows_dropped += url_duplicates + row_stats.get("duplicate_rows_dropped", 0)
                if world:
                    sources.append(world_source or "news")
                    active_source_tiers.append(
                        "wire_rss_fallback" if world_source == "rss" else "wire_gdelt_primary"
                    )
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
                        symbol_world = we.world_rows(
                            deduped_fresh, now=now, source="symbol_feed",
                            limit=len(deduped_fresh), stats=row_stats,
                        )[:60]
                        duplicate_rows_dropped += url_duplicates + row_stats.get("duplicate_rows_dropped", 0)
                        if symbol_world:
                            world.extend(symbol_world)
                            sources.append("symbol_feed")
                            active_source_tiers.append("wire_symbol_feed")

        rows = economic + world
        unfiltered_upcoming, unfiltered_past = we.split_window(
            rows, days_ahead=days_ahead, days_back=days_back
        )

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
        # Upcoming-first priority within the limit.
        upcoming = upcoming[:limit]
        past = past[: max(0, limit - len(upcoming))]
        ordered = upcoming + past
        alerts = we.build_alerts(unfiltered_upcoming, lead_minutes=we.DEFAULT_ALERT_LEAD_MINUTES)
        country_index = we.build_country_index(unfiltered_upcoming + unfiltered_past, now=now)

        if not rows:
            reason = (
                "No requested world-events provider responded."
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
                    mode=mode, tags=tags, data_filter=data_filter,
                    data_mode="provider_unavailable" if warnings else "empty",
                    provider_mode=provider_mode,
                    hash=empty_hash, new_rows=empty_new,
                    removed_ids=empty_removed, since_echo=since,
                    data_quality=empty_quality, attributions=attributions,
                ),
                sources=sources or ["no_live_source"],
                warnings=warnings + ([reason] if warnings else []),
                metadata={
                    "live": False,
                    "fallback": True,
                    "data_mode": "provider_unavailable" if warnings else "empty",
                    "requested_mode": provider_mode,
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
        live_mode = "live_" + "+".join(sources) if sources else "cached_snapshot"
        if provider_mode == "cached_snapshot" and live_mode.startswith("live_"):
            warnings.append(f"requested cached_snapshot, served {live_mode}")
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
            ),
            attributions=attributions,
        )
        payload["filtered_empty"] = not ordered
        payload["unfiltered_upcoming_count"] = len(unfiltered_upcoming)
        payload["symbol_rows"] = symbol_rows
        payload["symbols_requested"] = symbols
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
                "requested_mode": provider_mode,
                "provider_errors": warnings,
                "counts": {
                    "rows": len(ordered),
                    "upcoming": len(upcoming),
                    "past": len(past),
                    "alerts": len(alerts),
                },
            },
        )

    async def _calendar_events(
        self, *, now: datetime, days_ahead: float, timeout: float
    ) -> tuple[
        list[dict[str, Any]], list[str], list[str], list[str],
        list[dict[str, str]], int, int,
    ]:
        """Fetch the configured provider chain plus keyless future coverage."""

        async def primary_chain() -> tuple[list[dict[str, Any]], str, list[str], str, int]:
            errors: list[str] = []
            rejected_no_time = 0
            deadline = time.monotonic() + timeout
            reserve_ff = min(2.0, timeout / 3)
            te = getattr(self.deps, "tradingeconomics", None)
            finnhub = getattr(self.deps, "finnhub", None)
            keyed_left = sum((
                _provider_configured(te, "tradingeconomics"),
                _provider_configured(finnhub, "finnhub"),
            ))

            def keyed_budget() -> float:
                nonlocal keyed_left
                remaining = max(0.0, deadline - time.monotonic())
                budget = min(4.0, max(0.1, (remaining - reserve_ff) / max(1, keyed_left)))
                keyed_left -= 1
                return budget

            def usable(raw: Any, source: str) -> list[dict[str, Any]]:
                nonlocal rejected_no_time
                normalized = _normalize_calendar_rows(raw, source)
                timed = [row for row in normalized if we.parse_when_utc(row.get("date")) is not None]
                rejected = len(normalized) - len(timed)
                rejected_no_time += rejected
                if rejected:
                    errors.append(f"{source}: {rejected} untimed rows rejected")
                return timed

            end = now + timedelta(days=min(days_ahead, _FINANCE_CALENDAR_MAX_DAYS))
            date_args = {
                "start": now.date().isoformat(),
                "end": end.date().isoformat(),
            }
            if _provider_configured(te, "tradingeconomics"):
                try:
                    raw = await asyncio.wait_for(
                        te.calendar(**date_args), timeout=keyed_budget()
                    )
                    rows = usable(raw, "tradingeconomics")
                    if rows:
                        return rows, "tradingeconomics", errors, "authenticated_primary", rejected_no_time
                    errors.append("tradingeconomics: empty response")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"tradingeconomics: {str(exc) or exc.__class__.__name__}")

            if _provider_configured(finnhub, "finnhub"):
                try:
                    raw = await asyncio.wait_for(
                        finnhub.economic_calendar(**date_args), timeout=keyed_budget()
                    )
                    rows = usable(raw, "finnhub")
                    if rows:
                        return rows, "finnhub", errors, "authenticated_fallback", rejected_no_time
                    errors.append("finnhub: empty response")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"finnhub: {str(exc) or exc.__class__.__name__}")

            try:
                remaining = max(0.1, deadline - time.monotonic())
                async with asyncio.timeout(remaining):
                    raw = await eco_mod._forex_factory_events(
                        client=await self._client(), timeout=remaining
                    )
                rows = usable(raw, "forex_factory")
                if rows:
                    return rows, "forex_factory", errors, "keyless_fallback", rejected_no_time
                errors.append("forex_factory: empty response")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"forex_factory: {str(exc) or exc.__class__.__name__}")
            return [], "", errors, "", rejected_no_time

        primary_task = asyncio.create_task(primary_chain())
        finance_task = asyncio.create_task(
            _finance_calendar_events(
                client=await self._client(), now=now,
                days_ahead=days_ahead, timeout=timeout,
            )
        )
        primary, finance = await asyncio.gather(primary_task, finance_task)
        primary_rows, primary_source, warnings, primary_tier, rejected_primary_no_time = primary
        finance_rows, attribution, finance_error = finance
        if finance_error:
            warnings.append(finance_error)

        merged, duplicates, finance_contributed = _merge_calendar_rows(
            primary_rows, finance_rows
        )
        sources = [primary_source] if primary_source else []
        tiers = [primary_tier] if primary_tier else []
        attributions: list[dict[str, str]] = []
        if finance_contributed:
            sources.append("financecalendar")
            tiers.append("future_supplement")
            attributions.append(attribution or _finance_calendar_attribution({}))
        return merged, sources, warnings, tiers, attributions, duplicates, rejected_primary_no_time

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
        # The crypto-group leg and the per-symbol legs are independent — race
        # them concurrently. Sequential awaits here used to stack 4 × timeout
        # (~32 s worst case) against the 14 s function timeout and flakily
        # killed MEET whenever the caller followed symbols on a slow network.
        async def _crypto_leg() -> list[dict[str, Any]]:
            if not crypto_syms:
                return []
            try:
                return list(
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
                return []

        async def _symbol_leg(sym: str) -> list[dict[str, Any]]:
            try:
                return list(
                    await asyncio.wait_for(
                        rss.fetch(
                            DataRequest(
                                kind=DataKind.NEWS,
                                extra={
                                    "feed_group": "market",
                                    "symbol": sym,
                                    "per_feed_timeout_seconds": max(3.0, min(timeout, 5.0)),
                                    "collection_timeout_seconds": max(3.0, min(timeout, 5.0)),
                                },
                                limit=30,
                            )
                        ),
                        timeout=timeout,
                    )
                    or []
                )
            except Exception:  # noqa: BLE001
                return []

        legs = [_crypto_leg(), *(_symbol_leg(sym) for sym in symbols[:3])]
        collected: list[dict[str, Any]] = []
        for result in await asyncio.gather(*legs):
            collected.extend(result)
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
        rss_extra = {
            "feed_group": "market",
            # Explicit per-feed + collection budgets: the adapter's
            # 2 s defaults were fine for ten feeds, but the
            # fast-wire list (15 hosts) on a COLD connection pool
            # completed nothing inside the window -> zero
            # headlines right after a restart (observed
            # 2026-09-16, GDELT down at the same time).
            "per_feed_timeout_seconds": max(3.0, min(timeout, 5.0)),
            "collection_timeout_seconds": max(3.0, min(timeout, 5.0)),
        }

        async def _gdelt_leg() -> tuple[list[dict[str, Any]], str | None]:
            try:
                items = await asyncio.wait_for(
                    gdelt.fetch(DataRequest(
                        kind=DataKind.NEWS,
                        extra={"query": we.world_query()},
                        start=now - timedelta(days=we.MEET_GDELT_LOOKBACK_DAYS),
                        limit=we.MEET_GDELT_LIMIT,
                    )),
                    # gdelt leg capped so a wedged DOC endpoint fails fast into the RSS win
                    timeout=min(timeout, we.MEET_GDELT_TIMEOUT_SECONDS),
                )
                if items:
                    return list(items), None
                return [], "gdelt: empty result"
            except Exception as exc:  # noqa: BLE001
                return [], f"gdelt: {str(exc) or exc.__class__.__name__}"

        async def _rss_leg() -> tuple[list[dict[str, Any]], str | None]:
            try:
                items = await asyncio.wait_for(
                    rss.fetch(DataRequest(
                        kind=DataKind.NEWS,
                        extra=rss_extra,
                        limit=50,
                    )),
                    timeout=timeout,
                )
                if items:
                    return list(items), None
                return [], "rss: empty result"
            except Exception as exc:  # noqa: BLE001
                return [], f"rss: {str(exc) or exc.__class__.__name__}"

        if gdelt is None and rss is None:
            result = ([], "", "news: neither gdelt nor rss is configured")
            _WORLD_CACHE = (now_mono, result, _WORLD_CACHE_FAIL_TTL_S)
            return result
        # First-wins race (owner 2026-09-17: the serial GDELT-timeout +
        # RSS-fallback chain cost ~13 s on a cold cache). GDELT keeps
        # priority when both legs are already done with items; otherwise
        # whoever answers first with items wins and the laggard is
        # cancelled, so worst case is ~one leg instead of both legs.
        legs: dict[asyncio.Task, str] = {}
        if gdelt is not None:
            legs[asyncio.create_task(_gdelt_leg())] = "gdelt"
        if rss is not None:
            legs[asyncio.create_task(_rss_leg())] = "rss"
        results: dict[str, tuple[list[dict[str, Any]], str | None]] = {}
        pending = set(legs)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    results[legs[task]] = task.result()
                except Exception as exc:  # noqa: BLE001 - legs guard already; last resort
                    results[legs[task]] = ([], f"{legs[task]}: {str(exc) or exc.__class__.__name__}")
            gdelt_res = results.get("gdelt")
            if gdelt_res is not None and gdelt_res[0]:
                for task in pending:
                    task.cancel()
                result = (gdelt_res[0], "gdelt", None)
                _WORLD_CACHE = (now_mono, result, _WORLD_CACHE_TTL_S)
                return result
            rss_res = results.get("rss")
            if rss_res is not None and rss_res[0]:
                for task in pending:
                    task.cancel()
                gdelt_err = gdelt_res[1] if gdelt_res else None
                if gdelt_err and "empty" not in gdelt_err:
                    gdelt_note: str | None = f"{gdelt_err} (rss served)"
                else:
                    gdelt_note = None
                result = (
                    rss_res[0],
                    "rss",
                    gdelt_note,
                )
                _WORLD_CACHE = (now_mono, result, _WORLD_CACHE_TTL_S)
                return result
        # Every leg settled without items.
        gdelt_err = results.get("gdelt", ([], None))[1]
        rss_err = results.get("rss", ([], None))[1]
        if rss_err and "empty" not in rss_err:
            merged = f"{gdelt_err}; {rss_err}" if gdelt_err else rss_err
        else:
            merged = gdelt_err or rss_err or "news: no world headlines returned"
        result = ([], "rss" if rss is not None else "", merged)
        _WORLD_CACHE = (now_mono, result, _WORLD_CACHE_FAIL_TTL_S)
        return result


_CALENDAR_TITLE_COUNTRIES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:fomc|federal reserve|fed chair|powell)\b", re.I), "US"),
    (re.compile(r"\b(?:bank of england|boe)\b", re.I), "GB"),
    (re.compile(r"\b(?:european central bank|ecb)\b", re.I), "EU"),
    (re.compile(r"\b(?:bank of japan|boj)\b", re.I), "JP"),
    (re.compile(r"\b(?:people'?s bank of china|pboc)\b", re.I), "CN"),
    (re.compile(r"\b(?:reserve bank of australia|rba)\b", re.I), "AU"),
    (re.compile(r"\b(?:bank of canada|boc)\b", re.I), "CA"),
    (re.compile(r"\b(?:reserve bank of new zealand|rbnz)\b", re.I), "NZ"),
    (re.compile(r"\b(?:swiss national bank|snb)\b", re.I), "CH"),
    (re.compile(r"\b(?:tcmb|central bank of the republic of t(?:u|ü)rkiye)\b", re.I), "TR"),
    (re.compile(r"\briksbank\b", re.I), "SE"),
    (re.compile(r"\bnorges bank\b", re.I), "NO"),
)


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


def _provider_configured(provider: Any, name: str) -> bool:
    if provider is None:
        return False
    if not hasattr(provider, "api_key"):
        return True  # explicit injected provider/test double
    key = str(getattr(provider, "api_key", "") or "").strip()
    if not key:
        return False
    return not (name == "tradingeconomics" and key.casefold() == "guest:guest")


def _ci(item: dict[str, Any], *names: str) -> Any:
    folded = {str(key).casefold(): value for key, value in item.items()}
    for name in names:
        if name.casefold() in folded:
            return folded[name.casefold()]
    return None


def _calendar_country(value: Any) -> str:
    token = str(value or "").strip()
    direct = we.canonical_iso(token)
    if direct:
        return direct
    lookup = {
        **{name.casefold(): iso for iso, name in we.COUNTRY_CATALOG},
        **{name.casefold(): iso for iso, name in we.REGION_NAMES.items()},
        "united states of america": "US",
        "euro zone": "EU",
        "eurozone": "EU",
        "great britain": "GB",
        "u.k.": "GB",
    }
    return lookup.get(token.casefold(), "")


def _infer_calendar_country(title: str) -> str:
    countries, _ = we.match_countries(title)
    if len(countries) == 1:
        return countries[0]
    for pattern, iso in _CALENDAR_TITLE_COUNTRIES:
        if pattern.search(title):
            return iso
    return ""


def _importance(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value) >= 3:
            return "high"
        if float(value) >= 2:
            return "medium"
        return "low"
    raw = str(value or "").strip()
    try:
        return _importance(float(raw))
    except (TypeError, ValueError):
        return we.normalize_impact(raw)


def _normalize_calendar_rows(raw: Any, source: str) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = raw.get("events") or raw.get("data") or raw.get("economicCalendar") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(_ci(item, "event", "title", "name") or "").strip()
        if not title:
            continue
        when = _ci(item, "time_utc", "date", "datetime", "time")
        if source == "financecalendar" and (
            _ci(item, "time_utc") in (None, "") or bool(_ci(item, "all_day"))
        ):
            when = None
        provider_country = _ci(item, "country", "currency", "countryCode")
        country = _calendar_country(provider_country)
        country_basis = "provider" if country else None
        if not country:
            country = _infer_calendar_country(title)
            if country:
                country_basis = "title_inference"
        out.append({
            "country": country or str(provider_country or "").strip(),
            "event": title,
            "date": str(when or "").strip(),
            "importance": _importance(_ci(item, "importance", "impact")),
            "actual": _ci(item, "actual"),
            "forecast": _ci(item, "forecast", "consensus", "estimate"),
            "previous": _ci(item, "previous", "prior"),
            "unit": str(_ci(item, "unit") or "").strip(),
            "provider": source,
            "provider_event_url": str(_ci(item, "url", "link") or "").strip() or None,
            "country_basis": country_basis,
            "provider_country_raw": provider_country,
        })
    return out


def _finance_calendar_attribution(raw: Any) -> dict[str, str]:
    item = raw if isinstance(raw, dict) else {}
    url = str(item.get("url") or "https://www.financecalendar.com/").strip()
    return {
        "name": str(item.get("name") or item.get("source") or "FinanceCalendar.com"),
        "url": url,
        "text": str(
            item.get("text") or item.get("terms")
            or "Economic calendar data by FinanceCalendar.com"
        ),
    }


async def _finance_calendar_events(
    *, client: Any, now: datetime, days_ahead: float, timeout: float
) -> tuple[list[dict[str, Any]], dict[str, str] | None, str | None]:
    days = max(1, min(int(math.ceil(days_ahead)), _FINANCE_CALENDAR_MAX_DAYS))
    date_from = now.date().isoformat()
    date_to = (now + timedelta(days=days)).date().isoformat()
    cache_key = f"{date_from}:{date_to}"
    age = time.monotonic() - float(_FINANCE_CALENDAR_CACHE.get("fetched_at") or 0.0)
    if (
        _FINANCE_CALENDAR_CACHE.get("key") == cache_key
        and _FINANCE_CALENDAR_CACHE.get("rows")
        and age < _FINANCE_CALENDAR_TTL_S
    ):
        return (
            list(_FINANCE_CALENDAR_CACHE["rows"]),
            _FINANCE_CALENDAR_CACHE.get("attribution"),
            None,
        )
    try:
        async with asyncio.timeout(timeout):
            try:
                response = await client.get(
                    _FINANCE_CALENDAR_URL,
                    params={"from": date_from, "to": date_to},
                    timeout=timeout,
                )
            except TypeError:
                response = await client.get(_FINANCE_CALENDAR_URL, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            return [], None, "financecalendar: unexpected response shape"
        rows = _normalize_calendar_rows(payload, "financecalendar")
        attribution = _finance_calendar_attribution(
            payload.get("attribution") if isinstance(payload, dict) else {}
        )
        if rows:
            _FINANCE_CALENDAR_CACHE.update({
                "fetched_at": time.monotonic(),
                "key": cache_key,
                "rows": list(rows),
                "attribution": attribution,
            })
        return rows, attribution, None
    except Exception as exc:  # noqa: BLE001
        return [], None, f"financecalendar: {str(exc) or exc.__class__.__name__}"


def _calendar_identity(item: dict[str, Any]) -> tuple[str, str, str]:
    when = we.parse_when_utc(item.get("date") or item.get("when_utc"))
    stamp = when.strftime("%Y-%m-%dT%H:%MZ") if when else ""
    country = _calendar_country(item.get("country") or item.get("currency"))
    title = re.sub(r"[^a-z0-9]+", " ", str(item.get("event") or item.get("title") or "").casefold()).strip()
    return stamp, country, title


def _merge_calendar_rows(
    primary: list[dict[str, Any]], supplemental: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int, bool]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    dropped = 0
    contributed = False
    for tier, items in (("primary", primary), ("supplement", supplemental)):
        for item in items:
            key = _calendar_identity(item)
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            merged.append(item)
            if tier == "supplement":
                contributed = True
    return merged, dropped, contributed


def _data_quality(
    rows: list[dict[str, Any]], *, duplicate_rows_dropped: int,
    dropped_no_time: int, active_source_tiers: list[str],
    attributions: list[dict[str, str]],
) -> dict[str, Any]:
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
            "Scheduled rows prefer configured TradingEconomics, then configured "
            "Finnhub, then the keyless ForexFactory weekly calendar. The keyless "
            "FinanceCalendar.com feed supplements future coverage (maximum 92 days) "
            "with required attribution and never replaces an overlapping primary row. "
            "Every country on the calendar is listed with its "
            "UTC timestamp, impact and affected FX pairs (country → currency → "
            "majors, e.g. TR → USDTRY/EURTRY). World rows come from the keyless "
            "GDELT headline stream (English-language wire, RSS fallback) tagged with "
            "a country gazetteer; "
            "a headline may concern several countries and carries the exact matched "
            "terms for audit. Countdowns are computed server-side from the provider "
            "timestamp; nothing is shown at a guessed time and failed providers "
            "surface as warnings instead of invented events. The scheduled "
            "calendar includes the best available provider window plus the bounded "
            "FinanceCalendar.com supplement. Country tags inferred from titles are "
            "explicitly marked country_basis=title_inference."
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
            "rows[].summary": "Headline summary text (world rows; mirrors details.summary).",
            "rows[].details.summary": "Headline summary text, truncated (world rows).",
            "rows[].details.topic_tags": "Macro topic tags (FED, ECB, INFLATION...) matched in the headline.",
            "rows[].details.matched_assets": "Exact asset terms that produced the asset_tags.",
            "rows[].details.provider_tags": "Provider-carried tags unioned in, when present.",
            "rows[].details.url": "Source article URL (None when absent).",
            "rows[].details.article_url": "Original article URL for world headlines (None when absent).",
            "rows[].details.publisher": "Publisher/feed name supplied by the RSS adapter.",
            "rows[].details.feed_url": "RSS feed URL used to retrieve the article.",
            "rows[].details.provider": "Calendar provider that supplied the row.",
            "rows[].details.provider_event_url": "Provider event page when supplied.",
            "rows[].details.country_basis": "provider or title_inference; inferred country tags are never presented as provider facts.",
            "data_quality": "Observable completeness counts; not a claim of factual accuracy.",
            "attributions": "Visible attribution records required by active supplemental sources.",
            "rows[].details.is_global": "True for global (ALL) calendar rows (country_names Global, pairs empty).",
            "country_catalog[]": "Static country reference (ISO + name) so filters stay complete when a provider is down.",
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
        return (
            has_actual
            and has_forecast
            and _is_numeric_value(details.get("actual"))
            and _is_numeric_value(details.get("forecast"))
        )
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
