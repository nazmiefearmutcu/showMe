"""Whisper large-v3 singleton wiring contract tests.

These tests MUST NOT load the real ~3 GB model. They exercise the
singleton lifecycle (lazy / latched / reset), the legacy service-tier
handoff, and the payload-shaping helper. The pipeline is stubbed in every
test so the suite runs in <1s even on CI machines without GPUs.

Coverage map
------------
* import-without-load — proves `from showme.whisper_analyzer import
  WhisperAnalyzer` is a cheap module-level import (no transformers/torch
  import at module scope).
* load-failed latch — proves `instance()` returns None and `is_available`
  is False after `_load_failed = True`, and that the latch is sticky.
* payload shape — stubs the pipeline and asserts the canonical envelope.
* legacy service tier-0 short-circuit — proves
  `engine.services.transcription.transcribe` consults the singleton when
  one is loaded and skips it cleanly when not.
* TRAN/TRQA "warming" warning — proves the user-facing handlers surface a
  transient "retry in 30s" message when the lifespan task hasn't finished
  yet.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


# ── Module-level import contract ─────────────────────────────────────────


def test_whisper_module_imports_without_loading():
    """`from showme.whisper_analyzer import WhisperAnalyzer` must be cheap.

    Heavy imports (transformers, torch) MUST happen inside __init__ and
    NOT at module scope — otherwise every cold sidecar boot pays the ~1s
    transformers import cost just to read the symbol.
    """
    # Remove a cached transformers import to simulate a clean process.
    transformers_was_loaded = "transformers" in sys.modules
    # Force a fresh import of the analyzer module.
    sys.modules.pop("showme.whisper_analyzer", None)
    from showme.whisper_analyzer import WhisperAnalyzer  # noqa: F401, PLC0415
    # If transformers was NOT already loaded by some other test, our
    # import shouldn't have pulled it in either.
    if not transformers_was_loaded:
        assert "transformers" not in sys.modules, (
            "whisper_analyzer module import pulled in transformers — "
            "move the heavy import inside __init__"
        )


# ── load-failed latch ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Every test starts with a clean singleton (no instance, no latch)."""
    from showme.whisper_analyzer import WhisperAnalyzer

    WhisperAnalyzer.reset_for_tests()
    yield
    WhisperAnalyzer.reset_for_tests()


def test_whisper_is_available_false_before_load():
    from showme.whisper_analyzer import WhisperAnalyzer

    assert WhisperAnalyzer.is_available() is False
    assert WhisperAnalyzer.load_error() is None


def test_whisper_is_available_false_when_load_fails(monkeypatch):
    """When `_load_failed` is True, instance() returns None and
    is_available() is False. We set the latch directly rather than
    triggering an actual load (which would import transformers)."""
    from showme.whisper_analyzer import WhisperAnalyzer

    monkeypatch.setattr(WhisperAnalyzer, "_load_failed", True, raising=False)
    monkeypatch.setattr(WhisperAnalyzer, "_load_error", "stub error", raising=False)

    assert WhisperAnalyzer.is_available() is False
    assert WhisperAnalyzer.instance() is None
    assert WhisperAnalyzer.load_error() == "stub error"


def test_whisper_load_failure_is_latched(monkeypatch):
    """A constructor failure latches _load_failed permanently so we don't
    burn CPU retrying on every request."""
    from showme import whisper_analyzer as wa
    from showme.whisper_analyzer import WhisperAnalyzer

    call_count = {"n": 0}

    def _boom(self):  # noqa: ANN001
        call_count["n"] += 1
        raise RuntimeError("no transformers, no whisper")

    monkeypatch.setattr(WhisperAnalyzer, "__init__", _boom, raising=False)

    assert WhisperAnalyzer.instance() is None
    assert WhisperAnalyzer.is_available() is False
    # Second call must NOT re-enter __init__.
    assert WhisperAnalyzer.instance() is None
    assert call_count["n"] == 1, (
        "load failure was not latched — instance() retried the constructor"
    )
    # The recorded error matches what the constructor raised.
    assert "no transformers" in (WhisperAnalyzer.load_error() or "")
    # Touch the module to keep the import live for coverage.
    assert wa.WHISPER_MODEL == "openai/whisper-large-v3"


# ── Payload shape ────────────────────────────────────────────────────────


