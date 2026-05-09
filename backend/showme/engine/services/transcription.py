"""Whisper transcription service.

Backend tier:
  1) ``whisper`` (OpenAI's official open-weight model, CPU-friendly)
  2) ``faster-whisper`` (CTranslate2 backend, 4× faster on CPU)
  3) OpenAI API (``OPENAI_API_KEY`` + ``audio.transcriptions``)
  4) ``stub`` returns "[transcription unavailable]"

Cache: SHA-256(audio_bytes) → runtime/transcripts/<hash>.txt
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any


_CACHE_DIR = Path("runtime/transcripts")


def _cache_key(audio_bytes: bytes) -> str:
    return hashlib.sha256(audio_bytes).hexdigest()[:32]


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.txt"


async def transcribe(audio_path: str | Path,
                      *, language: str | None = None,
                      model_name: str = "base") -> dict[str, Any]:
    """Transcribe a local audio file (.mp3/.m4a/.wav). Returns
    ``{text, language, model, segments}``."""
    p = Path(audio_path)
    if not p.exists():
        return {"error": f"file not found: {p}"}
    audio = p.read_bytes()
    key = _cache_key(audio)
    cache = _cache_path(key)
    if cache.exists():
        return {"text": cache.read_text(), "model": "cache", "language": language}

    # Tier 1: whisper.cpp / openai-whisper
    try:
        import whisper  # type: ignore
        m = whisper.load_model(model_name)
        result = m.transcribe(str(p), language=language)
        text = result.get("text", "").strip()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text)
        return {"text": text, "language": result.get("language"),
                "model": f"whisper:{model_name}",
                "segments": result.get("segments", [])[:50]}
    except Exception:
        pass

    # Tier 2: faster-whisper
    try:
        from faster_whisper import WhisperModel  # type: ignore
        m = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, info = m.transcribe(str(p), language=language)
        seg_list = list(segments)
        text = " ".join(s.text for s in seg_list).strip()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text)
        return {"text": text, "language": info.language,
                "model": f"faster-whisper:{model_name}",
                "segments": [{"start": s.start, "end": s.end, "text": s.text}
                              for s in seg_list[:50]]}
    except Exception:
        pass

    # Tier 3: OpenAI Whisper API
    if os.environ.get("OPENAI_API_KEY"):
        try:
            from openai import AsyncOpenAI  # type: ignore
            client = AsyncOpenAI()
            with p.open("rb") as f:
                resp = await client.audio.transcriptions.create(
                    model="whisper-1", file=f, language=language,
                )
            text = getattr(resp, "text", "") or ""
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text)
            return {"text": text, "model": "openai:whisper-1",
                    "language": language}
        except Exception as e:
            return {"error": f"openai whisper: {e}"}

    return {"text": "[transcription unavailable — install whisper or set OPENAI_API_KEY]",
             "model": "stub"}


async def transcribe_url(url: str, *, language: str | None = None,
                          model_name: str = "base") -> dict[str, Any]:
    """Download an audio URL into a tmp file and transcribe."""
    import httpx
    import tempfile
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            content = r.content
    except Exception as e:
        return {"error": f"download: {e}"}
    suffix = url.rsplit(".", 1)[-1].lower()
    if suffix not in ("mp3", "m4a", "wav", "ogg", "flac"):
        suffix = "mp3"
    with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as f:
        f.write(content)
        tmp = f.name
    try:
        return await transcribe(tmp, language=language, model_name=model_name)
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
