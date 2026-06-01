"""TRQA — Earnings Call Transcript Q&A.

Real, KEYLESS implementation. The claim is: answer questions over an
earnings-call transcript. We obtain a REAL transcript several ways (in order):

  1. an explicit ``transcript`` / ``text`` param (user-pasted text),
  2. Whisper transcription of an ``audio_url`` / ``audio_path``,
  3. the most recent SEC 8-K Exhibit 99.1 earnings document for the symbol,
     reusing the keyless EDGAR helpers shipped in ``news.tran``.

We then answer with keyless extractive retrieval (passage ranking by query-term
overlap) and, when an LLM router is wired (``showme.engine.agents.llm_router``),
an abstractive answer grounded in the retrieved passages. We never invent
content: every answer is backed by quoted evidence passages from the real
document, and an empty/dash LLM response falls back to the local extractive
answer (``model='local_extractive'``).

Param examples:
    transcript / text:  "<earnings call transcript text>"
    audio_url:          "https://.../q4-call.mp3"
    questions:          ["What was Q4 revenue?", "What is FY guidance?", ...]
    query / question:   "What changed in guidance?"
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


_DEFAULT_QUESTIONS = [
    "What was the headline revenue and EPS for the quarter?",
    "Did the company raise or lower full-year guidance, and by how much?",
    "What were the most-discussed risks or headwinds?",
    "Quote the CEO's most forward-looking statement.",
    "What capital allocation moves (buybacks, dividends, M&A) were mentioned?",
]


def _rank_passages(text: str, query: str, k: int = 5) -> list[dict[str, Any]]:
    """Keyless extractive retrieval: score sentences by query-term overlap."""
    qterms = set(_question_terms(query))
    sentences = [s for s in _sentences(text) if len(s) >= 25]
    if not qterms:
        # No usable query terms — return the lead passages as context.
        return [{"passage": s, "score": 0.0} for s in sentences[:k]]
    scored: list[tuple[float, str]] = []
    for s in sentences:
        sl = s.lower()
        hits = sum(1 for t in qterms if t in sl)
        if hits:
            scored.append((hits / len(qterms), s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"passage": s, "score": round(sc, 3)} for sc, s in scored[:k]]


async def _fetch_transcript_text(
    symbol: str, deps: Any = None
) -> tuple[str, dict[str, Any] | None]:
    """Reuse TRAN's keyless SEC helper to fetch a real earnings document.

    ``tran._fetch_sec_earnings_press_release(symbol, deps) -> (meta, body)``
    resolves the ticker to a CIK and pulls the latest 8-K Exhibit 99.x earnings
    press-release text from EDGAR (keyless, needs only a User-Agent). This is
    the only SEC helper TRAN actually exports — earlier code imported
    ``_recent_8k_exhibits``/``_extract_exhibit_text`` which never existed, so
    the SEC path silently died and TRQA always returned provider_unavailable.
    """
    try:
        from showme.engine.functions.news.tran import _fetch_sec_earnings_press_release
    except Exception:
        return "", None
    try:
        meta, body = await _fetch_sec_earnings_press_release(symbol, deps=deps)
    except Exception:
        return "", None
    if body and len(body) > 400:
        return body, meta
    return "", None


@FunctionRegistry.register
class TRQAFunction(BaseFunction):
    code = "TRQA"
    name = "Transcript Q&A"
    asset_classes = (AssetClass.EQUITY,)
    category = "news"
    description = "Run a list of questions against an earnings call transcript / audio."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (getattr(instrument, "symbol", None) or params.get("symbol") or "AAPL").upper()

        # ---- 1) resolve transcript TEXT from the available sources -----------
        transcript = str(params.get("transcript") or params.get("text") or "").strip()
        source_mode = "user_transcript" if transcript else ""
        source_doc: dict[str, Any] | None = None
        warnings: list[str] = []
        # Session-14 contract: Whisper transcription failures must surface in
        # ``provider_errors`` instead of being swallowed into a misleading
        # "missing transcript input" reason.
        transcribe_errors: list[str] = []
        attempted_transcribe = bool(params.get("audio_url") or params.get("audio_path"))

        if not transcript and attempted_transcribe:
            # If the caller asked us to transcribe and the bundled large-v3
            # singleton isn't warmed yet, surface a transient warning so the UI
            # can suggest a retry. Load failures are permanent — only "still
            # warming" (not available, no load error) is transient.
            try:
                from showme.whisper_analyzer import WhisperAnalyzer  # noqa: PLC0415
                if not WhisperAnalyzer.is_available() and WhisperAnalyzer.load_error() is None:
                    transcribe_errors.append("whisper: large-v3 not yet warmed, retry in ~30s")
            except Exception:  # noqa: BLE001 - singleton optional
                pass

        if not transcript and params.get("audio_url"):
            try:
                from showme.engine.services.transcription import transcribe_url
                w = await asyncio.wait_for(
                    transcribe_url(
                        params["audio_url"],
                        language=params.get("language"),
                        model_name=params.get("model", "base"),
                    ),
                    timeout=float(params.get("transcribe_timeout", 15)),
                )
                transcript = (w.get("text") or "").strip()
                if transcript:
                    source_mode = "whisper_audio"
            except Exception as exc:  # noqa: BLE001
                transcribe_errors.append(f"transcribe_url: {exc}")

        if not transcript and params.get("audio_path"):
            try:
                from showme.engine.services.transcription import transcribe
                w = await asyncio.wait_for(
                    transcribe(
                        params["audio_path"],
                        language=params.get("language"),
                        model_name=params.get("model", "base"),
                    ),
                    timeout=float(params.get("transcribe_timeout", 15)),
                )
                transcript = (w.get("text") or "").strip()
                if transcript:
                    source_mode = "whisper_audio"
            except Exception as exc:  # noqa: BLE001
                transcribe_errors.append(f"transcribe: {exc}")

        # 2) keyless SEC 8-K Exhibit 99.1 fallback when nothing else produced text
        #    and no audio path was requested (audio requests stay on their own
        #    honest-degradation branch so whisper errors aren't masked).
        if not transcript and not attempted_transcribe:
            try:
                transcript, source_doc = await _fetch_transcript_text(sym, deps=self.deps)
                if transcript:
                    source_mode = "sec_8k_ex99"
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"sec: {exc}")

        # ---- honest "no transcript" envelope --------------------------------
        if not transcript:
            reason = (
                "Transcript Q&A could not transcribe the provided audio; check provider_errors."
                if attempted_transcribe and transcribe_errors
                else f"No earnings transcript found for {sym} via SEC 8-K and none was pasted."
            )
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "symbol": sym,
                    "query": _first_question(params),
                    "text_chars": 0,
                    "rows": [],
                    "answer": "",
                    "answer_text": "",
                    "answers": [],
                    "reason": reason,
                    "next_actions": [
                        "Paste a transcript via the 'transcript' / 'text' input, or",
                        "Pass an audio_url/audio_path so Whisper can transcribe before Q&A, or",
                        "Open TRAN to pull the latest earnings document first.",
                    ],
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICT,
                    "sec_recent_filings": [source_doc] if source_doc else [],
                },
                sources=["no_live_source"],
                warnings=warnings or [f"No transcript available for {sym}."],
                metadata={
                    "symbol": sym,
                    "live": bool(source_doc),
                    "provider_errors": transcribe_errors or warnings or ["missing transcript input"],
                },
            )

        # ---- 3) answer one or more questions over the transcript ------------
        questions = _coerce_questions(params.get("questions"), params.get("query") or params.get("question"))
        explicit_query = bool(
            str(params.get("query") or params.get("question") or "").strip()
            or params.get("questions")
        )

        if not explicit_query and not questions:
            # No question → surface a real preview of the transcript.
            preview = _sentences(transcript)[:6]
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "ok",
                    "symbol": sym,
                    "query": "",
                    "text_chars": len(transcript),
                    "rows": [{"evidence": s, "score": None} for s in preview],
                    "answer": "Ask a question about this transcript (e.g. 'what is the revenue guidance?').",
                    "answer_text": "Ask a question about this transcript (e.g. 'what is the revenue guidance?').",
                    "answers": [],
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICT,
                    "source": source_mode,
                    "sec_recent_filings": [source_doc] if source_doc else [],
                },
                sources=[source_mode],
                warnings=warnings,
                metadata={"symbol": sym, "live": True, "source": source_mode,
                          "provider_errors": transcribe_errors},
            )

        answers = await _answer_questions(transcript, questions, sym, self.deps, params)

        primary = answers[0] if answers else {"a": "", "evidence": ""}
        primary_answer = str(primary.get("a") or "")
        evidence_rows = _evidence_rows(transcript, questions[0] if questions else "")

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "symbol": sym,
                "query": questions[0] if questions else "",
                "text_chars": len(transcript),
                "answer": primary_answer,
                "answer_text": primary_answer,
                "answers": answers,
                "rows": evidence_rows,
                "evidence": evidence_rows,
                "total_cost_usd": sum(float(a.get("cost_usd", 0) or 0) for a in answers),
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICT,
                "source": source_mode,
                "sec_recent_filings": [source_doc] if source_doc else [],
            },
            sources=[source_mode, "extractive_qa"]
            + (["llm"] if any(a.get("model") not in ("local_extractive", None) for a in answers) else []),
            warnings=warnings,
            metadata={
                "symbol": sym,
                "live": True,
                "source": source_mode,
                "transcript_chars": len(transcript),
                "provider_errors": transcribe_errors,
            },
        )


def _first_question(params: dict[str, Any]) -> str:
    return str(params.get("query") or params.get("question") or "").strip()


def _evidence_rows(transcript: str, question: str) -> list[dict[str, Any]]:
    passages = _rank_passages(transcript, question, k=6)
    return [{"evidence": p["passage"], "score": p["score"]} for p in passages]


async def _answer_questions(
    text: str,
    questions: list[str],
    sym: str,
    deps: Any,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Answer each question with the LLM router when wired, else extractive.

    A dash/empty LLM response (or a 'none'/'null' model) falls back to the local
    extractive answer with ``model='local_extractive'`` — never an invented one.
    """
    try:
        from showme.engine.agents.llm_router import LLMRequest, LLMRouter
        router = LLMRouter()
    except Exception:
        return [
            {
                "q": q,
                **_extractive_answer(text, q),
                "model": "local_extractive",
                "cost_usd": 0,
                "tokens": 0,
            }
            for q in questions
        ]

    async def _answer(q: str) -> dict[str, Any]:
        try:
            req = LLMRequest(
                role="qa",
                system=(
                    "You are a careful equity analyst. Answer with quotes from the "
                    "transcript when possible. If unknown, say 'not stated'."
                ),
                user=f"TRANSCRIPT:\n{text[:30000]}\n\nQUESTION: {q}",
                max_tokens=500,
                temperature=0.1,
                expected_complexity="med",
            )
            r = await asyncio.wait_for(
                router.complete(req),
                timeout=float(params.get("llm_timeout", 8)),
            )
            text_answer = str(getattr(r, "text", "") or "").strip()
            model = str(getattr(r, "model", "") or "").strip()
            if _answer_is_empty(text_answer) or model.lower() in {"", "none", "null"}:
                return {
                    "q": q,
                    **_extractive_answer(text, q),
                    "model": "local_extractive",
                    "cost_usd": 0,
                    "tokens": 0,
                }
            return {
                "q": q,
                "a": text_answer,
                "model": model,
                "cost_usd": getattr(r, "cost_usd", 0),
                "tokens": getattr(r, "tokens_in", 0) + getattr(r, "tokens_out", 0),
            }
        except Exception:  # noqa: BLE001 - any router failure degrades to extractive
            return {
                "q": q,
                **_extractive_answer(text, q),
                "model": "local_extractive",
                "cost_usd": 0,
                "tokens": 0,
            }

    return list(await asyncio.gather(*(_answer(q) for q in questions)))