def test_transcribe_shapes_payload_correctly(monkeypatch):
    """`transcribe()` wraps the raw pipeline output in the canonical
    envelope: text / chunks / language / model."""
    from showme.whisper_analyzer import WhisperAnalyzer

    # Build a minimal instance that bypasses __init__ — we don't want to
    # touch transformers. We then attach a fake pipeline.
    analyzer = WhisperAnalyzer.__new__(WhisperAnalyzer)
    import threading

    analyzer._infer_lock = threading.Lock()

    calls: list[tuple[object, dict]] = []

    def _fake_pipe(audio, **kwargs):  # noqa: ANN001
        calls.append((audio, kwargs))
        return {
            "text": "hello world",
            "chunks": [
                {"text": "hello", "timestamp": (0.0, 0.5)},
                {"text": " world", "timestamp": (0.5, 1.0)},
            ],
        }

    analyzer._pipe = _fake_pipe

    out = asyncio.run(analyzer.transcribe("dummy.mp3", language="en"))

    assert out["text"] == "hello world"
    assert out["model"] == "whisper-large-v3"
    assert out["language"] == "en"
    assert len(out["chunks"]) == 2
    assert out["chunks"][0] == {"text": "hello", "timestamp": (0.0, 0.5)}
    assert out["chunks"][1] == {"text": " world", "timestamp": (0.5, 1.0)}
    # Language hint was threaded into generate_kwargs.
    assert calls[0][1] == {"generate_kwargs": {"language": "en"}}


def test_transcribe_handles_missing_chunks(monkeypatch):
    """Pipeline output with no 'chunks' key still produces a valid
    envelope (chunks=[]). Defensive against transformers minor versions."""
    from showme.whisper_analyzer import WhisperAnalyzer

    analyzer = WhisperAnalyzer.__new__(WhisperAnalyzer)
    import threading

    analyzer._infer_lock = threading.Lock()
    analyzer._pipe = lambda audio, **kw: {"text": "no chunks here"}  # noqa: ARG005

    out = asyncio.run(analyzer.transcribe(b"\x00" * 100))
    assert out == {
        "text": "no chunks here",
        "chunks": [],
        "language": "auto",
        "model": "whisper-large-v3",
    }


def test_transcribe_normalises_path_to_str(monkeypatch):
    """A pathlib.Path is converted to str before reaching the pipeline."""
    from showme.whisper_analyzer import WhisperAnalyzer

    analyzer = WhisperAnalyzer.__new__(WhisperAnalyzer)
    import threading

    analyzer._infer_lock = threading.Lock()
    seen: list[object] = []

    def _fake_pipe(audio, **kw):  # noqa: ANN001, ARG001
        seen.append(audio)
        return {"text": "ok", "chunks": []}

    analyzer._pipe = _fake_pipe

    p = Path("/tmp/whisper-not-real.mp3")
    asyncio.run(analyzer.transcribe(p))
    assert seen == [str(p)], "Path was not normalised to str before pipeline"


# ── Legacy service tier-0 handoff ────────────────────────────────────────


def test_legacy_service_uses_singleton_when_loaded(monkeypatch, tmp_path):
    """`engine.services.transcription.transcribe` calls the singleton
    when one is available and re-wraps its envelope."""
    import showme.whisper_analyzer as wa
    from showme.engine.services import transcription

    audio = tmp_path / "fake.mp3"
    audio.write_bytes(b"\x00" * 4096)

    # Bypass the on-disk cache by pointing it at an empty tmpdir.
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(
        transcription, "_cache_dir", lambda: cache_dir, raising=False
    )

    # Stand up a fake singleton (no transformers anywhere).
    fake = wa.WhisperAnalyzer.__new__(wa.WhisperAnalyzer)

    async def _fake_transcribe(audio_in, *, language=None):  # noqa: ANN001
        return {
            "text": "tier-0 hit",
            "chunks": [{"text": "tier-0 hit", "timestamp": (0.0, 1.0)}],
            "language": language or "auto",
            "model": "whisper-large-v3",
        }

    fake.transcribe = _fake_transcribe
    monkeypatch.setattr(
        wa.WhisperAnalyzer, "instance", classmethod(lambda cls: fake)
    )

    out = asyncio.run(transcription.transcribe(audio))
    assert out["text"] == "tier-0 hit"
    assert out["model"] == "whisper:whisper-large-v3"
    # And the on-disk cache file was written for next time.
    cache_files = list(cache_dir.glob("*.txt"))
    assert len(cache_files) == 1
    assert cache_files[0].read_text() == "tier-0 hit"


