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


@FunctionRegistry.register
class BRIEFFunction(BaseFunction):
    code = "BRIEF"
    name = "Daily Brief"
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        watchlist = params.get("watchlist") or ["AAPL", "MSFT", "BTCUSDT"]
        if isinstance(watchlist, str):
            watchlist = [s.strip() for s in watchlist.split(",") if s.strip()]
        watchlist = [str(s).upper() for s in watchlist if str(s).strip()]
        if instrument and instrument.symbol and instrument.symbol.upper() not in watchlist:
            watchlist = [instrument.symbol.upper(), *watchlist]
        # ``live`` defaults to True (manifest default). It is now an OPT-OUT
        # toggle, not an opt-in: the brief composes from real surfaces by
        # default. Passing live=false explicitly is the only way to skip the
        # network composition — and even that returns an honest empty shape, not
        # the old fabricated template.
        live = _truthy(params.get("live_news"), params.get("live"), default=True)
        limit = _clamp_int(params.get("limit"), default=25, min_value=1, max_value=50)
        timeout = params.get("news_timeout", params.get("timeout", 8))

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
                    "cards": _cards(watchlist, 0, "off"),
                    "next_actions": [
                        "Pass live=true (default) to compose the brief from real watchlist headlines.",
                    ],
                },
                sources=["watchlist_brief_builder"],
                warnings=["Live composition disabled (live=false); no headlines fetched."],
                metadata={"format": "markdown", "live": False, "data_mode": "off"},
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
        wl_symbols = watchlist[:6]
        per_symbol = max(3, min(limit // max(1, len(wl_symbols) + 1), 10))

        async def _macro() -> tuple[str, Any]:
            return "MACRO", await top_fn.execute(live=True, limit=min(limit, 15), timeout=timeout)

        async def _sym(sym: str) -> tuple[str, Any]:
            return sym, await top_fn.execute(
                symbol=sym, query=sym, live=True, limit=per_symbol, timeout=timeout,
            )

        tasks = [_macro(), *[_sym(s) for s in wl_symbols]]
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

        # Surface watchlist-tagged stories first, then macro top stories.
        articles.sort(key=lambda a: 0 if a.get("section") == "watchlist" else 1)

        articles = articles[:limit]
        markdown = _compose_markdown(watchlist, articles)
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
                "article_count": len(articles),
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "cards": _cards(watchlist, len(articles), "live_official" if articles else "provider_unavailable"),
                "next_actions": next_actions,
            },
            sources=sources,
            warnings=warnings,
            metadata={
                "format": "markdown",
                "provider_errors": provider_errors,
                "live": True,
                "data_mode": "live_official" if articles else "provider_unavailable",
                "as_of": datetime.now(timezone.utc).isoformat(),
            },
        )


_METHODOLOGY = (
    "BRIEF composes the briefing from existing surfaces — it does NOT call an LLM "
    "and does NOT fabricate prose. It merges the input watchlist (or the default "
    "set), then calls TOP() once for cross-asset top news and once per watchlist "
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
    "watchlist": "Effective watchlist used (input + instrument).",
    "article_count": "Number of cited articles.",
    "next_actions": "Suggested follow-up actions when no live headlines were returned.",
}


def _cards(watchlist: list[str], article_count: int, data_mode: str) -> list[dict[str, Any]]:
    return [
        {"key": "article_count", "label": "Stories", "value": article_count},
        {"key": "watchlist_size", "label": "Watchlist", "value": len(watchlist)},
        {"key": "positions_covered", "label": "Positions", "value": len(watchlist)},
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


def _compose_markdown(watchlist: list[str], articles: list[dict[str, Any]]) -> str:
    lines = [
        f"# ShowMe Daily Brief — {datetime.now(timezone.utc):%Y-%m-%d}",
        "",
        f"**Watchlist:** {', '.join(watchlist)}",
        "",
        "## Top Stories",
        "",
    ]
    if articles:
        top_symbols = sorted(
            {
                str(a.get("matched_symbol") or a.get("symbol") or "")
                for a in articles
                if a.get("matched_symbol") or a.get("symbol")
            }
        )
        if top_symbols:
            lines.extend([f"**Matched symbols:** {', '.join(top_symbols[:10])}", ""])
        for a in articles:
            title = a.get("title", "")
            link = a.get("url") or a.get("link") or ""
            sym = a.get("matched_symbol") or a.get("symbol") or ""
            source = a.get("source") or a.get("publisher") or ""
            suffix = f" — {source}" if source else ""
            if link:
                lines.append(f"- ({sym}) [{title}]({link}){suffix}")
            else:
                lines.append(f"- ({sym}) {title}{suffix}")
    else:
        lines.extend(
            [
                "- No live watchlist headlines were returned.",
                "",
                "## Next actions",
                "",
                "- Check RSS/news provider availability.",
                "- Add watchlist symbols or broaden the query before generating a brief.",
            ]
        )
    return "\n".join(lines)


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
