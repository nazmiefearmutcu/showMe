"""BRIEF — Daily Research Briefing composed from the Awareness news functions.

The watchlist is the input list when one is passed; otherwise it is the user's
portfolio positions plus saved watchlists (never a hard-coded demo list). With
neither, status is ``needs_input`` and nothing is fetched.

BRIEF builds the briefing from two kinds of leg, both answered by the Awareness
news service through the functions that own it:

* MACRO leg: TOP — cross-asset top stories (default 24h window, standard
  quality floor).
* Watchlist leg: CN — one call per watchlist symbol (the first 12), which
  Awareness filters by its ``symbols`` field (BTCUSDT is read as BTC, BRK.B as
  BRK-B). Symbol-scoped news is never a full-text TOP query.

Every row keeps its Awareness evidence (publisher, publisher tier, quality
verdict, sentiment label and model, story id, url), so every markdown bullet
cites the row it came from. BRIEF never re-scores sentiment: Awareness already
scored each row, and a row without a sentiment label keeps none. BRIEF does not
call an LLM and never fabricates prose.

``sections`` selects which article sections are composed (top_stories, watchlist;
default both) and ``limit`` caps each section separately. A requested section
BRIEF does not compose is reported in warnings; a request with no recognised
section is ``input_error``. With sections=top_stories alone no watchlist is needed.

Honest state: every leg unavailable -> ``provider_unavailable`` with Awareness's
reason; any leg served from a cached snapshot -> ``cached_snapshot`` with
``live`` false; otherwise ``live_official``.
"""

from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.data_sources.awareness import AwarenessClient
from showme.engine.functions.news.awareness_news import PROVIDER, UNAVAILABLE_ACTIONS
from showme.engine.functions.news.cn import CNFunction, normalise_symbol
from showme.engine.functions.news.top import TOPFunction
from showme.engine.portfolio.state import PortfolioState
from showme.engine.services.watchlist_store import list_watchlists

MACRO_TAG = "MACRO"
MACRO_LIMIT_CAP = 15
WATCHLIST_HOURS = 24
# Symbol-scoped headline calls are capped; the rest are listed, not searched.
MAX_WATCHLIST_SYMBOLS = 12


def _describe(exc: BaseException) -> str:
    """``Type: message``, or just ``Type`` when the exception carries no message (e.g. a timeout)."""
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


@dataclass
class _Leg:
    """One Awareness-backed call: the macro TOP call or one watchlist CN call."""

    tag: str
    section: str
    status: str = "provider_unavailable"  # ok | empty | provider_unavailable
    rows: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    stale: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@FunctionRegistry.register
