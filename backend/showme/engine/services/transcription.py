"""Whisper transcription service.

Backend tier:
  0) :class:`showme.whisper_analyzer.WhisperAnalyzer` (in-process
     ``openai/whisper-large-v3`` singleton — the recommended path now that
     the model is bundled inside the .app)
  1) ``whisper`` (OpenAI's official open-weight Python package, CPU-friendly)
  2) ``faster-whisper`` (CTranslate2 backend, 4× faster on CPU)
  3) OpenAI API (``OPENAI_API_KEY`` + ``audio.transcriptions``)
  4) ``stub`` returns "[transcription unavailable]"

Cache: SHA-256(audio_bytes) → runtime/transcripts/<hash>.txt — checked
*before* any tier runs so a previously-transcribed file never re-pays the
large-v3 cost. The cache file is the plain transcript text; we re-wrap it
in the standard envelope on read.

The ``model_name`` parameter is honoured ONLY when the call lands on a
fallback tier — Tier 0 always uses large-v3 because that is the singleton
the rest of the app shares. Pass ``use_singleton=False`` (or set
``SHOWME_WHISPER_SINGLETON=0``) to force the legacy tiered path, e.g. for
tests that need a deterministic fake-pipeline backend.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import socket
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from showme.app_paths import runtime_path

LOG = logging.getLogger("showme.transcription")


class UnsafeURLError(ValueError):
    """Raised when a user-supplied audio URL targets a non-public address."""


def _assert_public_url(url: str) -> None:
    """Reject URLs that could drive a server-side request forgery (SSRF).

    Requires an ``http``/``https`` scheme and resolves the hostname, rejecting
    if ANY resolved IP is private, loopback, link-local, reserved, multicast or
    otherwise non-global. ``file://`` and every other scheme are refused. The
    caller fetches with ``follow_redirects=False`` and re-validates each hop,
    so this guard runs once per concrete host before the socket is opened.
    """
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UnsafeURLError(f"disallowed scheme: {scheme or '(none)'!r}")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("missing host")

    # Resolve every A/AAAA record; a hostname can map to multiple addresses
    # (and DNS rebinding can hide an internal one behind a public-looking name).
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"cannot resolve host {host!r}: {exc}") from exc
    if not infos:
        raise UnsafeURLError(f"host {host!r} did not resolve")

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:  # pragma: no cover - getaddrinfo returns valid IPs
            raise UnsafeURLError(f"unparseable address {ip_str!r}") from exc
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
            or not ip.is_global
        ):
            raise UnsafeURLError(
                f"host {host!r} resolves to non-public address {ip_str}"
            )


def _media_base_dirs() -> list[Path]:
    """Directories a local ``audio_path`` is allowed to live under.

    Legitimate local-file transcription targets the app cache/runtime tree and
    the OS temp dir (``transcribe_url`` writes downloads there). Anything that
    resolves outside ALL of these is rejected as a traversal attempt.
    """
    bases: list[Path] = []
    try:
        bases.append(_cache_dir().resolve())
    except Exception:  # pragma: no cover - cache dir creation is best-effort
        pass
    try:
        bases.append(runtime_path(".placeholder").parent.resolve())
    except Exception:  # pragma: no cover
        pass
    bases.append(Path(tempfile.gettempdir()).resolve())
    # De-dup while preserving order.
    seen: set[str] = set()
    uniq: list[Path] = []
    for b in bases:
        s = str(b)
        if s not in seen:
            seen.add(s)
            uniq.append(b)
    return uniq


def _resolve_contained_audio_path(audio_path: str | Path) -> Path:
    """Resolve ``audio_path`` and ensure it stays inside an allowed base dir.

    Raises :class:`ValueError` for absolute paths / ``..`` traversal / any path
    that escapes the allowed media bases (cache, runtime, OS temp).
    """
    resolved = Path(audio_path).resolve()
    for base in _media_base_dirs():
        if resolved == base or resolved.is_relative_to(base):
            return resolved
    raise ValueError(
        f"audio_path {audio_path!r} escapes the allowed media directories"
    )


def _cache_dir() -> Path:
    base = runtime_path("transcripts/.placeholder").parent
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cache_key(audio_bytes: bytes) -> str:
    return hashlib.sha256(audio_bytes).hexdigest()[:32]


def _cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.txt"


async def transcribe(audio_path: str | Path,
                      *, language: str | None = None,
                      model_name: str = "base",
                      use_singleton: bool | None = None) -> dict[str, Any]:
    """Transcribe a local audio file (.mp3/.m4a/.wav). Returns
    ``{text, language, model, segments}``.

    The Whisper large-v3 singleton (Tier 0) is consulted first when
    available. Pass ``use_singleton=False`` to force the legacy tiered
    path. The ``model_name`` argument is honoured only when the call lands
    on Tier 1+ — the singleton is pinned to large-v3.
    """
    try:
        p = _resolve_contained_audio_path(audio_path)
    except ValueError as exc:
        LOG.warning("transcribe: rejected audio_path %r: %s", audio_path, exc)
        return {"error": f"audio_path rejected: {exc}"}
    if not p.exists():
        return {"error": f"file not found: {p}"}
    audio = p.read_bytes()
    key = _cache_key(audio)
    cache = _cache_path(key)
    if cache.exists():
        return {"text": cache.read_text(), "model": "cache", "language": language}

    if use_singleton is None:
        use_singleton = os.environ.get("SHOWME_WHISPER_SINGLETON", "1") != "0"

    # Tier 0: shared large-v3 singleton. We only call it when it is
    # already loaded — if the lifespan warmup hasn't completed yet (or the
    # model failed to load entirely) we fall through to the legacy tiers
    # so the caller still gets a real transcript on first cold-boot rather
    # than a "warmup pending" stub from a service-tier entrypoint.
    if use_singleton:
        try:
            from showme.whisper_analyzer import WhisperAnalyzer  # noqa: PLC0415
            analyzer = WhisperAnalyzer.instance()
            if analyzer is not None:
                envelope = await analyzer.transcribe(p, language=language)
                text = (envelope.get("text") or "").strip()
                if text:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(text)
                return {
                    "text": text,
                    "language": envelope.get("language") or language,
                    "model": f"whisper:{envelope.get('model','whisper-large-v3')}",
                    "segments": envelope.get("chunks", [])[:50],
                }
        except Exception:
            LOG.warning("transcribe tier0 (whisper singleton) failed; "
                        "falling through to legacy tiers", exc_info=True)

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
        LOG.warning("transcribe tier1 (openai-whisper) failed; "
                    "falling through to faster-whisper", exc_info=True)

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
        LOG.warning("transcribe tier2 (faster-whisper) failed; "
                    "falling through to OpenAI API / stub", exc_info=True)

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
                          model_name: str = "base",
                          use_singleton: bool | None = None) -> dict[str, Any]:
    """Download an audio URL into a tmp file and transcribe.

    See :func:`transcribe` for the ``use_singleton`` / ``model_name`` rules.
    """
    import httpx

    # SSRF guard: validate the user-supplied URL (and every redirect hop)
    # against the public-address allowlist BEFORE opening a socket, and never
    # let httpx auto-follow a redirect into an internal host.
    try:
        _assert_public_url(url)
    except UnsafeURLError as exc:
        LOG.warning("transcribe_url: rejected URL %r: %s", url, exc)
        return {"error": f"url rejected: {exc}"}

    current = url
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as cli:
            for _ in range(5):  # bounded redirect chain
                r = await cli.get(current)
                if r.is_redirect:
                    location = r.headers.get("location")
                    if not location:
                        raise UnsafeURLError("redirect without Location header")
                    current = str(httpx.URL(r.url).join(location))
                    _assert_public_url(current)
                    continue
                r.raise_for_status()
                content = r.content
                break
            else:
                raise UnsafeURLError("too many redirects")
    except UnsafeURLError as exc:
        LOG.warning("transcribe_url: redirect rejected for %r: %s", url, exc)
        return {"error": f"url rejected: {exc}"}
    except Exception as e:
        return {"error": f"download: {e}"}
    suffix = url.rsplit(".", 1)[-1].lower()
    if suffix not in ("mp3", "m4a", "wav", "ogg", "flac"):
        suffix = "mp3"
    with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as f:
        f.write(content)
        tmp = f.name
    try:
        return await transcribe(
            tmp,
            language=language,
            model_name=model_name,
            use_singleton=use_singleton,
        )
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