def test_legacy_service_skips_singleton_when_disabled(monkeypatch, tmp_path):
    """`use_singleton=False` (or SHOWME_WHISPER_SINGLETON=0) makes the
    service jump straight to the legacy tiers."""
    import showme.whisper_analyzer as wa
    from showme.engine.services import transcription

    audio = tmp_path / "fake.mp3"
    audio.write_bytes(b"\x01" * 2048)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(
        transcription, "_cache_dir", lambda: cache_dir, raising=False
    )

    # If the singleton were consulted we'd hit this exploding stub.
    def _boom(cls):  # noqa: ANN001
        raise AssertionError("singleton was consulted despite use_singleton=False")

    monkeypatch.setattr(wa.WhisperAnalyzer, "instance", classmethod(_boom))

    # Force all legacy tiers to fail too so we fall through to the stub.
    monkeypatch.delitem(sys.modules, "whisper", raising=False)
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    out = asyncio.run(transcription.transcribe(audio, use_singleton=False))
    assert out["model"] == "stub"


# ── TRAN / TRQA "warming" warning surface ────────────────────────────────


@pytest.mark.asyncio
async def test_tran_warns_when_whisper_warming(monkeypatch, tmp_path):
    """When TRAN is asked to transcribe and the singleton isn't loaded
    yet (no load error either — just warming), it appends a transient
    'retry in 30s' warning to the FunctionResult metadata."""
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.news.tran import TRANFunction

    # Make the singleton report "not loaded, no error" (the warming state).
    from showme import whisper_analyzer as wa

    monkeypatch.setattr(wa.WhisperAnalyzer, "is_available", classmethod(lambda cls: False))
    monkeypatch.setattr(wa.WhisperAnalyzer, "load_error", classmethod(lambda cls: None))

    # Make the legacy service return a benign error so we exercise the
    # warning path without touching network/audio.
    from showme.engine.services import transcription

    async def _fail(*a, **kw):  # noqa: ANN001, ARG001
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(transcription, "transcribe_url", _fail)

    fn = TRANFunction()
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = await fn.execute(inst, audio_url="https://example.com/q4.mp3")

    errs = result.metadata.get("provider_errors", [])
    assert any("not yet warmed" in e for e in errs), errs


@pytest.mark.asyncio
async def test_trqa_warns_when_whisper_warming(monkeypatch):
    """Same warning shape on TRQA — surfaced through provider_errors."""
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.news.trqa import TRQAFunction
    from showme import whisper_analyzer as wa

    monkeypatch.setattr(wa.WhisperAnalyzer, "is_available", classmethod(lambda cls: False))
    monkeypatch.setattr(wa.WhisperAnalyzer, "load_error", classmethod(lambda cls: None))

    # Make the legacy service fail so we land in the "no text" path
    # without trying a real network call.
    from showme.engine.services import transcription

    async def _fail(*a, **kw):  # noqa: ANN001, ARG001
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(transcription, "transcribe_url", _fail)

    fn = TRQAFunction()
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = await fn.execute(inst, audio_url="https://example.com/q4.mp3")

    errs = result.metadata.get("provider_errors", [])
    assert any("not yet warmed" in e for e in errs), errs


@pytest.mark.asyncio
async def test_tsar_ingest_auto_transcribes_audio(monkeypatch, tmp_path):
    """TSAR action=ingest with audio_url runs Whisper before persisting,
    then stamps FinBert sentiment when the caller didn't supply one."""
    from showme.engine.functions.news.tsar import TSARFunction
    from showme.engine.services import transcription, transcripts_archive

    captured: dict[str, object] = {}

    async def _fake_transcribe_url(url, *, language=None, model_name="base"):  # noqa: ANN001, ARG001
        return {"text": "Q4 revenue grew 12 percent year over year.",
                "model": "whisper:whisper-large-v3"}

    def _fake_upsert(**kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return 42

    monkeypatch.setattr(transcription, "transcribe_url", _fake_transcribe_url)
    monkeypatch.setattr(transcripts_archive, "upsert", _fake_upsert)

    # Stub finbert so we don't touch transformers.
    from showme import finbert_analyzer as fb

    class _StubFinBert:
        async def label(self, text):  # noqa: ANN001, ARG002
            return {"score_signed": 0.42}

    monkeypatch.setattr(fb.FinBertAnalyzer, "instance",
                        classmethod(lambda cls: _StubFinBert()))

    fn = TSARFunction()
    result = await fn.execute(
        instrument=None,
        action="ingest",
        symbol="AAPL",
        audio_url="https://example.com/q4.mp3",
    )

    assert result.data["ingested"] is True
    assert result.data["id"] == 42
    # The transcript landed in archive.upsert as content.
    assert "revenue grew" in (captured.get("content") or "")
    # FinBert sentiment was stamped (we returned 0.42).
    assert captured.get("sentiment") == 0.42
    # Sources reflect the actual pipeline used.
    assert "whisper" in result.sources
    assert "finbert" in result.sources