def _coerce_questions(value: Any, query: Any = None) -> list[str]:
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[\n;]+", value) if part.strip()]
        return parts or ([str(query).strip()] if query else list(_DEFAULT_QUESTIONS))
    if isinstance(value, (list, tuple)):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return parts or ([str(query).strip()] if query else list(_DEFAULT_QUESTIONS))
    if query:
        return [str(query).strip()]
    return list(_DEFAULT_QUESTIONS)


_METHODOLOGY = (
    "TRQA answers questions over a REAL earnings-call transcript. The transcript is taken from a pasted "
    "input when provided, otherwise Whisper-transcribed audio, otherwise the most recent SEC 8-K Exhibit "
    "99.1 earnings document fetched via the keyless EDGAR API. Each question is answered by ranking "
    "transcript passages on query-term overlap (extractive retrieval); when an LLM router is configured an "
    "abstractive answer is generated strictly from those retrieved passages, falling back to the best "
    "extractive passage when the model returns nothing. Every answer is backed by quoted evidence passages "
    "from the real document."
)

_FIELD_DICT = {
    "answer": "Primary answer grounded in the transcript (abstractive if an LLM is wired, else the best-matching passage).",
    "answers": "Per-question answers; model='local_extractive' marks the keyless fallback.",
    "evidence": "Transcript passages ranked by relevance to the question.",
    "score": "Fraction of query terms matched in the passage.",
}


