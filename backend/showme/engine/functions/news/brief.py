"""BRIEF — Daily Research Briefing composed from live ShowMe surfaces.

Per the manifest, BRIEF composes a portfolio-aware briefing from existing
surfaces (TOP cross-asset top stories + TOP symbol-scoped headlines per
watchlist symbol) and emits markdown + a structured payload where every bullet
cites the evidence row it came from. It does NOT call an LLM and NEVER
fabricates prose or quotes.

The previous implementation returned a hardcoded ``_brief_template`` with
invented bullets ("Market monitor is online…") whenever ``live`` was falsy.
That violated the manifest claim ("No synthetic summaries, no fabricated
quotes"). The default path now always composes from real, keyless live data via
TOP (which ranks live RSS/GDELT headlines). A clearly-labelled
``provider_unavailable`` fallback is kept ONLY for a genuine outage where every
adapter fails — and even then the body names the failure instead of inventing a
"no news today, all quiet" summary.
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.portfolio.state import PortfolioState
from showme.engine.services.watchlist_store import list_watchlists

# Symbol-scoped headline searches are capped; the rest are listed, not searched.
_MAX_SYMBOL_SEARCHES = 12


@FunctionRegistry.register
class BRIEFFunction(BaseFunction):
    code = "BRIEF"
    name = "Daily Brief"
    category = "news"

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
        # ``live`` defaults to True (manifest default). It is now an OPT-OUT
        # toggle, not an opt-in: the brief composes from real surfaces by
        # default. Passing live=false explicitly is the only way to skip the
        # network composition — and even that returns an honest empty shape, not
        # the old fabricated template.
        live = _truthy(params.get("live_news"), params.get("live"), default=True)
        limit = _clamp_int(params.get("limit"), default=25, min_value=1, max_value=50)
        timeout = params.get("news_timeout", params.get("timeout", 8))
        base_warnings = [f"{err}" for err in source_errors]
        # BRIEF#3: ``sections`` selects which article sections are composed;
        # ``limit`` is applied per section. Omitted/empty means both sections.
        requested_sections = _requested_sections(params.get("sections"))
        chosen_sections = [
            s for s in _ARTICLE_SECTIONS
            if requested_sections is None or s in requested_sections
        ]
        # BRIEF#3: a requested section BRIEF does not compose is reported, never
        # silently dropped.
        unsupported_sections = [
            s for s in (requested_sections or []) if s not in _ARTICLE_SECTIONS
        ]
        if unsupported_sections:
            base_warnings.append(
                "Sections not implemented by BRIEF and skipped: "
                + ", ".join(unsupported_sections)
                + "."
            )

        if not live:
            markdown = _no_compose_markdown(watchlist)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "markdown": markdown,
                    "articles": [],
                    "watchlist": watchlist,
                    "article_count": 0,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "cards": _cards(watchlist, 0, "off", positions_covered),
                    "watchlist_source": watchlist_source,
                    "next_actions": [
                        "Pass live=true (default) to compose the brief from real watchlist headlines.",
                    ],
                },
                sources=["watchlist_brief_builder"],
                warnings=[*base_warnings, "Live composition disabled (live=false); no headlines fetched."],
                metadata={"format": "markdown", "live": False, "data_mode": "off"},
            )

        if not watchlist:
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
                    "sections": [],
                    "unsupported_sections": unsupported_sections,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "cards": _cards(watchlist, 0, "input_error", positions_covered),
                    "next_actions": [
                        "Pass sections=top_stories, sections=watchlist, or both.",
                    ],
                },
                sources=["watchlist_brief_builder"],
                warnings=[*base_warnings, "No recognised article section requested."],
                metadata={"format": "markdown", "live": False, "data_mode": "explicit_unavailable"},
            )

        # ---- LIVE COMPOSITION (default) -------------------------------------
        # De-garbage 2026-06-01: the brief used to source its "watchlist news"
        # from ``READFunction`` — but READ is the saved-articles *reading-list*
        # CRUD store, not a live news fetcher, so a fresh user got zero stories.
        # It also read the cross-asset TOP leg via ``.get("articles"/"rows")``
        # while TOP actually emits its ranked headlines under ``items`` — so
        # even the working top-stories leg was dropped and the brief reported a
        # false ``provider_unavailable``. We now compose entirely from TOP, the
        # function that genuinely ranks live RSS/GDELT headlines: one general
        # macro pass plus one symbol-scoped pass per watchlist symbol (capped,
        # concurrent, best-effort), all read from the correct ``items`` key.
        from showme.engine.functions.news.top import TOPFunction  # local: avoid cycle
        from showme.finbert_analyzer import stamp_items

        articles: list[dict[str, Any]] = []
        sources: list[str] = []
        provider_errors: list[Any] = []
        warnings: list[str] = []

        def _items_of(res: Any) -> list[dict[str, Any]]:
            data = getattr(res, "data", None)
            if isinstance(data, dict):
                raw = data.get("items") or data.get("articles") or data.get("rows") or []
            else:
                raw = data or []
            return [item for item in raw if isinstance(item, dict)]

        top_fn = TOPFunction(self.deps)
        # General macro headlines + per-symbol watchlist headlines, concurrently.
        want_macro = "top_stories" in chosen_sections
        wl_symbols = watchlist[:_MAX_SYMBOL_SEARCHES] if "watchlist" in chosen_sections else []
        if "watchlist" in chosen_sections and len(watchlist) > len(wl_symbols):
            base_warnings.append(
                f"Symbol headlines searched for the first {len(wl_symbols)} of "
                f"{len(watchlist)} symbols."
            )
        per_symbol = max(3, min(limit // max(1, len(wl_symbols) + 1), 10))

        async def _macro() -> tuple[str, Any]:
            return "MACRO", await top_fn.execute(
                live=True, limit=min(limit, 15), timeout=timeout, stamp_sentiment=False,
            )

        async def _sym(sym: str) -> tuple[str, Any]:
            return sym, await top_fn.execute(
                symbol=sym, query=sym, live=True, limit=per_symbol, timeout=timeout, stamp_sentiment=False,
            )

        tasks = [*([_macro()] if want_macro else []), *[_sym(s) for s in wl_symbols]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        existing: set[str] = set()
        for res in results:
            if isinstance(res, BaseException):
                provider_errors.append(f"top: {type(res).__name__}: {res}")
                continue
            tag, top_res = res
            for item in _items_of(top_res):
                cleaned = _clean_article(item)
                key = _dedupe_key(cleaned)
                if key and key in existing:
                    continue
                cleaned["matched_symbol"] = tag
                cleaned["section"] = "top_stories" if tag == "MACRO" else "watchlist"
                articles.append(cleaned)
                if key:
                    existing.add(key)
            for src in getattr(top_res, "sources", []) or []:
                if src not in sources:
                    sources.append(src)
            for err in (getattr(top_res, "metadata", {}) or {}).get("provider_errors", []) or []:
                provider_errors.append(err)

        # BRIEF#3: ``limit`` caps each section separately, so a long watchlist
        # cannot push every top story out of the brief. Watchlist stories
        # are listed first, then macro top stories.
        watch_rows = [a for a in articles if a.get("section") == "watchlist"][:limit]
        macro_rows = [a for a in articles if a.get("section") == "top_stories"][:limit]
        articles = [*watch_rows, *macro_rows]

        # Stamp sentiment on the final merged list of articles once!
        _, finbert_warning = await stamp_items(articles)
        if finbert_warning:
            warnings.append(finbert_warning)
        warnings = [*base_warnings, *warnings]

        source_label = _SOURCE_LABELS.get(watchlist_source, "Watchlist")
        markdown = _compose_markdown(watchlist, articles, source_label, chosen_sections)
        status = "ok" if articles else "provider_unavailable"
        if not sources:
            sources = ["watchlist_brief_builder"]

        next_actions: list[str] = []
        if not articles:
            next_actions = [
                "Check RSS/news provider availability.",
                "Add watchlist symbols or broaden the query before generating a brief.",
            ]
            warnings.append("No live headlines returned from any news adapter.")

        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": status,
                "markdown": markdown,
                "articles": articles,
                "rows": articles,
                "watchlist": watchlist,
                "watchlist_source": watchlist_source,
                "symbols_searched": wl_symbols,
                "sections": chosen_sections,
                "unsupported_sections": unsupported_sections,
                "article_count": len(articles),
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "cards": _cards(
                    watchlist,
                    len(articles),
                    "live_official" if articles else "provider_unavailable",
                    positions_covered,
                ),
                "next_actions": next_actions,
            },
            sources=sources,
            warnings=warnings,
            metadata={
                "format": "markdown",
                "provider_errors": provider_errors,
                # R2 H-1: the live claim follows the payload — an empty
                # provider_unavailable envelope must not voucher live.
                "live": bool(articles),
                "data_mode": "live_official" if articles else "provider_unavailable",
                "as_of": datetime.now(timezone.utc).isoformat(),
            },
        )


_METHODOLOGY = (
    "BRIEF composes the briefing from existing surfaces — it does NOT call an LLM "
    "and does NOT fabricate prose. The watchlist is the input list when one is "
    "passed; otherwise it is the user's portfolio positions plus saved watchlists. "
    "With neither, status is needs_input and no news is fetched. It then calls "
    "TOP() once for cross-asset top news and once per watchlist "
    "symbol for symbol-scoped headlines (both reading TOP's ranked live RSS/GDELT "
    "items), de-duplicates by URL/title, and renders each headline as a markdown "
    "bullet whose link is the evidence cite. The structured `articles` array "
    "carries the same rows. When every news adapter is down, status is "
    "'provider_unavailable' and the body names the failure — the brief never "
    "invents a 'no news today, all quiet' summary."
)

_FIELD_DICTIONARY: dict[str, str] = {
    "status": "ok / empty / provider_unavailable.",
    "markdown": "Markdown rendering of the brief — every bullet links to its evidence row.",
    "articles": "Structured rows of the headlines cited in the markdown body.",
    "articles[].title": "Headline text quoted from the source.",
    "articles[].url": "Direct HTTPS link to the source article — the evidence cite.",
    "articles[].source": "Publisher / source name.",
    "articles[].matched_symbol": "Symbol this article was tagged to (MACRO for cross-asset TOP news).",
    "watchlist": "Effective watchlist used (input, or positions plus saved watchlists, plus instrument).",
    "watchlist_source": "input / positions_and_watchlists / instrument / none.",
    "symbols_searched": "Symbols that received a symbol-scoped headline search (capped).",
    "article_count": "Number of cited articles.",
    "sections": "Article sections composed (top_stories / watchlist).",
    "next_actions": "Suggested follow-up actions when no live headlines were returned.",
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
        errors.append(f"Portfolio positions unavailable: {type(exc).__name__}: {exc}")
    try:
        for entry in list_watchlists():
            watch_symbols.extend(entry.get("symbols") or [])
        watch_symbols = _normalise_symbols(watch_symbols)
    except Exception as exc:
        errors.append(f"Saved watchlists unavailable: {type(exc).__name__}: {exc}")
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
    """Coerce ``value`` to an int and clamp to [min_value, max_value].

    Mirrors the local ``_int_param`` helpers in read.py / top.py — kept inline
    so BRIEF has no dependency on a shared coercion module that may not exist
    in every checkout.
    """
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
    # BRIEF#5: TOP emits the article link as ``link``; the documented evidence
    # field is ``url``. Expose the same absolute link under both.
    link = str(cleaned.get("link") or "").strip()
    if not cleaned.get("url") and link.lower().startswith(("http://", "https://")):
        cleaned["url"] = link
    # BRIEF#5: RSS items carry the adapter tag ("rss") in ``source`` and the
    # publisher in ``publisher``. The documented ``source`` is the publisher.
    publisher = str(cleaned.get("publisher") or "").strip()
    if publisher and str(cleaned.get("source") or "").strip().lower() in ("", "rss"):
        cleaned["source"] = publisher
    for key in ("summary", "description", "snippet"):
        if isinstance(cleaned.get(key), str):
            cleaned[key] = _strip_html(cleaned[key])
    return cleaned


def _strip_html(value: str) -> str:
    # Unescape entities BEFORE stripping tags so an entity-encoded tag
    # (``&lt;script&gt;``) is not re-injected as live markup by a later
    # unescape. Matches cn._clean_html / news_intelligence.strip_markup order.
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compose_markdown(
    watchlist: list[str],
    articles: list[dict[str, Any]],
    source_label: str = "Watchlist",
    sections: list[str] | None = None,
) -> str:
    wanted = list(sections or _ARTICLE_SECTIONS)
    lines = [
        f"# ShowMe Daily Brief — {datetime.now(timezone.utc):%Y-%m-%d}",
        "",
        f"**{source_label}:** {', '.join(watchlist)}",
        "",
    ]
    if not articles:
        # BRIEF#3: with no rows, still honour ``sections`` -- each requested
        # section gets its own heading and an honest empty line, nothing else.
        empty_lines = {
            "watchlist": ("Watchlist", "- No live watchlist headlines were returned."),
            "top_stories": ("Top Stories", "- No live top-story headlines were returned."),
        }
        for key in ("watchlist", "top_stories"):
            if key not in wanted:
                continue
            heading, empty_line = empty_lines[key]
            lines.extend([f"## {heading}", "", empty_line, ""])
        lines.extend(
            [
                "## Next actions",
                "",
                "- Check RSS/news provider availability.",
                "- Add watchlist symbols or broaden the query before generating a brief.",
            ]
        )
        return "\n".join(lines)
    top_symbols = sorted(
        {
            str(a.get("matched_symbol") or a.get("symbol") or "")
            for a in articles
            if a.get("matched_symbol") or a.get("symbol")
        }
    )
    if top_symbols:
        lines.extend([f"**Matched symbols:** {', '.join(top_symbols[:10])}", ""])
    # BRIEF#3: each requested section gets its own heading; a section with no
    # rows says so instead of inheriting another section's stories.
    for key, heading in (("watchlist", "Watchlist"), ("top_stories", "Top Stories")):
        if key not in wanted:
            continue
        lines.extend([f"## {heading}", ""])
        rows = [a for a in articles if a.get("section") == key]
        if not rows:
            lines.extend(["- No headlines in this section.", ""])
            continue
        for a in rows:
            title = a.get("title", "")
            link = a.get("url") or a.get("link") or ""
            sym = a.get("matched_symbol") or a.get("symbol") or ""
            source = a.get("source") or a.get("publisher") or ""
            suffix = f" — {source}" if source else ""
            if link:
                lines.append(f"- ({sym}) [{title}]({link}){suffix}")
            else:
                lines.append(f"- ({sym}) {title}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


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
            "- Pass live=true (the default) to compose the brief from real headlines.",
        ]
    )
