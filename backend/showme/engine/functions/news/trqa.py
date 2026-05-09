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
            except Exception:
                pass
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
            except Exception:
                pass
        if not text:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_required",
                    "reason": "Transcript Q&A needs transcript text, audio_url, or audio_path before it can answer.",
                    "text_chars": 0,
                    "answers": [],
                    "next_actions": [
                        "Paste transcript text in Advanced as text.",
                        "Pass an audio_url/audio_path so Whisper can transcribe before Q&A.",
                    ],
                },
                sources=[],
                metadata={"provider_errors": ["missing transcript input"]},
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
    sentences = _sentences(text)
    terms = _question_terms(question)
    if not sentences:
        return {"a": "Transcript text was empty after parsing.", "evidence": "", "confidence": 0.0}
    scored = []
    for sentence in sentences:
        low = sentence.lower()
        score = sum(1 for term in terms if term in low)
        if any(token in low for token in ("guidance", "outlook", "expect", "risk", "headwind", "revenue", "eps", "margin")):
            score += 1
        scored.append((score, sentence))
    scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    best_score, best = scored[0]
    if best_score <= 0:
        best = sentences[0]
    return {
        "a": best,
        "evidence": best,
        "confidence": round(min(0.95, 0.35 + 0.12 * max(best_score, 0)), 2),
    }


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
