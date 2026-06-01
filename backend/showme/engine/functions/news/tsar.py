"""TSAR — Transcript Sentiment Analyzer.

Score a transcript with FinBERT (and optional XSEN RoBERTa) and surface the
per-section / per-speaker / per-utterance sentiment: the dominant call tone,
polarity by speaker role (management vs analyst), and a top-quote ladder for
each polarity. The transcript source is resolved identically to TRAN/TRQA —
pasted ``text`` wins, then a ``(symbol, quarter)`` lookup in the
``transcripts_archive``, then ``audio_url`` via Whisper. When the audio path
requires Whisper and Whisper is missing the function returns
``data_mode="not_configured"`` with ``utterances=[]`` and a setup hint — never
a fabricated sentiment.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.services import transcripts_archive as archive

# Hysteresis thresholds for the dominant-tone derivation (see methodology).
_POS_THRESHOLD = 0.12
_NEG_THRESHOLD = -0.12

# Speaker role classification — keyword heuristics over the speaker prefix.
_ANALYST_HINTS = ("analyst", "research", "securities", "capital", "& co", "partners", "bank")
_OPERATOR_HINTS = ("operator", "moderator", "conference", "host")
_MGMT_HINTS = (
    "ceo", "cfo", "coo", "cto", "president", "chief", "chairman", "chairwoman",
    "director", "head of", "vp", "evp", "svp", "treasurer", "founder",
    "investor relations", "ir ", "officer", "management",
)

# A "SPEAKER: utterance" line. Capture group 1 = speaker label, 2 = text.
_SPEAKER_LINE = re.compile(r"^\s*([A-Z][\w .,'&/-]{0,60}?)\s*[:\-—]\s+(.*\S.*)$")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


@FunctionRegistry.register
class TSARFunction(BaseFunction):
    code = "TSAR"
    name = "Transcript Sentiment Analyzer"
    category = "news"
    description = "Score a transcript with FinBERT (+ optional XSEN RoBERTa) per section/speaker."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Legacy transcript-archive actions (search/stats/list/ingest/get/delete)
        # are retained verbatim for back-compat with the agent runtime and the
        # whisper-wiring tests. The DEFAULT path (no action, or action in
        # {analyze, sentiment, score}) is the manifest-promised sentiment
        # analyzer.
        action = (params.get("action") or "").lower()
        if action in _LEGACY_ACTIONS:
            return await self._legacy(action, instrument, params)
        # The agent runtime probes TSAR with a bare `query` (no action) and no
        # transcript text/audio — route that to the legacy FTS search so the
        # runtime keeps getting archive matches. A pasted `text`, a symbol/
        # quarter lookup, or audio always wins the sentiment-analyzer path.
        has_analyzer_input = bool(
            (params.get("text") or "").strip()
            or params.get("symbol")
            or (instrument.symbol if instrument else None)
            or params.get("audio_url")
            or params.get("audio_path")
        )
        if not action and not has_analyzer_input and str(
            params.get("query") or params.get("q") or ""
        ).strip():
            return await self._legacy("search", instrument, params)
        return await self._analyze(instrument, params)

    async def _analyze(self, instrument: Instrument | None, params: dict[str, Any]) -> FunctionResult:
        started = time.perf_counter()
        models = _normalize_models(params.get("models"))
        speaker_roles = _normalize_roles(params.get("speaker_roles"))
        warnings: list[str] = []
        sources: list[str] = []

        # ── 1. Resolve transcript source: pasted text → (symbol, quarter) → audio ──
        text, src_label, resolve_warn, audio_pending = await self._resolve_text(
            instrument, params, sources, warnings
        )
        if resolve_warn:
            warnings.append(resolve_warn)

        if audio_pending:
            # Audio path that needs Whisper, and Whisper is unavailable → honest
            # not_configured with a setup hint, no fabricated sentiment.
            return self._not_configured(instrument, models, started, sources, warnings)

        if not text or not str(text).strip():
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "no_text",
                    "data_mode": "not_configured",
                    "summary": _empty_summary(models),
                    "speaker_rollups": [],
                    "utterances": [],
                    "rows": [],
                    "series": [],
                    "cards": _empty_cards(models),
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICT,
                    "next_actions": [
                        "Paste transcript text, or pass a symbol with an archived transcript.",
                        "For audio, pass audio_url (Whisper transcription required).",
                    ],
                },
                sources=sources or ["transcripts_archive"],
                warnings=warnings or ["no transcript text resolved"],
                metadata={"latency_ms": _ms(started), "models": models},
            )

        # ── 2. Segment into utterances with speaker + role + section ──────────
        utterances_raw = _segment(text)
        if not utterances_raw:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "data_mode": "modeled",
                    "summary": _empty_summary(models),
                    "speaker_rollups": [],
                    "utterances": [],
                    "rows": [],
                    "series": [],
                    "cards": _empty_cards(models),
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICT,
                    "next_actions": ["Transcript produced no scorable utterances; check the text."],
                },
                sources=sources or ["transcripts_archive"],
                warnings=warnings,
                metadata={"latency_ms": _ms(started), "models": models},
            )

        # ── 3. Score every utterance with each requested model ────────────────
        texts = [u["utterance"] for u in utterances_raw]
        finbert_scores, finbert_warn = await self._score_finbert(texts)
        if finbert_warn:
            warnings.append(finbert_warn)
        else:
            sources.append("finbert")

        xsen_scores: list[float | None] = [None] * len(texts)
        if "xsen_roberta" in models:
            xsen_scores, xsen_warn = await self._score_xsen(texts)
            if xsen_warn:
                warnings.append(xsen_warn)
            else:
                sources.append("xsen_roberta")

        # Build per-(utterance, model) rows. Every row carries a model id.
        utterances: list[dict[str, Any]] = []
        position = 0
        for idx, base in enumerate(utterances_raw):
            for model_id in models:
                if model_id == "finbert":
                    score = finbert_scores[idx]
                elif model_id == "xsen_roberta":
                    score = xsen_scores[idx]
                    if score is None:
                        # XSEN failed → still emit a row with a model id but an
                        # honest neutral so provenance stays auditable.
                        score = 0.0
                else:
                    continue
                position += 1
                utterances.append(
                    {
                        "position": position,
                        "section": base["section"],
                        "speaker": base["speaker"],
                        "role": base["role"],
                        "utterance": base["utterance"],
                        "len": base["len"],
                        "score": round(float(score), 4),
                        "sentiment": _tag(float(score)),
                        "model": model_id,
                    }
                )

        # ── 4. Aggregations: net score, speaker rollups, dominant tone ────────
        # The primary aggregate is over the FinBERT pass (canonical), so a
        # second model doesn't double-weight an utterance.
        primary_rows = [u for u in utterances if u["model"] == "finbert"] or utterances
        net_score = _weighted_mean([(u["score"], u["len"]) for u in primary_rows])
        mgmt_score = _weighted_mean(
            [(u["score"], u["len"]) for u in primary_rows if u["role"] == "management"]
        )
        analyst_score = _weighted_mean(
            [(u["score"], u["len"]) for u in primary_rows if u["role"] == "analyst"]
        )
        dominant_tone = _dominant_tone(net_score)

        speaker_rollups = _build_rollups(primary_rows, speaker_roles)
        cards_quotes = _quote_ladder(primary_rows)

        summary = {
            "dominant_tone": dominant_tone,
            "net_score": round(net_score, 4),
            "management_score": round(mgmt_score, 4),
            "analyst_score": round(analyst_score, 4),
            "utterance_count": len(utterances_raw),
            "model_set": models,
            "source": src_label,
        }

        # series: speaker polarity bars for the BAR_LADDER chart grammar.
        series = [
            {"speaker": r["role"], "score": r["score"], "count": r["count"]}
            for r in speaker_rollups
        ]

        as_of = datetime.now(timezone.utc).isoformat()
        data_mode = "live_official" if "finbert" in sources else "modeled"
        cards = {
            "dominant_tone": dominant_tone,
            "net_score": round(net_score, 4),
            "management_score": round(mgmt_score, 4),
            "analyst_score": round(analyst_score, 4),
            "utterance_count": len(utterances_raw),
            "model_set": ", ".join(models),
            "data_mode": data_mode,
            "as_of": as_of,
            "top_positive": cards_quotes["positive"],
            "top_negative": cards_quotes["negative"],
        }

        data = {
            "status": "ok",
            "data_mode": data_mode,
            "summary": summary,
            "speaker_rollups": speaker_rollups,
            "utterances": utterances,
            "rows": utterances,
            "series": series,
            "cards": cards,
            "methodology": _METHODOLOGY,
            "field_dictionary": _FIELD_DICT,
            "next_actions": [],
        }
        if not sources:
            sources = ["transcripts_archive"]

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=data,
            sources=sources,
            warnings=warnings,
            metadata={
                "latency_ms": _ms(started),
                "models": models,
                "as_of": as_of,
            },
        )

    # ── source resolution ────────────────────────────────────────────────
    async def _resolve_text(
        self,
        instrument: Instrument | None,
        params: dict[str, Any],
        sources: list[str],
        warnings: list[str],
    ) -> tuple[str, str, str | None, bool]:
        """Return (text, source_label, warning, audio_pending).

        audio_pending is True only when the caller pointed us at audio that
        needs Whisper and Whisper is unavailable / produced no text.
        """
        text = params.get("text") or ""
        if str(text).strip():
            sources.append("pasted_text")
            return str(text), "pasted_text", None, False

        sym = params.get("symbol") or (instrument.symbol if instrument else None)
        quarter = params.get("quarter") or None
        if sym:
            try:
                rows = await asyncio.wait_for(
                    asyncio.to_thread(archive.list_for_symbol, str(sym), limit=50),
                    timeout=float(params.get("timeout", 8)),
                )
            except Exception as exc:  # noqa: BLE001
                return "", "archive", f"transcripts_archive: {exc.__class__.__name__}", False
            chosen = None
            for r in rows:
                if quarter and str(r.get("quarter") or "").lower() != str(quarter).lower():
                    continue
                chosen = r
                break
            if chosen is None and rows and not quarter:
                chosen = rows[0]
            if chosen is not None:
                row_id = chosen.get("id")
                full = None
                if row_id is not None:
                    try:
                        full = await asyncio.to_thread(archive.get, int(row_id))
                    except Exception:  # noqa: BLE001
                        full = None
                content = (full or {}).get("content") if full else None
                content = content or chosen.get("summary") or ""
                if str(content).strip():
                    sources.append("transcripts_archive")
                    return str(content), "transcripts_archive", None, False

        # Audio path → Whisper.
        if params.get("audio_url") or params.get("audio_path"):
            if not _whisper_available():
                return "", "audio", "whisper unavailable for audio transcription", True
            content, warn = await self._transcribe(params)
            if warn:
                warnings.append(warn)
            if str(content or "").strip():
                sources.append("whisper")
                return str(content), "whisper", None, False
            # Whisper was available but transcription failed/empty.
            return "", "audio", warn or "whisper transcription produced no text", True

        return "", "none", None, False

    async def _transcribe(self, params: dict[str, Any]) -> tuple[str, str | None]:
        timeout = float(params.get("transcribe_timeout", 30))
        if params.get("audio_url"):
            try:
                from showme.engine.services.transcription import transcribe_url

                w = await asyncio.wait_for(
                    transcribe_url(
                        params["audio_url"],
                        language=params.get("language"),
                        model_name=params.get("model", "base"),
                    ),
                    timeout=timeout,
                )
                return (w.get("text") or ""), None
            except Exception as exc:  # noqa: BLE001
                return "", f"transcribe_url: {exc.__class__.__name__}"
        if params.get("audio_path"):
            try:
                from showme.engine.services.transcription import transcribe

                w = await asyncio.wait_for(
                    transcribe(
                        params["audio_path"],
                        language=params.get("language"),
                        model_name=params.get("model", "base"),
                    ),
                    timeout=timeout,
                )
                return (w.get("text") or ""), None
            except Exception as exc:  # noqa: BLE001
                return "", f"transcribe: {exc.__class__.__name__}"
        return "", None

    # ── scoring ──────────────────────────────────────────────────────────
    async def _score_finbert(self, texts: list[str]) -> tuple[list[float], str | None]:
        try:
            from showme.finbert_analyzer import FinBertAnalyzer  # noqa: PLC0415

            analyzer = await asyncio.to_thread(FinBertAnalyzer.instance)
            results = await analyzer.label_many(texts)
            return [float(r.get("score_signed") or 0.0) for r in results], None
        except Exception as exc:  # noqa: BLE001
            return [0.0] * len(texts), f"finbert unavailable: {exc.__class__.__name__}"

    async def _score_xsen(self, texts: list[str]) -> tuple[list[float | None], str | None]:
        # XSEN's multi-head RoBERTa (sentiment / emotion / topic) — the same
        # bundled checkpoint the X Sentiment pane uses. classify() returns one
        # dict per input with a `sentiment` label + `sentiment_score`
        # confidence and a `probs.sentiment` probability vector.
        try:
            from showme.x_analysis import XAnalyzer  # noqa: PLC0415

            analyzer = await asyncio.to_thread(XAnalyzer.instance)
            results = await asyncio.to_thread(lambda: analyzer.classify(list(texts)))
            return [_xsen_signed(r) for r in results], None
        except Exception as exc:  # noqa: BLE001
            return [None] * len(texts), f"xsen_roberta unavailable: {exc.__class__.__name__}"

    # ── not_configured (Whisper missing) ──────────────────────────────────
    def _not_configured(
        self,
        instrument: Instrument | None,
        models: list[str],
        started: float,
        sources: list[str],
        warnings: list[str],
    ) -> FunctionResult:
        err = _whisper_error()
        msg = (
            f"whisper not configured: {err}" if err
            else "whisper not configured for audio transcription"
        )
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "not_configured",
                "data_mode": "not_configured",
                "summary": _empty_summary(models),
                "speaker_rollups": [],
                "utterances": [],
                "rows": [],
                "series": [],
                "cards": _empty_cards(models),
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICT,
                "next_actions": [
                    "Install/warm Whisper (large-v3) to transcribe the audio before scoring.",
                    "Or paste the transcript text directly to score without Whisper.",
                ],
            },
            sources=sources or ["whisper"],
            warnings=warnings + [msg],
            metadata={"latency_ms": _ms(started), "models": models},
        )

    # ── legacy transcript-archive actions (back-compat) ───────────────────
    async def _legacy(
        self, action: str, instrument: Instrument | None, params: dict[str, Any]
    ) -> FunctionResult:
        """Retained transcript-archive API (search/stats/list/ingest/get/delete).

        Kept verbatim so the agent runtime (action=search) and the whisper-
        wiring tests (action=ingest) keep working; the product default path is
        the sentiment analyzer above.
        """
        if action == "stats":
            return FunctionResult(code=self.code, instrument=None, data=archive.stats())
        if action == "list":
            sym = params.get("symbol") or (instrument.symbol if instrument else None)
            if not sym:
                return FunctionResult(code=self.code, instrument=None, data={"items": []})
            try:
                items = await asyncio.wait_for(
                    asyncio.to_thread(
                        archive.list_for_symbol, sym, limit=int(params.get("limit", 50))
                    ),
                    timeout=float(params.get("timeout", 8)),
                )
            except Exception:  # noqa: BLE001
                items = [{"symbol": sym, "status": "archive_unavailable"}]
            return FunctionResult(code=self.code, instrument=instrument, data={"items": items})
        if action == "ingest":
            return await self._legacy_ingest(instrument, params)
        if action == "get":
            row_id = _safe_int(params.get("id"))
            if row_id is None:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "input_required",
                        "reason": "action=get requires a numeric `id`.",
                        "next_actions": ["Pass id=<row id> in params."],
                    },
                    sources=["transcripts_archive"],
                )
            return FunctionResult(code=self.code, instrument=None, data=archive.get(row_id) or {})
        if action == "delete":
            row_id = _safe_int(params.get("id"))
            if row_id is None:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "input_required",
                        "reason": "action=delete requires a numeric `id`.",
                        "next_actions": ["Pass id=<row id> in params."],
                    },
                    sources=["transcripts_archive"],
                )
            return FunctionResult(
                code=self.code, instrument=None, data={"deleted": archive.delete(row_id)}
            )
        # default legacy action: search
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
                    "next_actions": [
                        "Enter keywords such as revenue, margin, guidance, or risk."
                    ],
                },
                sources=["transcripts_archive"],
                metadata={"provider_errors": ["missing transcript search query"]},
            )
        try:
            items = await asyncio.wait_for(
                asyncio.to_thread(
                    archive.search, query, symbol=sym, limit=int(params.get("limit", 25))
                ),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception:  # noqa: BLE001
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
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={"query": query, "items": items},
            sources=["transcripts_archive"],
        )

    async def _legacy_ingest(
        self, instrument: Instrument | None, params: dict[str, Any]
    ) -> FunctionResult:
        symbol_param = params.get("symbol") or (instrument.symbol if instrument else None)
        if not symbol_param:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_required",
                    "reason": "Transcript ingest requires a symbol.",
                    "next_actions": [
                        "Pass `symbol` (or focus an instrument) before action=ingest."
                    ],
                },
                sources=["transcripts_archive"],
                metadata={"provider_errors": ["missing ingest symbol"]},
            )
        ingest_warnings: list[str] = []
        ingest_sources: list[str] = ["transcripts_archive"]
        content = params.get("content") or ""
        if not content and (params.get("audio_url") or params.get("audio_path")):
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
        sentiment = params.get("sentiment")
        if sentiment is None and content:
            try:
                from showme.finbert_analyzer import FinBertAnalyzer

                analyzer = await asyncio.to_thread(FinBertAnalyzer.instance)
                result = await analyzer.label(content[:512])
                sentiment = float(result.get("score_signed") or 0.0)
                ingest_sources.append("finbert")
            except Exception as exc:  # noqa: BLE001
                ingest_warnings.append(f"finbert: {exc.__class__.__name__}")
        tid = archive.upsert(
            symbol=str(symbol_param),
            company=params.get("company"),
            quarter=params.get("quarter"),
            fiscal_year=params.get("fiscal_year"),
            event_date=params.get("event_date"),
            source=params.get("source"),
            url=params.get("url"),
            content=content,
            summary=params.get("summary"),
            sentiment=sentiment,
        )
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "id": tid,
                "ingested": True,
                "chars": len(content),
                "sentiment": sentiment,
            },
            sources=ingest_sources,
            metadata={"provider_errors": ingest_warnings} if ingest_warnings else {},
        )


# ── helpers ───────────────────────────────────────────────────────────────
_LEGACY_ACTIONS = frozenset(
    {"search", "stats", "list", "ingest", "get", "delete"}
)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
def _normalize_models(raw: Any) -> list[str]:
    allowed = ("finbert", "xsen_roberta")
    if not raw:
        return ["finbert"]
    if isinstance(raw, str):
        raw = [raw]
    out = [m for m in raw if m in allowed]
    return out or ["finbert"]


def _normalize_roles(raw: Any) -> list[str]:
    if not raw:
        return ["all"]
    if isinstance(raw, str):
        raw = [raw]
    valid = {"management", "analyst", "operator", "all"}
    out = [r for r in raw if r in valid]
    return out or ["all"]


def _classify_role(speaker: str) -> str:
    s = (speaker or "").lower()
    if any(h in s for h in _OPERATOR_HINTS):
        return "operator"
    if any(h in s for h in _ANALYST_HINTS):
        return "analyst"
    if any(h in s for h in _MGMT_HINTS):
        return "management"
    return "management"


def _segment(text: str) -> list[dict[str, Any]]:
    """Split a transcript into utterances with speaker, role, and section.

    Recognizes ``SPEAKER: text`` lines (and continuation lines that follow
    them). When no speaker prefixes exist (e.g. a flat paragraph), falls back
    to sentence segmentation under a single unknown speaker so the function
    still produces real per-utterance scores.
    """
    lines = [ln for ln in str(text).splitlines() if ln.strip()]
    utterances: list[dict[str, Any]] = []
    current_speaker: str | None = None
    current_role = "management"
    section = "prepared_remarks"
    saw_qa = False
    matched_any = False

    for ln in lines:
        low = ln.lower()
        if not saw_qa and (
            "question-and-answer" in low or "q&a" in low or "questions and answers" in low
        ):
            section = "qa"
            saw_qa = True
        m = _SPEAKER_LINE.match(ln)
        if m:
            matched_any = True
            current_speaker = m.group(1).strip()
            current_role = _classify_role(current_speaker)
            body = m.group(2).strip()
            for sent in _split_sentences(body):
                utterances.append(_utt(section, current_speaker, current_role, sent))
        elif current_speaker is not None:
            for sent in _split_sentences(ln.strip()):
                utterances.append(_utt(section, current_speaker, current_role, sent))

    if matched_any:
        return [u for u in utterances if u["utterance"]]

    # No speaker prefixes → sentence-level fallback under unknown speaker.
    flat = " ".join(lines)
    return [
        _utt("prepared_remarks", "Unknown", "management", sent)
        for sent in _split_sentences(flat)
        if sent.strip()
    ]


def _split_sentences(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _utt(section: str, speaker: str, role: str, utterance: str) -> dict[str, Any]:
    u = utterance.strip()
    return {
        "section": section,
        "speaker": speaker,
        "role": role,
        "utterance": u,
        "len": max(1, len(u)),
    }


def _weighted_mean(pairs: list[tuple[float, float]]) -> float:
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return 0.0
    return sum(s * w for s, w in pairs) / total_w


def _dominant_tone(net: float) -> str:
    if net >= _POS_THRESHOLD:
        return "positive"
    if net <= _NEG_THRESHOLD:
        return "negative"
    return "neutral"


def _tag(score: float) -> str:
    if score >= _POS_THRESHOLD:
        return "positive"
    if score <= _NEG_THRESHOLD:
        return "negative"
    return "neutral"


def _build_rollups(rows: list[dict[str, Any]], roles_filter: list[str]) -> list[dict[str, Any]]:
    want_all = "all" in roles_filter or not roles_filter
    by_role: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_role.setdefault(r["role"], []).append(r)
    out: list[dict[str, Any]] = []
    for role in ("management", "analyst", "operator"):
        if not want_all and role not in roles_filter:
            continue
        group = by_role.get(role) or []
        if not group:
            continue
        score = _weighted_mean([(g["score"], g["len"]) for g in group])
        out.append(
            {
                "role": role,
                "speaker": role,
                "score": round(score, 4),
                "count": len(group),
                "sentiment": _tag(score),
            }
        )
    return out


def _quote_ladder(rows: list[dict[str, Any]], top: int = 3) -> dict[str, list[dict[str, Any]]]:
    pos = sorted((r for r in rows if r["score"] > 0), key=lambda r: r["score"], reverse=True)
    neg = sorted((r for r in rows if r["score"] < 0), key=lambda r: r["score"])

    def fmt(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "speaker": r["speaker"],
            "role": r["role"],
            "score": r["score"],
            "utterance": r["utterance"][:280],
        }

    return {
        "positive": [fmt(r) for r in pos[:top]],
        "negative": [fmt(r) for r in neg[:top]],
    }


def _xsen_signed(result: dict[str, Any]) -> float:
    """Coerce an XSEN (showme.x_analysis.XAnalyzer) result dict → signed [-1,+1].

    XAnalyzer.classify() returns {sentiment: label, sentiment_score: conf,
    sentiment_probs: [...]} per item. We also tolerate the generic
    label/score/compound and probability-vector shapes.
    """
    if not isinstance(result, dict):
        return 0.0
    # Pre-signed forms first.
    for key in ("score_signed", "signed_score", "compound"):
        if result.get(key) is not None:
            try:
                return max(-1.0, min(1.0, float(result[key])))
            except (TypeError, ValueError):
                pass
    # XAnalyzer (and generic) label + confidence.
    label = str(result.get("sentiment") or result.get("label") or "").lower()
    try:
        conf = float(
            result.get("sentiment_score")
            if result.get("sentiment_score") is not None
            else (result.get("score") or result.get("confidence") or 0.0)
        )
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    if label in ("positive", "pos", "bullish", "label_2"):
        return conf
    if label in ("negative", "neg", "bearish", "label_0"):
        return -conf
    if label in ("neutral", "neu", "label_1"):
        return 0.0
    # probability-vector forms.
    probs = result.get("sentiment_probs")
    if isinstance(probs, (list, tuple)) and len(probs) >= 2:
        try:
            # Convention: index 0 = negative, last = positive (label_maps order).
            return max(-1.0, min(1.0, float(probs[-1]) - float(probs[0])))
        except (TypeError, ValueError):
            pass
    try:
        p = float(result.get("positive") or 0.0)
        n = float(result.get("negative") or 0.0)
        return max(-1.0, min(1.0, p - n))
    except (TypeError, ValueError):
        return 0.0


def _whisper_available() -> bool:
    try:
        from showme.whisper_analyzer import WhisperAnalyzer  # noqa: PLC0415

        return bool(WhisperAnalyzer.is_available())
    except Exception:  # noqa: BLE001
        return False


def _whisper_error() -> str | None:
    try:
        from showme.whisper_analyzer import WhisperAnalyzer  # noqa: PLC0415

        return WhisperAnalyzer.load_error()
    except Exception as exc:  # noqa: BLE001
        return exc.__class__.__name__


def _empty_summary(models: list[str]) -> dict[str, Any]:
    return {
        "dominant_tone": "neutral",
        "net_score": 0.0,
        "management_score": 0.0,
        "analyst_score": 0.0,
        "utterance_count": 0,
        "model_set": models,
        "source": None,
    }


def _empty_cards(models: list[str]) -> dict[str, Any]:
    return {
        "dominant_tone": "neutral",
        "net_score": 0.0,
        "management_score": 0.0,
        "analyst_score": 0.0,
        "utterance_count": 0,
        "model_set": ", ".join(models),
        "data_mode": "not_configured",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "top_positive": [],
        "top_negative": [],
    }


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


_METHODOLOGY = (
    "TSAR resolves the transcript source identically to TRAN/TRQA — pasted text wins, then a "
    "(symbol, quarter) lookup in the transcripts_archive, then audio_url via Whisper. The "
    "transcript is segmented into utterances (SPEAKER: text lines, with sentence fallback when "
    "no speaker prefixes exist) and each speaker is classified management/analyst/operator. Each "
    "utterance is scored by every model in the input set: FinBERT returns score_signed = P(pos) - "
    "P(neg) in [-1, +1] from the bundled ProsusAI/finbert checkpoint; xsen_roberta runs the X-tuned "
    "RoBERTa (reused from XSEN) coerced to the same range. The net score and speaker rollups are the "
    "char-length-weighted mean of utterance scores over the canonical FinBERT pass. dominant_tone is "
    "derived from net_score with hysteresis thresholds (positive >= +0.12, negative <= -0.12, else "
    "neutral). When the audio path requires Whisper and Whisper is missing, data_mode='not_configured' "
    "and utterances=[] with a setup hint — never a fabricated sentiment."
)

_FIELD_DICT = {
    "status": "ok / empty / no_text / not_configured.",
    "data_mode": "live_official when FinBERT scored, modeled when fallback-neutral, not_configured for missing Whisper.",
    "summary.dominant_tone": "positive / negative / neutral from net_score with +/-0.12 hysteresis.",
    "summary.net_score": "[-1,+1] char-length weighted mean of all utterance scores.",
    "summary.management_score": "[-1,+1] weighted mean over management-role utterances.",
    "summary.analyst_score": "[-1,+1] weighted mean over analyst-role utterances.",
    "summary.utterance_count": "Number of distinct utterances scored.",
    "speaker_rollups[].role": "management / analyst / operator.",
    "speaker_rollups[].score": "[-1,+1] char-length weighted mean score for this role.",
    "speaker_rollups[].count": "Utterances by this role.",
    "utterances[].position": "1-based row index in the scored ladder.",
    "utterances[].section": "prepared_remarks / qa.",
    "utterances[].score": "[-1,+1] per-utterance sentiment score.",
    "utterances[].sentiment": "positive / negative / neutral tag from the score.",
    "utterances[].model": "finbert / xsen_roberta — which model produced the score.",
}
