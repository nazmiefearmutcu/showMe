"""TSAR — Transcript Search (AlphaSense-style FTS over earnings transcripts)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.services import transcripts_archive as archive


@FunctionRegistry.register
class TSARFunction(BaseFunction):
    code = "TSAR"
    name = "Transcript Search"
    category = "news"
    description = "Search across stored earnings call transcripts (FTS5)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "search").lower()
        if action == "stats":
            return FunctionResult(code=self.code, instrument=None,
                                  data=archive.stats())
        if action == "list":
            sym = params.get("symbol") or (instrument.symbol if instrument else None)
            if not sym:
                return FunctionResult(code=self.code, instrument=None, data={"items": []})
            try:
                items = await asyncio.wait_for(
                    asyncio.to_thread(archive.list_for_symbol, sym, limit=int(params.get("limit", 50))),
                    timeout=float(params.get("timeout", 8)),
                )
            except Exception:
                items = [{"symbol": sym, "status": "archive_unavailable"}]
            return FunctionResult(code=self.code, instrument=instrument,
                                  data={"items": items})
        if action == "ingest":
            # Session-14 bug fix: action=ingest used to KeyError when `symbol`
            # was missing — the function would 500 instead of returning a
            # labelled input_required payload. Guard required params and emit
            # the same shape every other action uses.
            symbol_param = params.get("symbol") or (instrument.symbol if instrument else None)
            if not symbol_param:
                return FunctionResult(
                    code=self.code,
                    instrument=instrument,
                    data={
                        "status": "input_required",
                        "reason": "Transcript ingest requires a symbol.",
                        "next_actions": ["Pass `symbol` (or focus an instrument) before action=ingest."],
                    },
                    sources=["transcripts_archive"],
                    metadata={"provider_errors": ["missing ingest symbol"]},
                )
            tid = archive.upsert(
                symbol=str(symbol_param), company=params.get("company"),
                quarter=params.get("quarter"), fiscal_year=params.get("fiscal_year"),
                event_date=params.get("event_date"), source=params.get("source"),
                url=params.get("url"), content=params.get("content", ""),
                summary=params.get("summary"), sentiment=params.get("sentiment"),
            )
            return FunctionResult(code=self.code, instrument=None,
                                  data={"id": tid, "ingested": True})
        if action == "get":
            row_id = _safe_int(params.get("id"))
            if row_id is None:
                return FunctionResult(
                    code=self.code, instrument=None,
                    data={"status": "input_required",
                          "reason": "action=get requires a numeric `id`.",
                          "next_actions": ["Pass id=<row id> in params."]},
                    sources=["transcripts_archive"],
                )
            return FunctionResult(code=self.code, instrument=None,
                                  data=archive.get(row_id) or {})
        if action == "delete":
            row_id = _safe_int(params.get("id"))
            if row_id is None:
                return FunctionResult(
                    code=self.code, instrument=None,
                    data={"status": "input_required",
                          "reason": "action=delete requires a numeric `id`.",
                          "next_actions": ["Pass id=<row id> in params."]},
                    sources=["transcripts_archive"],
                )
            ok = archive.delete(row_id)
            return FunctionResult(code=self.code, instrument=None,
                                  data={"deleted": ok})
        # default: search
        query = params.get("query") or params.get("q") or ""
        sym = params.get("symbol") or (instrument.symbol if instrument else None)
        if not str(query).strip():
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_required",
                    "reason": "Transcript Search needs a search query.",
                    "query": query,
                    "items": [],
                    "next_actions": ["Enter keywords such as revenue, margin, guidance, or risk."],
                },
                sources=["transcripts_archive"],
                metadata={"provider_errors": ["missing transcript search query"]},
            )
        try:
            items = await asyncio.wait_for(
                asyncio.to_thread(
                    archive.search,
                    query,
                    symbol=sym,
                    limit=int(params.get("limit", 25)),
                ),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception:
            items = [{"symbol": sym, "query": query, "status": "archive_unavailable"}]
        if not items:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": f"No stored transcript matches found for '{query}'.",
                    "query": query,
                    "items": [],
                    "next_actions": [
                        "Ingest transcripts first with action=ingest.",
                        "Try a broader query or provide a symbol with archived transcripts.",
                    ],
                },
                sources=["transcripts_archive"],
                metadata={"provider_errors": ["transcript archive returned no matches"]},
            )
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"query": query, "items": items},
                              sources=["transcripts_archive"])


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