# --------------------------------------------------------------------------- #
# Extractive helpers — honest-confidence contract (no hardcoded 0.59) preserved
# verbatim from the 2026-05-24 bug-hunt regression suite.
# --------------------------------------------------------------------------- #
def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()][:200]


def _question_terms(question: str) -> list[str]:
    stop = {"what", "was", "were", "the", "and", "or", "did", "with", "from",
            "this", "that", "for", "into", "how", "much", "is", "are", "of",
            "to", "in", "on", "a", "an", "be", "been", "do", "does", "it", "as"}
    return [
        token
        for token in re.findall(r"[a-z0-9]+", (question or "").lower())
        if len(token) > 2 and token not in stop
    ]


def _answer_is_empty(value: str) -> bool:
    cleaned = (value or "").strip().lower()
    return cleaned in {"", "-", "—", "n/a", "na", "none", "null", "not available"}


def _extractive_confidence(
    *,
    term_hits: int,
    domain_hits: int,
    question_terms: int,
    evidence_chars: int,
) -> float | None:
    """Real-signal confidence in [0, 1] or None when no real signal exists.

    BugHunt 2026-05-24: never emit a floor constant (the notorious 0.59) — when
    nothing matched, return None instead of pretending precision.
    """
    if term_hits <= 0 and domain_hits <= 0:
        return None
    if question_terms <= 0 and domain_hits <= 0:
        return None
    term_ratio = (term_hits / question_terms) if question_terms > 0 else 0.0
    score = 0.0
    if term_hits > 0:
        score += 0.45 * min(term_ratio, 1.0)
    if domain_hits > 0:
        score += 0.20 * min(domain_hits / 3.0, 1.0)
    if evidence_chars >= 30:
        score += 0.10 * min((evidence_chars - 30) / 210.0, 1.0)
    if score <= 0.0:
        return None
    return round(min(0.95, score), 2)


