"""Whisper large-v3 singleton — multilingual ASR / translation.

Lazy-loaded once per process. Heavy (~3 GB model weights + ~1.5 GB resident on
M-series). Inference always runs through ``asyncio.to_thread`` so the FastAPI
event loop never blocks on a 30-second chunk. The model is downloaded on first
use through the HuggingFace cache; outside the .app the first call may pay a
multi-minute download. Inside the bundled .app the weights are shipped via
PyInstaller and the cache lookup hits the local snapshot.

Contract mirrors the other ML singletons in this package
(``x_analysis.XAnalyzer``, ``finbert_analyzer.FinBertAnalyzer``):

* ``instance()`` returns the singleton, or ``None`` if the model failed to
  load. Callers MUST check before dereferencing — there is no fallback to a
  smaller model from here; the legacy CPU paths in
  ``engine/services/transcription.py`` already do that for the no-Whisper
  case.
* ``is_available()`` is the cheap probe handlers should use to decide
  whether to call ``transcribe()`` or short-circuit with a "warmup pending"
  warning.
* ``transcribe(audio, language=None)`` returns
  ``{text, chunks: [{text, timestamp}], language, model}`` where ``model``
  is the literal string ``"whisper-large-v3"`` so downstream callers can
  pin the bundle version in audit logs.

Design notes
------------
* Heavy imports (``transformers.pipeline``, ``torch``) happen ONLY inside
  ``__init__`` so ``from showme.whisper_analyzer import WhisperAnalyzer``
  stays cheap (matches the FinBert/XAnalyzer convention).
* A class-level ``_load_failed`` latch prevents thrashing the loader on
  every request when the model genuinely cannot load (no network on first
  cold start, missing sentencepiece, etc.). Once latched ``instance()``
  returns ``None`` for the rest of the process lifetime.
* The singleton lock is the standard double-checked-lock pattern used in
  the sibling analyzers.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, ClassVar


LOG = logging.getLogger("showme.whisper")

# Pinned model id. We deliberately use the upstream HuggingFace bundle
# (openai/whisper-large-v3) rather than the older ``openai-whisper`` PyPI
# package's "large-v3" alias because the transformers pipeline gives us
# native chunked long-form transcription via ``chunk_length_s``.
WHISPER_MODEL = "openai/whisper-large-v3"


class WhisperAnalyzer:
    """Process-wide singleton wrapping the Whisper large-v3 ASR pipeline."""

    _instance: ClassVar["WhisperAnalyzer | None"] = None
    _instance_lock: ClassVar[threading.Lock] = threading.Lock()
    _load_failed: ClassVar[bool] = False
    _load_error: ClassVar[str | None] = None

    def __init__(self) -> None:
        # Heavy imports happen ONLY inside __init__.
        from transformers import pipeline  # noqa: PLC0415 - intentional lazy import

        self._pipe = pipeline(
            "automatic-speech-recognition",
            model=WHISPER_MODEL,
            return_timestamps=True,
            chunk_length_s=30,
            stride_length_s=5,
        )
        self._infer_lock = threading.Lock()

    # ── Singleton plumbing ───────────────────────────────────────────────
    @classmethod
    def instance(cls) -> "WhisperAnalyzer | None":
        """Return the singleton, or ``None`` if loading the model failed.

        Once a load failure is latched in ``_load_failed`` we do not retry
        for the rest of the process lifetime — a missing dependency or a
        missing weight bundle is not going to fix itself between requests
        and retrying every call would burn CPU + log noise.
        """
        with cls._instance_lock:
            if cls._load_failed:
                return None
            if cls._instance is None:
                try:
                    cls._instance = cls()
                    cls._load_error = None
                except Exception as exc:  # noqa: BLE001
                    cls._load_failed = True
                    cls._load_error = str(exc) or exc.__class__.__name__
                    LOG.warning("whisper large-v3 load failed (TRAN/TRQA/TSAR "
                                "will fall back to the legacy tiered service): %r", exc)
                    return None
            return cls._instance

    @classmethod
    def is_available(cls) -> bool:
        """Cheap probe — ``True`` only if the model is loaded and ready."""
        return cls._instance is not None and not cls._load_failed

    @classmethod
    def load_error(cls) -> str | None:
        """Last load error string for diagnostics endpoints. ``None`` while ok."""
        return cls._load_error

    @classmethod
    def reset_for_tests(cls) -> None:
        """Test-only helper — drop the singleton + clear the latch.

        Production code never calls this; the singleton is permanent.
        """
        with cls._instance_lock:
            cls._instance = None
            cls._load_failed = False
            cls._load_error = None

    # ── Inference ────────────────────────────────────────────────────────
    def _transcribe_sync(
        self,
        audio: str | Path | bytes,
        language: str | None,
    ) -> dict[str, Any]:
        """Run the pipeline; called from the asyncio worker thread."""
        kwargs: dict[str, Any] = {}
        if language:
            # Whisper's generate-time language hint. Anything Whisper does
            # not recognise (e.g. "auto") is rejected by transformers — we
            # let it bubble up so the handler surfaces the real error rather
            # than silently mis-transcribing.
            kwargs["generate_kwargs"] = {"language": language}
        # Normalise Path → str for the pipeline (it accepts str / bytes /
        # ndarray; Path is rejected on older transformers).
        if isinstance(audio, Path):
            audio = str(audio)
        with self._infer_lock:
            raw = self._pipe(audio, **kwargs)
        return _shape_payload(raw, language=language)

    async def transcribe(
        self,
        audio: str | Path | bytes,
        *,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Transcribe ``audio`` and return the canonical envelope.

        ``audio`` may be:
          * a path string or :class:`pathlib.Path` to an audio file
          * raw audio bytes (mp3 / wav / flac — transformers feeds it to
            ffmpeg under the hood)

        Returns
        -------
        dict
            ``{text, chunks: [{text, timestamp}], language, model}`` where
            ``language`` echoes the caller's hint (or the literal string
            ``"auto"`` when no hint was passed — Whisper detects internally
            but the pipeline does not surface the detected language for
            chunked output) and ``model`` is the pinned ``"whisper-large-v3"``.
        """
        return await asyncio.to_thread(self._transcribe_sync, audio, language)


def _shape_payload(raw: Any, *, language: str | None) -> dict[str, Any]:
    """Convert a transformers pipeline result into the canonical envelope.

    The pipeline returns ``{"text": str, "chunks": [{"text": str,
    "timestamp": (start, end)}]}`` when ``return_timestamps=True``. We
    re-shape into the envelope every showMe transcription caller speaks so
    the existing service-tier output and the new singleton output line up.
    """
    if not isinstance(raw, dict):
        return {
            "text": "",
            "chunks": [],
            "language": language or "auto",
            "model": "whisper-large-v3",
        }
    chunks_raw = raw.get("chunks") or []
    chunks: list[dict[str, Any]] = []
    for chunk in chunks_raw:
        if not isinstance(chunk, dict):
            continue
        chunks.append(
            {
                "text": str(chunk.get("text", "")),
                "timestamp": chunk.get("timestamp"),
            }
        )
    return {
        "text": str(raw.get("text", "")),
        "chunks": chunks,
        "language": language or "auto",
        "model": "whisper-large-v3",
    }


__all__ = ["WhisperAnalyzer", "WHISPER_MODEL"]
