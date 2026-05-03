"""BRIEF — Daily Newsletter (cron 06:00, AI summary placeholder)."""

from __future__ import annotations

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
        news_res = await read.execute(watchlist=watchlist)
        articles = news_res.data or []
        # Markdown brief
        lines = [
            f"# ShowMe Daily Brief — {datetime.utcnow():%Y-%m-%d}",
            "",
            f"**Watchlist:** {', '.join(watchlist)}",
            "",
            "## Top Stories",
            "",
        ]
        for a in articles[:25]:
            title = a.get("title", "")
            link = a.get("url") or a.get("link") or ""
            sym = a.get("matched_symbol", "")
            lines.append(f"- ({sym}) [{title}]({link})")
        markdown = "\n".join(lines)
        return FunctionResult(
            code=self.code, instrument=None, data=markdown,
            sources=news_res.sources, metadata={"format": "markdown"},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
