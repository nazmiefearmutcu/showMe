"""TRQA — Earnings Call Transcript Q&A.

Whisper ile transkript edilmiş veya metinli olarak verilmiş bir
earnings call üzerinde LLM üzerinden RAG-style sorular sorar.

Param örnekleri:
    audio_url:   "https://.../q4-call.mp3"
    text:        "<earnings call transcript metni>"
    questions:   ["What was Q4 revenue?", "What is FY guidance?", ...]
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


@FunctionRegistry.register
class TRQAFunction(BaseFunction):
    code = "TRQA"
    name = "Transcript Q&A"
    asset_classes = (AssetClass.EQUITY,)
    category = "news"
    description = "Run a list of questions against an earnings call transcript / audio."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        text = params.get("text") or ""
        # Session-14 fix: Whisper transcription failures used to be silently
        # swallowed, leaving the user with a misleading "missing transcript
        # input" reason when the real cause was a transcription error. Track
        # the failures so they surface in `provider_errors`.
        transcribe_errors: list[str] = []
        # If the caller asked us to transcribe (audio_url / audio_path) and
        # the bundled large-v3 singleton isn't warmed yet, surface a
        # transient warning so the UI can suggest a retry. Load failures
        # are permanent — only "still warming" is transient.
        if not text and (params.get("audio_url") or params.get("audio_path")):
            try:
                from showme.whisper_analyzer import WhisperAnalyzer  # noqa: PLC0415
                if not WhisperAnalyzer.is_available() and WhisperAnalyzer.load_error() is None:
                    transcribe_errors.append("whisper: large-v3 not yet warmed, retry in ~30s")
            except Exception:  # noqa: BLE001 - singleton optional
                pass
        # Whisper-transcribe if needed
        if not text and params.get("audio_url"):
            try:
                from showme.engine.services.transcription import transcribe_url
                w = await asyncio.wait_for(
                    transcribe_url(params["audio_url"],
                                   language=params.get("language"),
                                   model_name=params.get("model", "base")),
                    timeout=float(params.get("transcribe_timeout", 15)),
                )
                text = w.get("text") or ""
            except Exception as exc:
                transcribe_errors.append(f"transcribe_url: {exc}")
        if not text and params.get("audio_path"):
            try:
                from showme.engine.services.transcription import transcribe
                w = await asyncio.wait_for(
                    transcribe(params["audio_path"],
                               language=params.get("language"),
                               model_name=params.get("model", "base")),
                    timeout=float(params.get("transcribe_timeout", 15)),
                )
                text = w.get("text") or ""
            except Exception as exc:
                transcribe_errors.append(f"transcribe: {exc}")
        if not text:
            # Session-14 fix: when transcription was attempted but failed,
            # surface the underlying provider errors instead of pretending
            # the user simply forgot to pass anything.
            attempted = bool(params.get("audio_url") or params.get("audio_path"))
            reason = (
                "Transcript Q&A could not transcribe the provided audio; check provider_errors."
                if attempted and transcribe_errors
                else "Transcript Q&A needs transcript text, audio_url, or audio_path before it can answer."
            )
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_required" if not attempted else "provider_unavailable",
                    "reason": reason,
                    "text_chars": 0,
                    "answers": [],
                    "next_actions": [
                        "Paste transcript text in Advanced as text.",
                        "Pass an audio_url/audio_path so Whisper can transcribe before Q&A.",
                    ],
                },
                sources=[],
                metadata={"provider_errors": transcribe_errors or ["missing transcript input"]},
            )
        questions = _coerce_questions(params.get("questions"), params.get("query"))
        # LLM router for Q&A
        try:
            from showme.engine.agents.llm_router import LLMRequest, LLMRouter
            router = LLMRouter()
        except Exception:
            answers = [
                {
                    "q": q,
                    **_extractive_answer(text, q),
                    "model": "local_extractive",
                    "cost_usd": 0,
                    "tokens": 0,
                }
                for q in questions
            ]
            return FunctionResult(code=self.code, instrument=instrument,
                                  data={"status": "ok", "text_chars": len(text), "answers": answers},
                                  sources=["transcript_text", "local_extractive_qa"])

        async def _answer(q: str) -> dict[str, Any]:
            try:
                req = LLMRequest(
                    role="qa",
                    system="You are a careful equity analyst. Answer with quotes from the transcript when possible. If unknown, say 'not stated'.",
                    user=f"TRANSCRIPT:\n{text[:30000]}\n\nQUESTION: {q}",
                    max_tokens=500, temperature=0.1,
                    expected_complexity="med",
                )
                r = await asyncio.wait_for(
                    router.complete(req),
                    timeout=float(params.get("llm_timeout", 8)),
                )
                text_answer = str(r.text or "").strip()
                model = str(r.model or "").strip()
                if _answer_is_empty(text_answer) or model.lower() in {"", "none", "null"}:
                    return {
                        "q": q,
                        **_extractive_answer(text, q),
                        "model": "local_extractive",
                        "cost_usd": 0,
                        "tokens": 0,
                    }
                return {"q": q, "a": text_answer, "model": model,
                        "cost_usd": r.cost_usd, "tokens": r.tokens_in + r.tokens_out}
            except Exception:
                return {
                    "q": q,
                    **_extractive_answer(text, q),
                    "model": "local_extractive",
                    "cost_usd": 0,
                    "tokens": 0,
                }

        answers = await asyncio.gather(*(_answer(q) for q in questions))
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={"status": "ok", "text_chars": len(text), "answers": answers,
                   "total_cost_usd": sum(a.get("cost_usd", 0) for a in answers)},
            sources=["transcript_text", "llm"],
        )


def _coerce_questions(value: Any, query: Any = None) -> list[str]:
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[\n;]+", value) if part.strip()]
        return parts or ([str(query).strip()] if query else _DEFAULT_QUESTIONS)
    if isinstance(value, (list, tuple)):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return parts or ([str(query).strip()] if query else _DEFAULT_QUESTIONS)
    if query:
        return [str(query).strip()]
    return list(_DEFAULT_QUESTIONS)


def _extractive_answer(text: str, question: str) -> dict[str, Any]:
    """Pick the best evidence sentence for a question via cheap heuristics.

    BugHunt 2026-05-24: previous version returned `0.35 + 0.12 * best_score`
    for every answer, which floors out at 0.35 even when ``best_score == 0``
    (no terms matched and no domain keywords landed) and yielded the
    notorious "0.59" constant whenever exactly two signals fired. That
    masquerades a fake number as a model probability.

    New rule:
      * If we have no real signal (best_score == 0 AND no terms in question)
        we return ``confidence: None`` — be honest, not falsely precise.
      * Otherwise compute confidence from real evidence:
        normalised term-match ratio, domain-keyword hits, evidence length.
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
    best = scored[0]
    best_total, best_terms, best_domain, best_sentence = best
    if best_total <= 0:
        best_sentence = sentences[0]
    confidence = _extractive_confidence(
        term_hits=best_terms,
        domain_hits=best_domain,
        question_terms=len(terms),
        evidence_chars=len(best_sentence or ""),
    )
    return {
        "a": best_sentence,
        "evidence": best_sentence,
        "confidence": confidence,
    }


