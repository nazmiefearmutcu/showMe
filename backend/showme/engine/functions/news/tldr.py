"""TLDR — TL;DR portfolio + watchlist daily summary.

LLM-backed: pulls quotes + news for portfolio positions + watchlist
symbols, asks the cheapest LLM for a 5-bullet markdown summary.
Falls back to a deterministic template when no LLM is configured.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class TLDRFunction(BaseFunction):
    code = "TLDR"
    name = "Daily TL;DR"
    category = "news"
    description = "LLM-summarised portfolio + watchlist day in 5 bullets."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(3.0, min(float(params.get("timeout", 8)), 9.0))

        def _remaining(default: float, floor: float = 0.5) -> float:
            remaining = deadline - loop.time()
            if remaining <= floor:
                return 0.0
            return max(floor, min(float(default), remaining))

        symbols = _parse_symbols(params.get("symbols"))
        # Pull from PortfolioState if no list
        if not symbols:
            try:
                from showme.engine.portfolio.state import PortfolioState
                p = PortfolioState()
                p.import_legacy_crypto()
                symbols = [pos.instrument.symbol for pos in p.positions[:15]]
            except Exception:
                pass
        if not symbols:
            symbols = ["AAPL", "MSFT", "TSLA", "BTCUSDT", "EURUSD", "DGS10"]

        sources: list[str] = []
        warnings: list[str] = []

        # Quotes (best-effort) — BugHunt 2026-05-24:
        # TLDR previously walked deps.yfinance / deps.ccxt_failover with its
        # own DataRequest pipeline. That produced answers that disagreed with
        # /api/quote/<sym>: MSFT showed -0.79% on the quote endpoint but TLDR
        # reported "No live negative movers" because its provider chain
        # returned a stale close_prev or fell back to nothing. We now consume
        # the same fetch_quote_snapshot() helper that /api/quote uses so TLDR
        # cannot disagree with the headline ticker the user sees in WATCH.
        async def _quote(s: str) -> dict[str, Any]:
            try:
                from showme.quotes import QuoteFetchError, fetch_quote_snapshot
            except Exception:
                fetch_quote_snapshot = None  # type: ignore[assignment]
                QuoteFetchError = Exception  # type: ignore[assignment]
            quote_timeout = _remaining(float(params.get("quote_timeout", 3)), floor=0.75)
            if quote_timeout <= 0 or fetch_quote_snapshot is None:
                return {"symbol": s}
            try:
                snapshot = await asyncio.wait_for(
                    fetch_quote_snapshot(s),
                    timeout=min(quote_timeout, 3.5),
                )
            except Exception:
                return {"symbol": s}
            if not isinstance(snapshot, dict):
                return {"symbol": s}
            last = snapshot.get("last") if snapshot.get("last") is not None else snapshot.get("price")
            chg = snapshot.get("change_pct")
            if chg is None:
                chg = snapshot.get("regularMarketChangePercent")
            if chg is None:
                prev = snapshot.get("previous_close") or snapshot.get("previousClose")
                if last is not None and prev not in (None, 0):
                    try:
                        chg = (float(last) / float(prev) - 1.0) * 100.0
                    except Exception:
                        chg = None
            src_name = str(snapshot.get("source") or "showme_quote")
            return {
                "symbol": s,
                "last": last,
                "change_pct": chg,
                "quote_source": src_name,
            }
        try:
            quotes = await asyncio.wait_for(
                asyncio.gather(*(_quote(s) for s in symbols)),
                timeout=max(0.75, _remaining(float(params.get("quote_timeout", 3)), floor=0.75)),
            )
        except Exception:
            quotes = [{"symbol": s} for s in symbols]
            warnings.append("quotes: provider timeout")
        sources.append("yfinance")

        # Top news
        news_summary: list[str] = []
        try:
            news_timeout = _remaining(float(params.get("news_timeout", 3)), floor=0.75)
            if news_timeout <= 0:
                raise TimeoutError("no time remaining for top news")
            from showme.engine.functions.news.top import TOPFunction
            top = await asyncio.wait_for(
                TOPFunction(self.deps).execute(limit=12),
                timeout=news_timeout,
            )
            news_summary = [str(a.get("title", "")) for a in (top.data or [])[:8]]
            sources += list(top.sources or [])
        except Exception as e:
            warnings.append(f"top: {e}")

        # Today's economic events
        events: list[dict[str, Any]] = []
        try:
            eco_timeout = _remaining(float(params.get("eco_timeout", 2)), floor=0.75)
            if eco_timeout <= 0:
                raise TimeoutError("no time remaining for economic calendar")
            from showme.engine.functions.macro.eco import ECOFunction
            eco = await asyncio.wait_for(
                ECOFunction(self.deps).execute(),
                timeout=eco_timeout,
            )
            events = ((eco.data or [])[:10])
            sources += list(eco.sources or [])
        except Exception as e:
            warnings.append(f"eco: {e}")

        # LLM summary if available
        prose = ""
        summary_model = "local_deterministic_tldr_v2"
        try:
            llm_timeout = _remaining(float(params.get("llm_timeout", 2)), floor=0.75)
            if llm_timeout <= 0:
                raise TimeoutError("no time remaining for LLM summary")
            from showme.engine.agents.llm_router import LLMRequest, LLMRouter
            router = LLMRouter()
            ctx_text = (
                "Quotes:\n" + "\n".join(
                    f"  {q['symbol']}: {q.get('last','—')} ({q.get('change_pct')}%)"
                    for q in quotes
                ) +
                "\nNews:\n" + "\n".join(f"  - {h}" for h in news_summary[:6]) +
                "\nUpcoming events:\n" + "\n".join(
                    f"  - {e.get('Country','')} {e.get('Event','')}" for e in events[:6]
                )
            )
            req = LLMRequest(
                role="summarize",
                system="You are a concise market briefing summariser. Output Markdown with 5 bullet points: 1) market tone, 2) portfolio movers, 3) news themes, 4) upcoming risks, 5) action items.",
                user=ctx_text,
                max_tokens=600, temperature=0.3,
            )
            r = await asyncio.wait_for(
                router.complete(req),
                timeout=llm_timeout,
            )
            if r.text:
                prose = r.text
                summary_model = f"llm:{r.model}"
                sources.append(summary_model)
        except Exception as e:
            warnings.append(f"llm: {e}")

        has_live_content = (
            any(q.get("last") is not None or q.get("change_pct") is not None for q in quotes)
            or bool(news_summary)
            or bool(events)
            or bool(prose)
        )
        if not has_live_content:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "TLDR providers returned no usable quote, news, calendar, or LLM content within the latency budget.",
                    "markdown": "",
                    "quotes": quotes,
                    "news": news_summary,
                    "events": events,
                    "watchlist": symbols,
                    "next_actions": [
                        "Retry TLDR after quote/news providers recover.",
                        "Increase timeout/news_timeout/quote_timeout for an interactive summary.",
                    ],
                },
                sources=list(set(sources)) or ["showme_tldr"],
                metadata={"format": "markdown", "provider_errors": warnings},
                warnings=warnings,
            )

        # Fallback markdown
        if not prose:
            movers = [q for q in quotes if q.get("change_pct") is not None]
            ups_line = _format_movers(movers, positive=True)
            downs_line = _format_movers(movers, positive=False)
            prose = (
                f"# ShowMe TL;DR — {datetime.now(timezone.utc):%Y-%m-%d}\n\n"
                f"- **Top movers up:** {ups_line}"
                f"\n- **Top movers down:** {downs_line}"
                + "\n- **News themes:** " + "; ".join(news_summary[:3])
                + f"\n- **Calendar items:** {len(events)} scheduled."
                + "\n- **Summary engine:** local deterministic template; no LLM response was available in the latency budget."
                + "\n- **Action items:** review portfolio positions, scan ALRT log."
            )

        return FunctionResult(
            code=self.code, instrument=None,
            data={"markdown": prose, "quotes": quotes,
                   "news": news_summary, "events": events,
                   "watchlist": symbols, "summary_model": summary_model,
                   "quote_count": len([q for q in quotes if q.get("last") is not None]),
                   "mover_count": len([q for q in quotes if q.get("change_pct") is not None])},
            sources=list(set(sources)) or ["local_briefing_model"],
            metadata={"format": "markdown", "provider_errors": warnings, "summary_model": summary_model},
        )


def _parse_symbols(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip().upper() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    return []


def _format_movers(quotes: list[dict[str, Any]], *, positive: bool) -> str:
    if positive:
        rows = sorted(
            [q for q in quotes if (q.get("change_pct") or 0) > 0],
            key=lambda x: -(x["change_pct"] or 0),
        )[:3]
        empty = "No live positive movers returned by quote providers."
    else:
        rows = sorted(
            [q for q in quotes if (q.get("change_pct") or 0) < 0],
            key=lambda x: (x["change_pct"] or 0),
        )[:3]
        empty = "No live negative movers returned by quote providers."
    line = ", ".join(f"{q['symbol']} ({q['change_pct']:+.2f}%)" for q in rows)
    return line or empty
