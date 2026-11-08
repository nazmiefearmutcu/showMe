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

        sources: list[str] = []
        warnings: list[str] = []

        symbols = _parse_symbols(params.get("symbols"))
        watchlist_source = "explicit" if symbols else ""
        # No explicit list: the user's own holdings are the scope. No invented
        # default watchlist is substituted when there are no holdings.
        if not symbols:
            try:
                from showme.engine.portfolio.state import PortfolioState
                p = PortfolioState()
                p.import_legacy_crypto()
                symbols = [pos.instrument.symbol for pos in p.positions[:15]]
                watchlist_source = "portfolio" if symbols else "portfolio_empty"
            except Exception as exc:
                watchlist_source = "portfolio_unavailable"
                warnings.append(f"portfolio: {str(exc) or type(exc).__name__}")

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
        # Provenance: cite the quote sources that actually answered, not a fixed name.
        sources += sorted({str(q["quote_source"]) for q in quotes if q.get("quote_source")})

        # Top news. TOP answers with a dict envelope {items, alerts, status}.
        news_summary: list[str] = []
        news_rows: list[dict[str, Any]] = []
        news_status = "unavailable"
        news_reason = "no response"
        try:
            news_timeout = _remaining(float(params.get("news_timeout", 3)), floor=0.75)
            if news_timeout <= 0:
                raise TimeoutError("no time remaining for top news")
            from showme.engine.functions.news.top import TOPFunction
            top = await asyncio.wait_for(
                TOPFunction(self.deps).execute(limit=12),
                timeout=news_timeout,
            )
            items, news_reason = _payload_rows(top, "items")
            news_rows = items[:8]
            news_summary = [str(a.get("title", "")) for a in news_rows]
            if news_reason:
                news_status = "unavailable"
            else:
                news_status = "ok" if news_summary else "empty"
            sources += list(top.sources or [])
        except Exception as e:
            news_reason = str(e) or type(e).__name__
            warnings.append(f"top: {str(e) or type(e).__name__}")

        # Today's economic events. ECO answers with a dict envelope whose rows
        # live under "events". A failed call is "unavailable", never a zero count.
        events: list[dict[str, Any]] = []
        calendar_total = 0
        calendar_status = "unavailable"
        calendar_reason = "no response"
        try:
            eco_timeout = _remaining(float(params.get("eco_timeout", 2)), floor=0.75)
            if eco_timeout <= 0:
                raise TimeoutError("no time remaining for economic calendar")
            from showme.engine.functions.macro.eco import ECOFunction
            eco = await asyncio.wait_for(
                ECOFunction(self.deps).execute(),
                timeout=eco_timeout,
            )
            rows, calendar_reason = _payload_rows(eco, "events")
            # The count is the real row total; only the listed events are capped.
            calendar_total = len(rows)
            events = rows[:10]
            if calendar_reason:
                calendar_status = "unavailable"
            else:
                calendar_status = "ok"
            sources += list(eco.sources or [])
        except Exception as e:
            calendar_reason = str(e) or type(e).__name__
            warnings.append(f"eco: {str(e) or type(e).__name__}")

        # Structured bullets, each cited to the evidence rows it was built from.
        # Built deterministically from the rows above, so they exist with or
        # without an LLM. A candidate without evidence is omitted, never invented.
        bullet_limit = _clamp_int(params.get("bullets"), default=5, low=3, high=8)
        evidence_limit = _clamp_int(params.get("evidence_per_bullet"), default=2, low=1, high=5)
        bullets = _compose_bullets(
            symbols=symbols,
            quotes=quotes,
            news_rows=news_rows,
            news_status=news_status,
            events=events,
            calendar_total=calendar_total,
            calendar_status=calendar_status,
            bullet_limit=bullet_limit,
            evidence_limit=evidence_limit,
        )

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
                    f"  - {e.get('country') or ''} {e.get('event') or ''}" for e in events[:6]
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
                    "bullets": [],
                    "symbols": symbols,
                    "news_status": news_status,
                    "calendar_status": calendar_status,
                    "watchlist": symbols,
                    "watchlist_source": watchlist_source,
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
            if not symbols:
                ups_line = downs_line = "no holdings or symbols to rank (pass a symbol list)."
            if news_summary:
                news_line = "; ".join(news_summary[:3])
            elif news_status == "empty":
                news_line = "no headlines returned."
            else:
                news_line = f"unavailable ({news_reason})."
            if calendar_status == "ok":
                calendar_line = f"{calendar_total} scheduled."
            else:
                calendar_line = f"unavailable ({calendar_reason}); not a zero count."
            prose = (
                f"# ShowMe TL;DR — {datetime.now(timezone.utc):%Y-%m-%d}\n\n"
                f"- **Top movers up:** {ups_line}"
                f"\n- **Top movers down:** {downs_line}"
                + "\n- **News themes:** " + news_line
                + f"\n- **Calendar items:** {calendar_line}"
                + "\n- **Summary engine:** local deterministic template; no LLM response was available in the latency budget."
            )

        return FunctionResult(
            code=self.code, instrument=None,
            data={"status": "ok", "markdown": prose, "quotes": quotes,
                   "news": news_summary, "events": events,
                   "bullets": bullets, "bullet_limit": bullet_limit,
                   "evidence_per_bullet": evidence_limit,
                   "composer_mode": "extractive",
                   "symbols": symbols,
                   "calendar_total": calendar_total,
                   "news_status": news_status, "news_reason": news_reason,
                   "calendar_status": calendar_status, "calendar_reason": calendar_reason,
                   "watchlist": symbols, "watchlist_source": watchlist_source,
                   "summary_model": summary_model,
                   "quote_count": len([q for q in quotes if q.get("last") is not None]),
                   "mover_count": len([q for q in quotes if q.get("change_pct") is not None])},
            sources=list(set(sources)) or ["local_briefing_model"],
            metadata={"format": "markdown", "provider_errors": warnings, "summary_model": summary_model},
        )


