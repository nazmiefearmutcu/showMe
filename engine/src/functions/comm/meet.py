"""MEET — Meeting briefing.

Topluyor:
  - Notion search (kişi/şirket adı geçen page'ler)
  - Granola lokal son toplantı notları
  - PORT karşılığı pozisyon (eğer şirket portföyde varsa)
  - TOP haber (son 24h)
  - DES kısa özet (varlık equity ise)
  - Optional: SOSC sentiment

Çıktı: tek bir briefing JSON. UI sayfası ``/meeting``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.functions.comm.peop import reference_people_search


@FunctionRegistry.register
class MEETFunction(BaseFunction):
    code = "MEET"
    name = "Meeting Briefing"
    category = "comm"
    description = "Pre-meeting briefing — Notion + Granola + portfolio + news + DES."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        topic = params.get("topic") or params.get("query") or params.get("symbol") or (instrument.symbol if instrument else "")
        if not topic:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=["topic / instrument required"])
        if not _truthy(params.get("live_meeting") or params.get("live")):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_meeting_template(topic, instrument),
                sources=["local_briefing"],
                metadata={"live": False},
            )
        sources: list[str] = []
        warnings: list[str] = []
        out: dict[str, Any] = {"topic": topic}

        async def _safe(coro, key, source_name):
            try:
                out[key] = await asyncio.wait_for(coro, timeout=float(params.get("timeout", 8)))
                sources.append(source_name)
            except Exception as e:
                warnings.append(f"{source_name}: {e}")

        tasks = []
        if self.deps.notion:
            tasks.append(_safe(self.deps.notion.search(topic, page_size=10),
                                "notion_pages", "notion"))
        if self.deps.granola:
            tasks.append(_safe(self.deps.granola.list_recent(15),
                                "granola_recent", "granola"))
        if self.deps.gdelt:
            from src.core.base_data_source import DataKind, DataRequest
            tasks.append(_safe(self.deps.gdelt.fetch(DataRequest(
                kind=DataKind.NEWS,
                extra={"query": topic},
                start=datetime.utcnow() - timedelta(days=2),
                limit=10,
            )), "recent_news", "gdelt"))
        # DES if instrument is equity
        if instrument and instrument.asset_class.value in ("EQUITY", "ETF"):
            from src.functions.equity.des import DESFunction
            try:
                des = await DESFunction(self.deps).execute(instrument)
                if des.data:
                    rd = des.data
                    out["company"] = {
                        "name": getattr(rd, "name", None),
                        "sector": getattr(rd, "sector", None),
                        "industry": getattr(rd, "industry", None),
                        "market_cap": getattr(rd, "market_cap", None),
                        "ceo": getattr(rd, "ceo", None),
                        "website": getattr(rd, "website", None),
                    }
                    sources.append("yfinance")
            except Exception as e:
                warnings.append(f"des: {e}")
            # Portfolio match
            try:
                from src.portfolio.state import PortfolioState
                p = PortfolioState()
                p.import_legacy_crypto()
                pos = next((x for x in p.positions
                             if x.instrument.symbol.upper() == instrument.symbol.upper()), None)
                if pos:
                    out["portfolio_position"] = {
                        "symbol": pos.instrument.symbol,
                        "quantity": pos.quantity, "avg_cost": pos.avg_cost,
                        "currency": pos.currency,
                    }
            except Exception:
                pass
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        people = reference_people_search(str(topic), limit=int(params.get("people_limit", 6)))
        if people:
            out["participants"] = people
            sources.append("people_public_reference")

        recent_news = _normalise_news(out.get("recent_news"))
        out["recent_news"] = recent_news
        out["meeting_date"] = str(params.get("date") or datetime.utcnow().date().isoformat())
        out["connection_status"] = [
            {"source": "notion", "status": "configured" if self.deps.notion else "not_configured"},
            {"source": "granola", "status": "configured" if self.deps.granola else "not_configured"},
            {"source": "gdelt", "status": "configured" if self.deps.gdelt else "not_configured"},
            {"source": "people_public_reference", "status": "used" if people else "no_match"},
        ]
        out["rows"] = _briefing_rows(topic, people, recent_news, out)
        out["briefing_sections"] = [
            {"section": "participants", "status": "ready" if people else "needs_data", "count": len(people)},
            {"section": "meeting_notes", "status": "ready" if out.get("granola_recent") else "not_configured_or_empty", "count": len(out.get("granola_recent") or [])},
            {"section": "news", "status": "ready" if recent_news else "not_available", "count": len(recent_news)},
            {"section": "portfolio", "status": "ready" if out.get("portfolio_position") else "not_linked", "count": 1 if out.get("portfolio_position") else 0},
        ]
        out["questions"] = [
            "What changed since the last meeting or review?",
            "Which person owns the next follow-up?",
            "What market, portfolio, or product risk should be raised?",
        ]
        out["methodology"] = (
            "MEET builds a meeting brief from configured connectors plus local/public reference context. "
            "Missing connectors are shown in connection_status instead of being replaced with fake notes."
        )
        out["field_dictionary"] = {
            "participants": "People matched from local directory or public reference sources.",
            "connection_status": "Whether Notion, Granola, news, and people sources were available.",
            "rows": "Briefing table grouped by participant, notes, news, and portfolio sections.",
        }
        return FunctionResult(code=self.code, instrument=instrument,
                              data=out, sources=list(dict.fromkeys(sources)) or ["meeting_briefing"], warnings=warnings)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _meeting_template(topic: str, instrument: Instrument | None) -> dict[str, Any]:
    symbol = instrument.symbol if instrument else topic
    asset_class = instrument.asset_class.value if instrument else "UNKNOWN"
    return {
        "topic": topic,
        "agenda": [
            {"item": "market_context", "status": "ready"},
            {"item": "recent_developments", "status": "ready"},
            {"item": "portfolio_exposure", "status": "ready"},
        ],
        "company": {
            "symbol": symbol,
            "asset_class": asset_class,
            "name": topic,
            "sector": "Market",
            "industry": "Cross-asset",
        },
        "recent_news": [
            {"title": f"{topic} market briefing", "source": "local_briefing"},
            {"title": f"{topic} risk and catalyst checklist", "source": "local_briefing"},
        ],
        "portfolio_position": {
            "symbol": symbol,
            "quantity": 0,
            "avg_cost": None,
            "currency": instrument.currency if instrument else "USD",
        },
        "questions": [
            "What changed since the last review?",
            "Which market drivers matter most now?",
            "What action or follow-up is required?",
        ],
    }


def _normalise_news(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        try:
            value = value.to_dict("records")
        except Exception:
            value = []
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value[:10]:
        if isinstance(item, dict):
            title = item.get("title") or item.get("headline") or item.get("name")
            if not title:
                continue
            out.append({
                "title": title,
                "source": item.get("source") or item.get("provider") or "news",
                "published_at": item.get("published_at") or item.get("date"),
                "url": item.get("url"),
            })
    return out


def _briefing_rows(
    topic: Any,
    people: list[dict[str, Any]],
    recent_news: list[dict[str, Any]],
    out: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for person in people:
        rows.append({
            "section": "participant",
            "name": person.get("full_name"),
            "role": person.get("role"),
            "company": person.get("company"),
            "status": person.get("contact_status", "public_profile_only"),
            "source": person.get("source"),
            "source_url": person.get("source_url"),
        })
    notes = out.get("granola_recent") or []
    if isinstance(notes, list) and notes:
        for note in notes[:5]:
            rows.append({
                "section": "meeting_note",
                "title": note.get("title") if isinstance(note, dict) else str(note),
                "status": "ready",
                "source": "granola",
            })
    else:
        rows.append({
            "section": "meeting_note",
            "title": "No recent Granola notes returned",
            "status": "not_configured_or_empty",
            "source": "granola",
        })
    if recent_news:
        for item in recent_news[:5]:
            rows.append({
                "section": "news",
                "title": item.get("title"),
                "published_at": item.get("published_at"),
                "status": "ready",
                "source": item.get("source"),
                "url": item.get("url"),
            })
    else:
        rows.append({
            "section": "news",
            "title": f"No recent live news returned for {topic}",
            "status": "not_available",
            "source": "news",
        })
    if out.get("portfolio_position"):
        rows.append({
            "section": "portfolio",
            **out["portfolio_position"],
            "status": "linked",
        })
    else:
        rows.append({
            "section": "portfolio",
            "title": "No matching portfolio position found",
            "status": "not_linked",
            "source": "portfolio_state",
        })
    return rows
