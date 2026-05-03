"""TLDR — TL;DR portfolio + watchlist daily summary.

LLM-backed: pulls quotes + news for portfolio positions + watchlist
symbols, asks the cheapest LLM for a 5-bullet markdown summary.
Falls back to a deterministic template when no LLM is configured.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


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

        symbols = list(params.get("symbols") or [])
        # Pull from PortfolioState if no list
        if not symbols:
            try:
                from src.portfolio.state import PortfolioState
                p = PortfolioState()
                p.import_legacy_crypto()
                symbols = [pos.instrument.symbol for pos in p.positions[:15]]
            except Exception:
                pass
        if not symbols:
            symbols = ["AAPL", "MSFT", "TSLA", "BTCUSDT", "EURUSD", "DGS10"]

        sources: list[str] = []
        warnings: list[str] = []

        # Quotes (best-effort)
        async def _quote(s: str) -> dict[str, Any]:
            try:
                from src.core.base_data_source import DataKind, DataRequest
                quote_timeout = _remaining(float(params.get("quote_timeout", 3)), floor=0.75)
                if quote_timeout <= 0:
                    return {"symbol": s}
                inst = None
                if self.deps.symbol_registry:
                    inst = await asyncio.wait_for(
                        self.deps.symbol_registry.resolve(s),
                        timeout=min(quote_timeout, 1.5),
                    )
                if not inst:
                    inst = Instrument(symbol=s, asset_class=AssetClass.EQUITY)
                src = self.deps.yfinance if inst.asset_class.value != "CRYPTO" else None
                if src is None:
                    return {"symbol": s}
                q = await asyncio.wait_for(
                    src.fetch(
                        DataRequest(
                            kind=DataKind.QUOTE,
                            instrument=inst,
                            extra={"timeout": min(quote_timeout, 3.0)},
                        )
                    ),
                    timeout=min(quote_timeout, 3.5),
                )
                last = q.last; prev = q.close_prev
                chg_pct = ((last or 0) / (prev or 1) - 1) * 100 if prev else None
                return {"symbol": s, "last": last, "change_pct": chg_pct}
            except Exception:
                return {"symbol": s}
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
            from src.functions.news.top import TOPFunction
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
            from src.functions.macro.eco import ECOFunction
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
        try:
            llm_timeout = _remaining(float(params.get("llm_timeout", 2)), floor=0.75)
            if llm_timeout <= 0:
                raise TimeoutError("no time remaining for LLM summary")
            from src.agents.llm_router import LLMRequest, LLMRouter
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
                sources.append(f"llm:{r.model}")
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
            ups = sorted([q for q in quotes if q.get("change_pct") is not None],
                          key=lambda x: -(x["change_pct"] or 0))[:3]
            downs = sorted([q for q in quotes if q.get("change_pct") is not None],
                            key=lambda x: (x["change_pct"] or 0))[:3]
            prose = (
                f"# ShowMe TL;DR — {datetime.utcnow():%Y-%m-%d}\n\n"
                f"- **Top movers up:** "
                + ", ".join(f"{q['symbol']} ({q['change_pct']:+.2f}%)" for q in ups)
                + "\n- **Top movers down:** "
                + ", ".join(f"{q['symbol']} ({q['change_pct']:+.2f}%)" for q in downs)
                + "\n- **News themes:** " + "; ".join(news_summary[:3])
                + f"\n- **Calendar items:** {len(events)} scheduled."
                + "\n- **Action items:** review portfolio positions, scan ALRT log."
            )

        return FunctionResult(
            code=self.code, instrument=None,
            data={"markdown": prose, "quotes": quotes,
                   "news": news_summary, "events": events,
                   "watchlist": symbols},
            sources=list(set(sources)) or ["local_briefing_model"],
            metadata={"format": "markdown", "provider_errors": warnings},
        )