def _extractive_confidence(
    *,
    term_hits: int,
    domain_hits: int,
    question_terms: int,
    evidence_chars: int,
) -> float | None:
    """Real-signal confidence in [0, 1] or None when no real signal exists."""
    if term_hits <= 0 and domain_hits <= 0:
        # No question terms matched and no domain hint — refuse to lie.
        return None
    if question_terms <= 0 and domain_hits <= 0:
        return None
    term_ratio = (term_hits / question_terms) if question_terms > 0 else 0.0
    score = 0.0
    if term_hits > 0:
        score += 0.45 * min(term_ratio, 1.0)
    if domain_hits > 0:
        score += 0.20 * min(domain_hits / 3.0, 1.0)
    # Evidence-length bonus tapers between 30 and 240 chars.
    if evidence_chars >= 30:
        score += 0.10 * min((evidence_chars - 30) / 210.0, 1.0)
    if score <= 0.0:
        return None
    return round(min(0.95, score), 2)


def _answer_is_empty(value: str) -> bool:
    cleaned = (value or "").strip().lower()
    return cleaned in {"", "-", "—", "n/a", "na", "none", "null", "not available"}


def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()][:200]


def _question_terms(question: str) -> list[str]:
    stop = {"what", "was", "were", "the", "and", "or", "did", "with", "from", "this", "that", "for", "into", "how", "much"}
    return [
        token
        for token in re.findall(r"[a-z0-9]+", (question or "").lower())
        if len(token) > 2 and token not in stop
    ]
