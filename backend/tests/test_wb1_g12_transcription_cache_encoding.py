"""LOC-4: the transcript cache must round-trip non-cp1254 text.

The cache used ``write_text(text)`` / ``read_text()`` with the locale codec.
On a Turkish Windows box (cp1254) a Whisper transcript containing Cyrillic,
arrows or emoji made ``write_text`` raise ``UnicodeEncodeError`` inside the
tier's try block, so an already-computed transcript was discarded and the
whole file was re-run on the next tier. The cache is now UTF-8 on both sides.

Network and models are stubbed: a fake ``whisper`` module returns the text.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

from showme.engine.services import transcription

NON_CP1254_TEXT = "Привет мир → 🎙 Ж"


def _fake_whisper(text: str) -> SimpleNamespace:
    def _transcribe(path, language=None):  # noqa: ARG001
        return {"text": text, "language": "ru", "segments": []}

    return SimpleNamespace(
        load_model=lambda name: SimpleNamespace(transcribe=_transcribe)
    )


async def test_tier1_keeps_non_cp1254_transcript(tmp_path, monkeypatch):
    cache_dir = tmp_path / "transcripts"
    monkeypatch.setattr(transcription, "_cache_dir", lambda: cache_dir)
    monkeypatch.setitem(sys.modules, "whisper", _fake_whisper(NON_CP1254_TEXT))

    audio = tmp_path / "clip_ru.wav"
    audio.write_bytes(b"RIFF" + bytes(range(80)))  # unique -> cache miss

    res = await transcription.transcribe(audio, use_singleton=False)

    # Before the fix the write raised UnicodeEncodeError on cp1254 and the
    # call fell through to the stub tier, discarding the transcript.
    assert res.get("model") == "whisper:base", res
    assert res["text"] == NON_CP1254_TEXT


async def test_cache_hit_reads_non_cp1254_transcript(tmp_path, monkeypatch):
    cache_dir = tmp_path / "transcripts"
    monkeypatch.setattr(transcription, "_cache_dir", lambda: cache_dir)
    # No whisper module: a cache hit must be served without any tier running.
    monkeypatch.setitem(sys.modules, "whisper", None)

    audio = tmp_path / "clip_ru2.wav"
    audio.write_bytes(b"RIFF" + bytes(range(90)))
    key = transcription._cache_key(audio.read_bytes())
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.txt").write_text(NON_CP1254_TEXT, encoding="utf-8")

    res = await transcription.transcribe(audio, use_singleton=False)

    assert res["model"] == "cache"
    assert res["text"] == NON_CP1254_TEXT