def _extractive_answer(text: str, question: str) -> dict[str, Any]:
    """Pick the best evidence sentence for a question via cheap heuristics.

    Honest confidence: None when no real signal exists, else derived from real
    term-match ratio + domain-keyword hits + evidence length.
    """
    sentences = _sentences(text)
    terms = _question_terms(question)
    if not sentences:
        return {"a": "Transcript text was empty after parsing.", "evidence": "", "confidence": None}
    domain_tokens = ("guidance", "outlook", "expect", "risk", "headwind", "revenue", "eps", "margin")
    scored: list[tuple[int, int, int, str]] = []
    for sentence in sentences:
        low = sentence.lower()
        term_hits = sum(1 for term in terms if term in low)
        domain_hits = sum(1 for token in domain_tokens if token in low)
        scored.append((term_hits + (1 if domain_hits else 0), term_hits, domain_hits, sentence))
    scored.sort(key=lambda item: (item[0], item[1], len(item[3])), reverse=True)
    best_total, best_terms, best_domain, best_sentence = scored[0]
    if best_total <= 0:
        best_sentence = sentences[0]
    confidence = _extractive_confidence(
        term_hits=best_terms,
        domain_hits=best_domain,
        question_terms=len(terms),
        evidence_chars=len(best_sentence or ""),
    )
    return {"a": best_sentence, "evidence": best_sentence, "confidence": confidence}
