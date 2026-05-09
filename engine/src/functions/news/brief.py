"""BRIEF — Daily Newsletter (cron 06:00, AI summary placeholder)."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.functions.news.read import READFunction


@FunctionRegistry.register
class BRIEFFunction(BaseFunction):
    code = "BRIEF"
    name = "Daily Brief"
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        watchlist = params.get("watchlist", ["AAPL", "MSFT", "BTCUSDT"])
        if isinstance(watchlist, str):
            watchlist = [s.strip() for s in watchlist.split(",") if s.strip()]
        if instrument and instrument.symbol not in watchlist:
            watchlist = [instrument.symbol, *watchlist]
        live = _truthy(params.get("live_news") or params.get("live"))
        if not live:
            markdown = _brief_template(watchlist)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=markdown,
                sources=["watchlist_brief_builder"],
                metadata={"format": "markdown", "live": False},
            )
        read = READFunction(self.deps)
        news_res = await read.execute(
            watchlist=watchlist,
            live=True,
            limit=int(params.get("limit", 25) or 25),
            timeout=params.get("news_timeout", params.get("timeout", 8)),
        )
        if isinstance(news_res.data, dict):
            articles = news_res.data.get("articles") or news_res.data.get("rows") or []
        else:
            articles = news_res.data or []
        articles = [_clean_article(item) for item in articles if isinstance(item, dict)]
        provider_errors = list(getattr(news_res, "metadata", {}).get("provider_errors", []) or [])
        # Markdown brief
        lines = [
            f"# ShowMe Daily Brief — {datetime.utcnow():%Y-%m-%d}",
            "",
            f"**Watchlist:** {', '.join(watchlist)}",
            "",
            "## Top Stories",
            "",
        ]
        if articles:
            top_symbols = sorted({str(a.get("matched_symbol") or a.get("symbol") or "") for a in articles if a.get("matched_symbol") or a.get("symbol")})
            if top_symbols:
                lines.extend(["", f"**Matched symbols:** {', '.join(top_symbols[:10])}", ""])
        for a in articles[:25]:
            title = a.get("title", "")
            link = a.get("url") or a.get("link") or ""
            sym = a.get("matched_symbol", "")
            source = a.get("source") or a.get("publisher") or ""
            suffix = f" — {source}" if source else ""
            lines.append(f"- ({sym}) [{title}]({link}){suffix}")
        if not articles:
            lines.extend([
                "- No live watchlist headlines were returned.",
                "",
                "## Next actions",
                "",
                "- Check RSS/news provider availability.",
                "- Add watchlist symbols or broaden the query before generating a brief.",
            ])
        markdown = "\n".join(lines)
        status = "ok" if articles else "provider_unavailable"
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "status": status,
                "markdown": markdown,
                "articles": articles[:25],
                "watchlist": watchlist,
                "article_count": len(articles),
                "next_actions": [] if articles else [
                    "Check RSS/news provider availability.",
                    "Add watchlist symbols or broaden the query before generating a brief.",
                ],
            },
            sources=news_res.sources,
            metadata={"format": "markdown", "provider_errors": provider_errors, "live": True},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _clean_article(article: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(article)
    for key in ("summary", "description", "snippet"):
        if isinstance(cleaned.get(key), str):
            cleaned[key] = _strip_html(cleaned[key])
    return cleaned


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _brief_template(watchlist: list[str]) -> str:
    symbols = [str(s).upper() for s in watchlist[:8]] or ["AAPL", "BTCUSDT"]
    lines = [
        f"# ShowMe Daily Brief - {datetime.utcnow():%Y-%m-%d}",
        "",
        f"**Watchlist:** {', '.join(symbols)}",
        "",
        "## Top Stories",
        "",
        f"- ({symbols[0]}) Market monitor is online and returning continuity coverage.",
        "- (MACRO) Rate, inflation, and liquidity calendar checks are ready.",
        "- (RISK) Portfolio and cross-asset risk panels are available without live-provider blocking.",
    ]
    if len(symbols) > 1:
        lines.append(f"- ({symbols[1]}) Secondary symbol included in the daily scan.")
    return "\n".join(lines)