def _payload_rows(result: Any, key: str) -> tuple[list[dict[str, Any]], str]:
    """Rows from a sibling function result, plus an unavailable reason ("" when usable).

    TOP and ECO return dict envelopes ({items|events, status, ...}); a list
    payload is accepted as-is. A non-ok status is reported, never read as zero rows.
    """
    data = getattr(result, "data", None)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)], ""
    if not isinstance(data, dict):
        return [], "unexpected payload"
    status = str(data.get("status") or "ok")
    if status not in {"ok", "empty"}:
        return [], str(data.get("reason") or status)
    rows = data.get(key)
    if not isinstance(rows, list):
        return [], f"missing '{key}' rows"
    return [row for row in rows if isinstance(row, dict)], ""


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


def _clamp_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: int(float("inf")) raises it, not ValueError.
        return default
    return max(low, min(high, number))


def _http_links(*candidates: Any) -> list[str]:
    links: list[str] = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text.lower().startswith(("http://", "https://")) and text not in links:
            links.append(text)
    return links


def _compose_bullets(
    *,
    symbols: list[str],
    quotes: list[dict[str, Any]],
    news_rows: list[dict[str, Any]],
    news_status: str,
    events: list[dict[str, Any]],
    calendar_total: int,
    calendar_status: str,
    bullet_limit: int,
    evidence_limit: int,
) -> list[dict[str, Any]]:
    """Bullets built only from evidence rows that were actually returned.

    Each bullet lists its ``evidence`` rows, ``evidence_count`` and the HTTP(S)
    ``evidence_links`` those rows carry. Quote and calendar rows carry no per-row
    URL today, so their bullets have an empty ``evidence_links``. A candidate with
    no evidence rows is omitted rather than filled in.
    """
    candidates: list[tuple[str, list[dict[str, Any]], list[str], list[str]]] = []

    def _quote_row(q: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "quote",
            "symbol": q.get("symbol"),
            "last": q.get("last"),
            "change_pct": q.get("change_pct"),
            "source": q.get("quote_source"),
            "evidence_links": [],
        }

    movers = [q for q in quotes if q.get("change_pct") is not None]
    ups = sorted((q for q in movers if q["change_pct"] > 0), key=lambda q: -q["change_pct"])
    downs = sorted((q for q in movers if q["change_pct"] < 0), key=lambda q: q["change_pct"])
    if ups:
        cited = ups[:evidence_limit]
        text = "Top movers up: " + ", ".join(f"{q['symbol']} ({q['change_pct']:+.2f}%)" for q in cited)
        candidates.append((text, [_quote_row(q) for q in cited], [], [q["symbol"] for q in cited]))
    if downs:
        cited = downs[:evidence_limit]
        text = "Top movers down: " + ", ".join(f"{q['symbol']} ({q['change_pct']:+.2f}%)" for q in cited)
        candidates.append((text, [_quote_row(q) for q in cited], [], [q["symbol"] for q in cited]))

    answered = [q for q in quotes if q.get("last") is not None or q.get("change_pct") is not None]
    if symbols and answered:
        answered_symbols = {str(q.get("symbol")) for q in answered}
        missing = [s for s in symbols if s not in answered_symbols]
        text = f"Quotes returned for {len(answered)} of {len(symbols)} symbols"
        if missing:
            text += "; no quote for " + ", ".join(missing[:5])
        cited = answered[:evidence_limit]
        candidates.append((text + ".", [_quote_row(q) for q in cited], [], [str(q["symbol"]) for q in cited]))

    if news_status == "ok" and news_rows:
        cited_news = news_rows[:evidence_limit]
        text = "News themes: " + "; ".join(str(a.get("title", "")) for a in cited_news)
        rows: list[dict[str, Any]] = []
        links: list[str] = []
        for a in cited_news:
            row_links = _http_links(a.get("url"), a.get("link"))
            links.extend(link for link in row_links if link not in links)
            rows.append({
                "kind": "news",
                "title": str(a.get("title", "")),
                "source": a.get("source") or a.get("publisher") or None,
                "evidence_links": row_links,
            })
        candidates.append((text, rows, links, []))

    if calendar_status == "ok" and events:
        cited_events = events[:evidence_limit]
        names = [
            " ".join(str(part) for part in (e.get("country") or e.get("Country"), e.get("event") or e.get("Event")) if part)
            for e in cited_events
        ]
        text = f"Calendar items: {calendar_total} scheduled; " + "; ".join(n for n in names if n)
        rows = [
            {
                "kind": "calendar",
                "country": e.get("country") or e.get("Country"),
                "event": e.get("event") or e.get("Event"),
                "evidence_links": [],
            }
            for e in cited_events
        ]
        candidates.append((text, rows, [], []))

    bullets: list[dict[str, Any]] = []
    for text, rows, links, bullet_symbols in candidates:
        if not rows:
            continue
        bullets.append({
            "position": len(bullets) + 1,
            "bullet_text": text,
            "symbols": bullet_symbols,
            "evidence_count": len(rows),
            "evidence_links": links,
            "evidence": rows,
        })
        if len(bullets) >= bullet_limit:
            break
    return bullets