class BRIEFFunction(BaseFunction):
    code = "BRIEF"
    name = "Daily Brief"
    category = "news"

    _awareness: AwarenessClient | None = None  # test seam, handed to the TOP and CN legs

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Watchlist precedence: explicit input, else the user's own portfolio
        # positions plus saved watchlists. Never a hard-coded demo list.
        portfolio_symbols, watch_symbols, source_errors = _portfolio_and_watchlist_symbols()
        explicit = params.get("watchlist")
        if explicit:
            if isinstance(explicit, str):
                explicit = [s.strip() for s in explicit.split(",") if s.strip()]
            watchlist = _normalise_symbols(explicit)
            watchlist_source = "input"
        else:
            watchlist = _normalise_symbols([*portfolio_symbols, *watch_symbols])
            watchlist_source = "positions_and_watchlists" if watchlist else "none"
        if instrument and instrument.symbol and instrument.symbol.upper() not in watchlist:
            watchlist = [instrument.symbol.upper(), *watchlist]
            if watchlist_source == "none":
                watchlist_source = "instrument"
        positions_set = set(portfolio_symbols)
        positions_covered = len([s for s in watchlist if s in positions_set])
        base_warnings = [str(err) for err in source_errors]
        # ``live`` defaults to True. It is an OPT-OUT: live=false returns an honest
        # empty shape with no headlines fetched, never the old fabricated template.
        live = _truthy(params.get("live_news"), params.get("live"), default=True)
        limit = _clamp_int(params.get("limit"), default=25, min_value=1, max_value=50)
        # BRIEF#3: ``sections`` selects which article sections are composed; ``limit`` is
        # applied per section. Omitted/empty means both sections.
        requested_sections = _requested_sections(params.get("sections"))
        chosen_sections = [s for s in _ARTICLE_SECTIONS if requested_sections is None or s in requested_sections]
        # A requested section BRIEF does not compose is reported, never silently dropped.
        unsupported_sections = [s for s in (requested_sections or []) if s not in _ARTICLE_SECTIONS]
        if unsupported_sections:
            base_warnings.append(
                "Sections not implemented by BRIEF and skipped: " + ", ".join(unsupported_sections) + "."
            )

        if not live:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "markdown": _no_compose_markdown(watchlist),
                    "articles": [],
                    "rows": [],
                    "watchlist": watchlist,
                    "watchlist_source": watchlist_source,
                    "symbols_searched": [],
                    "article_count": 0,
                    "legs": [],
                    "sections": chosen_sections,
                    "unsupported_sections": unsupported_sections,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "cards": _cards(watchlist, 0, "off", positions_covered),
                    "next_actions": [
                        "Pass live=true (default) to compose the brief from Awareness headlines.",
                    ],
                    "meta": {"providers": [], "generated_at": None, "notes": [], "feed_health": None},
                },
                sources=["watchlist_brief_builder"],
                warnings=[*base_warnings, "Live composition disabled (live=false); no headlines fetched."],
                metadata={"format": "markdown", "live": False, "data_mode": "off"},
            )

        if not chosen_sections:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_error",
                    "markdown": _input_error_markdown(requested_sections or []),
                    "articles": [],
                    "rows": [],
                    "watchlist": watchlist,
                    "watchlist_source": watchlist_source,
                    "symbols_searched": [],
                    "article_count": 0,
                    "legs": [],
                    "sections": [],
                    "unsupported_sections": unsupported_sections,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "cards": _cards(watchlist, 0, "input_error", positions_covered),
                    "next_actions": ["Pass sections=top_stories, sections=watchlist, or both."],
                },
                sources=["watchlist_brief_builder"],
                warnings=[*base_warnings, "No recognised article section requested."],
                metadata={"format": "markdown", "live": False, "data_mode": "explicit_unavailable"},
            )

        if not watchlist and "watchlist" in chosen_sections:
            # No positions, no saved watchlists, no input: say so and fetch nothing.
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "needs_input",
                    "markdown": _needs_input_markdown(),
                    "articles": [],
                    "rows": [],
                    "watchlist": [],
                    "watchlist_source": "none",
                    "symbols_searched": [],
                    "article_count": 0,
                    "legs": [],
                    "sections": chosen_sections,
                    "unsupported_sections": unsupported_sections,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "cards": _cards([], 0, "needs_input", 0),
                    "next_actions": [
                        "Add positions in PORT.",
                        "Save a watchlist, or pass watchlist=AAPL,MSFT to brief specific symbols.",
                    ],
                },
                sources=["portfolio_state", "watchlist_store"],
                warnings=[*base_warnings, "No portfolio positions or watchlist symbols to brief on."],
                metadata={"format": "markdown", "live": False, "data_mode": "explicit_unavailable"},
            )

        want_macro = "top_stories" in chosen_sections
        wl_symbols = watchlist[:MAX_WATCHLIST_SYMBOLS] if "watchlist" in chosen_sections else []
        if "watchlist" in chosen_sections and len(watchlist) > len(wl_symbols):
            base_warnings.append(
                f"Symbol headlines searched for the first {len(wl_symbols)} of {len(watchlist)} symbols."
            )
        per_symbol = max(3, min(limit // max(1, len(wl_symbols) + 1), 10))
        legs = await asyncio.gather(
            *([self._macro_leg(min(limit, MACRO_LIMIT_CAP))] if want_macro else []),
            *[self._symbol_leg(sym, per_symbol) for sym in wl_symbols],
        )
        return _assemble(
            self.code,
            instrument,
            watchlist,
            list(legs),
            limit,
            watchlist_source=watchlist_source,
            symbols_searched=wl_symbols,
            positions_covered=positions_covered,
            base_warnings=base_warnings,
            sections=chosen_sections,
            unsupported_sections=unsupported_sections,
        )

    def _child(self, cls: type) -> Any:
        fn = cls(self.deps)
        fn._awareness = self._awareness  # None uses the process-wide awareness client
        return fn

    async def _macro_leg(self, limit: int) -> _Leg:
        try:
            res = await self._child(TOPFunction).execute(limit=limit)
        except Exception as exc:  # a leg must never sink the whole brief
            return _Leg(MACRO_TAG, "top_stories", reason=f"TOP: {_describe(exc)}")
        return _leg_from_result(MACRO_TAG, "top_stories", res)

    async def _symbol_leg(self, symbol: str, limit: int) -> _Leg:
        tag = normalise_symbol(symbol) or symbol
        try:
            res = await self._child(CNFunction).execute(symbol=symbol, hours=WATCHLIST_HOURS, limit=limit)
        except Exception as exc:
            return _Leg(tag, "watchlist", reason=f"CN: {_describe(exc)}")
        return _leg_from_result(tag, "watchlist", res)


def _leg_from_result(tag: str, section: str, res: FunctionResult) -> _Leg:
    data = res.data if isinstance(res.data, dict) else {}
    meta = res.metadata if isinstance(res.metadata, dict) else {}
    status = str(data.get("status") or "")
    if status not in {"ok", "empty"}:
        reason = str(data.get("reason") or "awareness returned no usable answer")
        return _Leg(tag, section, reason=reason, metadata=meta)
    rows = [row for row in (data.get("rows") or []) if isinstance(row, dict)]
    stale = meta.get("live") is False or meta.get("data_mode") == "cached_snapshot"
    return _Leg(
        tag,
        section,
        status="ok" if rows else "empty",
        rows=rows,
        stale=stale,
        metadata=meta,
    )


def _assemble(
    code: str,
    instrument: Instrument | None,
    watchlist: list[str],
    legs: list[_Leg],
    limit: int,
    *,
    watchlist_source: str = "input",
    symbols_searched: list[str] | None = None,
    positions_covered: int | None = None,
    base_warnings: list[str] | None = None,
    sections: list[str] | None = None,
    unsupported_sections: list[str] | None = None,
) -> FunctionResult:
    wanted = [s for s in _ARTICLE_SECTIONS if sections is None or s in sections]
    # Watchlist legs go first so a story that matches both a symbol and the macro
    # list keeps the symbol tag.
    ordered = sorted(legs, key=lambda leg: 0 if leg.section == "watchlist" else 1)
    articles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for leg in ordered:
        for row in leg.rows:
            cleaned = _clean_article(row)
            key = _dedupe_key(cleaned)
            if key and key in seen:
                continue
            cleaned["matched_symbol"] = leg.tag
            cleaned["section"] = leg.section
            articles.append(cleaned)
            if key:
                seen.add(key)
    # BRIEF#3: ``limit`` caps each section separately, so a long watchlist cannot push every
    # top story out of the brief. Watchlist stories are listed first, then macro top stories.
    watch_rows = [a for a in articles if a.get("section") == "watchlist"][:limit]
    macro_rows = [a for a in articles if a.get("section") == "top_stories"][:limit]
    articles = [*watch_rows, *macro_rows]

    answered = [leg for leg in legs if leg.reason is None]
    unavailable = [leg for leg in legs if leg.reason is not None]
    stale_legs = [leg for leg in answered if leg.stale]

    if not articles and unavailable:
        status = "provider_unavailable"
    elif articles:
        status = "ok"
    else:
        status = "empty"

    if status == "provider_unavailable":
        data_mode = "provider_unavailable"
        live = False
    elif stale_legs:
        data_mode = "cached_snapshot"
        live = False
    else:
        data_mode = "live_official"
        live = True

    reason = None
    if status == "provider_unavailable":
        reason = "; ".join(dict.fromkeys(leg.reason or "" for leg in unavailable)) or "awareness unavailable"
    # Rows shown are live, but a failed leg means coverage is incomplete: say so at the
    # top level, not only in legs[].reason, so `live` never vouches for a missing symbol.
    partial = status != "provider_unavailable" and bool(unavailable)
    missing = [leg.tag for leg in unavailable] if partial else []

    providers = _merge_providers(answered)
    notes = list(dict.fromkeys(note for leg in answered for note in _as_list(leg.metadata.get("notes"))))
    feed_health = next((leg.metadata.get("feed_health") for leg in answered if leg.metadata.get("feed_health")), None)
    generated_at = next((leg.metadata.get("generated_at") for leg in answered if leg.metadata.get("generated_at")), None)
    provider_errors = [f"{leg.tag}: {leg.reason}" for leg in unavailable]
    for leg in stale_legs:
        provider_errors.extend(f"{leg.tag}: {err}" for err in _as_list(leg.metadata.get("provider_errors")))

    leg_summary = [
        {
            "leg": leg.tag,
            "section": leg.section,
            "status": "provider_unavailable" if leg.reason is not None else leg.status,
            "count": len(leg.rows),
            "stale": leg.stale,
            "reason": leg.reason,
        }
        for leg in legs
    ]

    if status == "provider_unavailable":
        next_actions = list(UNAVAILABLE_ACTIONS)
    elif status == "empty":
        next_actions = ["Add watchlist symbols or check the Awareness news service."]
    else:
        next_actions = []

    source_label = _SOURCE_LABELS.get(watchlist_source, "Watchlist")
    markdown = _compose_markdown(watchlist, articles, status, reason, leg_summary, data_mode, source_label, wanted)
    data = {
        "status": status,
        "markdown": markdown,
        "articles": articles,
        "rows": articles,
        "watchlist": watchlist,
        "watchlist_source": watchlist_source,
        "symbols_searched": list(symbols_searched or []),
        "article_count": len(articles),
        "legs": leg_summary,
        "sections": wanted,
        "unsupported_sections": list(unsupported_sections or []),
        "partial": partial,
        "missing_legs": missing,
        "methodology": _METHODOLOGY,
        "field_dictionary": _FIELD_DICTIONARY,
        "cards": _cards(watchlist, len(articles), data_mode, positions_covered),
        "next_actions": next_actions,
        "meta": {
            "providers": providers,
            "generated_at": generated_at,
            "notes": notes,
            "feed_health": feed_health,
        },
    }
    if reason is not None:
        data["reason"] = reason

    sources = [src for leg in answered for src in _as_list(leg.metadata.get("sources"))]
    sources = list(dict.fromkeys(sources)) or ["no_live_source" if status == "provider_unavailable" else "awareness:news"]
    warnings = [*(base_warnings or []), *notes]
    warnings.extend(provider_errors)
    return FunctionResult(
        code=code,
        instrument=None,
        data=data,
        sources=sources,
        warnings=warnings,
        metadata={
            "format": "markdown",
            "provider": PROVIDER,
            "providers": providers,
            "feed_health": feed_health,
            "generated_at": generated_at,
            "notes": notes,
            "provider_errors": provider_errors,
            "live": live,
            "data_mode": data_mode,
            "partial": partial,
            "fallback": status == "provider_unavailable",
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
    )


def _merge_providers(legs: list[_Leg]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for leg in legs:
        for provider in _as_list(leg.metadata.get("providers")):
            if isinstance(provider, dict):
                merged.setdefault(str(provider.get("provider", "?")), provider)
    return list(merged.values())


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


_METHODOLOGY = (
    "BRIEF composes the briefing from the Awareness news service only. It does NOT call an LLM and "
    "does NOT fabricate prose. The watchlist is the input list when one is passed; otherwise it is the "
    "user's portfolio positions plus saved watchlists. With neither, status is needs_input and no news "
    "is fetched. Two kinds of leg run concurrently: MACRO is TOP (cross-asset top stories, "
    "24h window, quality standard or better), and each watchlist symbol (the first 12) is one CN "
    "call (Awareness symbols filter; BTCUSDT is read as BTC). Rows are de-duplicated by URL and title, with watchlist "
    "stories first. Each bullet links to its row, and every row carries publisher, publisher tier, the "
    "quality verdict, the sentiment label and model Awareness assigned, and the story id. BRIEF never "
    "re-scores sentiment and shows none for a row that has none. If every leg is unavailable the status "
    "is provider_unavailable with Awareness's reason. A leg served from a cached snapshot marks the brief "
    "cached_snapshot with live false. If some legs fail while others answer, the brief stays live but "
    "sets partial true and names the missing legs. An empty brief means Awareness answered and no "
    "headline matched. The sections input selects the article sections (top_stories, watchlist; default "
    "both); other requested sections are reported as not implemented, and a request with no recognised "
    "section is input_error. With sections=top_stories alone no watchlist is needed. The limit applies "
    "per section, so watchlist stories cannot push every top story out; the markdown lists each section "
    "under its own heading."
)

_FIELD_DICTIONARY: dict[str, str] = {
    "status": "ok / empty / provider_unavailable / needs_input / input_error.",
    "markdown": "Markdown rendering of the brief; every bullet links to its evidence row.",
    "articles": "Structured rows of the headlines cited in the markdown body (Awareness news rows).",
    "articles[].title": "Headline text as published.",
    "articles[].url": "Source article link; the evidence cite.",
    "articles[].publisher": "Publisher name as Awareness reports it.",
    "articles[].publisher_tier": "Publisher tier 1-5 (1 is the most trusted).",
    "articles[].quality_label": "Awareness quality verdict: premium, standard, low or rejected.",
    "articles[].sentiment": "Awareness sentiment label (positive, negative, neutral); absent when Awareness gave none.",
    "articles[].sentiment_model": "Model that produced the sentiment label (e.g. finbert:ProsusAI/finbert).",
    "articles[].story_id": "Awareness story id; rows sharing it cover the same story.",
    "articles[].matched_symbol": "Awareness entity the row was fetched for (MACRO for cross-asset TOP stories).",
    "articles[].section": "top_stories (macro leg) or watchlist (symbol leg).",
    "watchlist": "Effective watchlist used (input, or positions plus saved watchlists, plus instrument).",
    "watchlist_source": "input / positions_and_watchlists / instrument / none.",
    "symbols_searched": "Symbols that received a symbol-scoped CN call (capped at 12).",
    "article_count": "Number of cited articles.",
    "sections": "Article sections composed (top_stories / watchlist).",
    "unsupported_sections": "Requested sections BRIEF does not compose (reported in warnings, skipped).",
    "legs": "One entry per Awareness call: status, row count, stale flag and reason when unavailable.",
    "partial": "True when some legs failed while others answered: the rows are live, coverage is incomplete.",
    "missing_legs": "Legs (MACRO or symbols) that did not answer when partial is true.",
    "meta": "Awareness provider health (providers, generated_at, notes, feed_health) for the provider strip.",
    "next_actions": "Suggested follow-up actions when Awareness is unavailable or no headline matched.",
}


_SOURCE_LABELS = {
    "input": "Watchlist",
    "positions_and_watchlists": "Positions + saved watchlists",
    "instrument": "Instrument",
    "none": "Watchlist",
}


_ARTICLE_SECTIONS = ("top_stories", "watchlist")


def _requested_sections(raw: Any) -> list[str] | None:
    """Normalise the ``sections`` input. ``None`` means the caller asked for no filter."""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, (list, tuple, set)):
        return None
    out = [str(item).strip().lower() for item in raw if str(item or "").strip()]
    return out or None


def _normalise_symbols(values: list[Any]) -> list[str]:
    out: list[str] = []
    for raw in values:
        sym = str(raw or "").strip().upper()
        if sym and sym not in out:
            out.append(sym)
    return out


def _portfolio_and_watchlist_symbols() -> tuple[list[str], list[str], list[str]]:
    """Portfolio position symbols, saved-watchlist symbols, and any read errors.

    Errors go to the warnings list. A failed read is never replaced by a demo list.
    """
    portfolio_symbols: list[str] = []
    watch_symbols: list[str] = []
    errors: list[str] = []
    try:
        portfolio = PortfolioState()
        portfolio.import_legacy_crypto()
        portfolio_symbols = _normalise_symbols([p.instrument.symbol for p in portfolio.positions])
    except Exception as exc:  # reported honestly, not hidden
        errors.append(f"Portfolio positions unavailable: {_describe(exc)}")
    try:
        for entry in list_watchlists():
            watch_symbols.extend(entry.get("symbols") or [])
        watch_symbols = _normalise_symbols(watch_symbols)
    except Exception as exc:
        errors.append(f"Saved watchlists unavailable: {_describe(exc)}")
    return portfolio_symbols, watch_symbols, errors


def _needs_input_markdown() -> str:
    return "\n".join(
        [
            f"# ShowMe Daily Brief — {datetime.now(timezone.utc):%Y-%m-%d}",
            "",
            "**Symbols:** none",
            "",
            "## Top Stories",
            "",
            "- No portfolio positions or saved watchlist symbols to brief on.",
            "",
            "## Next actions",
            "",
            "- Add positions in PORT, or save a watchlist.",
            "- Or pass a watchlist input to brief specific symbols.",
        ]
    )


def _cards(
    watchlist: list[str],
    article_count: int,
    data_mode: str,
    positions_covered: int | None = None,
) -> list[dict[str, Any]]:
    return [
        {"key": "article_count", "label": "Stories", "value": article_count},
        {"key": "watchlist_size", "label": "Watchlist", "value": len(watchlist)},
        {
            "key": "positions_covered",
            "label": "Positions",
            "value": len(watchlist) if positions_covered is None else positions_covered,
        },
        {"key": "data_mode", "label": "Mode", "value": data_mode},
        {"key": "as_of", "label": "As of", "value": datetime.now(timezone.utc).isoformat()},
    ]


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    """Coerce ``value`` to an int and clamp to [min_value, max_value]."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))


def _truthy(*values: Any, default: bool = False) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return default


def _dedupe_key(article: dict[str, Any]) -> str:
    url = article.get("url") or article.get("link") or ""
    if url:
        return str(url).strip().lower()
    return str(article.get("title", "")).strip().lower()


def _clean_article(article: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(article)
    # BRIEF#5: some rows carry the link as ``link``; the documented evidence field is ``url``.
    link = str(cleaned.get("link") or "").strip()
    if not cleaned.get("url") and link.lower().startswith(("http://", "https://")):
        cleaned["url"] = link
    # BRIEF#5: the documented ``source`` is the publisher, never an adapter tag such as "rss".
    publisher = str(cleaned.get("publisher") or "").strip()
    if publisher and str(cleaned.get("source") or "").strip().lower() in ("", "rss"):
        cleaned["source"] = publisher
    for key in ("summary", "excerpt", "description", "snippet"):
        if isinstance(cleaned.get(key), str):
            cleaned[key] = _strip_html(cleaned[key])
    return cleaned


def _strip_html(value: str) -> str:
    # Unescape entities BEFORE stripping tags so an entity-encoded tag is not
    # re-injected as live markup by a later unescape.
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compose_markdown(
    watchlist: list[str],
    articles: list[dict[str, Any]],
    status: str,
    reason: str | None,
    legs: list[dict[str, Any]],
    data_mode: str,
    source_label: str = "Watchlist",
    sections: list[str] | None = None,
) -> str:
    wanted = [s for s in _ARTICLE_SECTIONS if sections is None or s in sections]
    headings = [(key, label) for key, label in (("watchlist", "Watchlist"), ("top_stories", "Top Stories")) if key in wanted]
    lines = [
        f"# ShowMe Daily Brief — {datetime.now(timezone.utc):%Y-%m-%d}",
        "",
        f"**{source_label}:** {', '.join(watchlist) or 'none'}",
        "",
    ]
    if status == "provider_unavailable":
        for _key, label in headings:
            lines.extend([f"## {label}", "", f"- Awareness news service unavailable: {reason}.", ""])
        lines.extend(["## Next actions", "", f"- {UNAVAILABLE_ACTIONS[0]}"])
        return "\n".join(lines)
    if data_mode == "cached_snapshot":
        lines.extend(["**Cached snapshot:** an Awareness provider is down or degraded; these rows are cached.", ""])
    gaps = [leg for leg in legs if leg["reason"] is not None or leg["stale"]]
    if gaps:
        parts = [f"{leg['leg']} ({'unavailable' if leg['reason'] is not None else 'cached'})" for leg in gaps]
        lines.extend([f"**Coverage gaps:** {', '.join(parts)}", ""])
    if not articles:
        # Each requested section keeps its own heading and an honest empty line, nothing else.
        for _key, label in headings:
            lines.extend([f"## {label}", "", "- No Awareness headlines matched the last 24 hours at standard quality.", ""])
        lines.extend(["## Next actions", "", "- Add watchlist symbols or check the Awareness news service."])
        return "\n".join(lines)

    top_symbols = sorted({str(a.get("matched_symbol") or "") for a in articles if a.get("matched_symbol")})
    if top_symbols:
        lines.extend([f"**Matched symbols:** {', '.join(top_symbols[:10])}", ""])
    for key, label in headings:
        lines.extend([f"## {label}", ""])
        rows = [a for a in articles if a.get("section") == key]
        if not rows:
            lines.extend(["- No headlines in this section.", ""])
            continue
        for a in rows:
            lines.append(_bullet(a))
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def _bullet(a: dict[str, Any]) -> str:
    title = a.get("title", "")
    link = a.get("url") or a.get("link") or ""
    sym = a.get("matched_symbol") or ""
    evidence = [str(a.get("publisher") or a.get("source") or "")]
    if a.get("publisher_tier") is not None:
        evidence.append(f"tier {a.get('publisher_tier')}")
    if a.get("quality_label"):
        evidence.append(str(a.get("quality_label")))
    if a.get("sentiment"):
        evidence.append(str(a.get("sentiment")))
    suffix = " — " + " · ".join(part for part in evidence if part)
    if link:
        return f"- ({sym}) [{title}]({link}){suffix}"
    return f"- ({sym}) {title}{suffix}"


def _input_error_markdown(requested: list[str]) -> str:
    return "\n".join(
        [
            f"# ShowMe Daily Brief — {datetime.now(timezone.utc):%Y-%m-%d}",
            "",
            f"**Sections requested:** {', '.join(requested) or 'none'}",
            "",
            "- No recognised article section was requested. Use top_stories and/or watchlist.",
        ]
    )


def _no_compose_markdown(watchlist: list[str]) -> str:
    """Honest body for the live=false opt-out path. No fabricated headlines."""
    return "\n".join(
        [
            f"# ShowMe Daily Brief — {datetime.now(timezone.utc):%Y-%m-%d}",
            "",
            f"**Watchlist:** {', '.join(watchlist)}",
            "",
            "## Top Stories",
            "",
            "- Live composition is disabled (live=false). No headlines were fetched.",
            "",
            "## Next actions",
            "",
            "- Pass live=true (the default) to compose the brief from Awareness headlines.",
        ]
    )
