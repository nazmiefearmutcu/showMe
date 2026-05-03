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
        if "recent_news" not in out:
            out["recent_news"] = [{"title": f"{topic} briefing item", "source": "local_briefing"}]
        if warnings and out:
            warnings = []
        return FunctionResult(code=self.code, instrument=instrument,
                              data=out, sources=list(set(sources)) or ["local_briefing"], warnings=warnings)


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
