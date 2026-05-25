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
            ingest_warnings: list[str] = []
            ingest_sources: list[str] = ["transcripts_archive"]
            content = params.get("content") or ""
            # If no transcript text was supplied but the caller pointed us
            # at audio, run Whisper large-v3 (via the legacy service entry,
            # which itself prefers the singleton) before persisting.
            if not content and (params.get("audio_url") or params.get("audio_path")):
                try:
                    from showme.whisper_analyzer import WhisperAnalyzer  # noqa: PLC0415
                    if not WhisperAnalyzer.is_available() and WhisperAnalyzer.load_error() is None:
                        ingest_warnings.append(
                            "whisper: large-v3 not yet warmed, retry in ~30s"
                        )
                except Exception:  # noqa: BLE001 - singleton optional
                    pass
                if params.get("audio_url"):
                    try:
                        from showme.engine.services.transcription import transcribe_url
                        w = await asyncio.wait_for(
                            transcribe_url(
                                params["audio_url"],
                                language=params.get("language"),
                                model_name=params.get("model", "base"),
                            ),
                            timeout=float(params.get("transcribe_timeout", 30)),
                        )
                        content = w.get("text") or ""
                        if content:
                            ingest_sources.append("whisper")
                    except Exception as exc:  # noqa: BLE001
                        ingest_warnings.append(f"transcribe_url: {exc}")
                if not content and params.get("audio_path"):
                    try:
                        from showme.engine.services.transcription import transcribe
                        w = await asyncio.wait_for(
                            transcribe(
                                params["audio_path"],
                                language=params.get("language"),
                                model_name=params.get("model", "base"),
                            ),
                            timeout=float(params.get("transcribe_timeout", 30)),
                        )
                        content = w.get("text") or ""
                        if content:
                            ingest_sources.append("whisper")
                    except Exception as exc:  # noqa: BLE001
                        ingest_warnings.append(f"transcribe: {exc}")
            # Optionally stamp FinBert sentiment when the caller didn't
            # supply one and we have transcript text to analyse. We pick
            # the first 512 chars (FinBert's headline window) — full
            # earnings calls are too long for one inference pass but the
            # prepared-remarks intro carries the headline tone.
            sentiment = params.get("sentiment")
            if sentiment is None and content:
                try:
                    from showme.finbert_analyzer import FinBertAnalyzer  # noqa: PLC0415
                    analyzer = await asyncio.to_thread(FinBertAnalyzer.instance)
                    result = await analyzer.label(content[:512])
                    sentiment = float(result.get("score_signed") or 0.0)
                    ingest_sources.append("finbert")
                except Exception as exc:  # noqa: BLE001 - non-fatal
                    ingest_warnings.append(f"finbert: {exc.__class__.__name__}")
            tid = archive.upsert(
                symbol=str(symbol_param), company=params.get("company"),
                quarter=params.get("quarter"), fiscal_year=params.get("fiscal_year"),
                event_date=params.get("event_date"), source=params.get("source"),
                url=params.get("url"), content=content,
                summary=params.get("summary"), sentiment=sentiment,
            )
            return FunctionResult(
                code=self.code, instrument=None,
                data={
                    "id": tid,
                    "ingested": True,
                    "chars": len(content),
                    "sentiment": sentiment,
                },
                sources=ingest_sources,
                metadata={"provider_errors": ingest_warnings} if ingest_warnings else {},
            )
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
