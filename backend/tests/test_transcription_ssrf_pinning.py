"""SEC-7 (wc3-g07): the audio download SSRF guard pins the connection.

The guard validates the resolved address, and the request must then connect
to that same address (not re-resolve the name, which a DNS-rebinding host can
answer with 127.0.0.1 or 169.254.x.x). No network: DNS and httpx are faked.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any

import httpx
import pytest

from showme.engine.services import transcription

PUBLIC_IP = "93.184.216.34"


def _addrinfo(ip: str) -> list[tuple[Any, ...]]:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (ip, 443))]


@pytest.fixture
def dns(monkeypatch):
    """Records getaddrinfo calls. Each name first answers public, then rebinds to
    loopback on any later lookup (the DNS-rebinding pattern)."""
    calls: list[str] = []
    answered: set[str] = set()

    def _fake_getaddrinfo(host, *args, **kwargs):
        calls.append(str(host))
        try:  # an IP literal resolves to itself, as the real resolver does
            return _addrinfo(str(ipaddress.ip_address(str(host))))
        except ValueError:
            pass
        if str(host) in answered:
            return _addrinfo("127.0.0.1")
        answered.add(str(host))
        return _addrinfo(PUBLIC_IP)

    monkeypatch.setattr(transcription.socket, "getaddrinfo", _fake_getaddrinfo)
    return calls


@pytest.fixture
def http(monkeypatch):
    """Scripted httpx responses; records each request target and its headers."""
    seen: list[dict[str, Any]] = []
    script: list[httpx.Response] = []

    async def _fake_get(self, url, *args, headers=None, extensions=None, **kwargs):
        seen.append({"url": str(url), "headers": dict(headers or {}),
                     "extensions": dict(extensions or {})})
        response = script.pop(0)
        response.request = httpx.Request("GET", str(url))
        return response

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)

    async def _fake_transcribe(path, **kwargs):
        return {"text": "ok", "model": "fake"}

    monkeypatch.setattr(transcription, "transcribe", _fake_transcribe)
    return seen, script


def _run(url: str) -> dict[str, Any]:
    return asyncio.run(transcription.transcribe_url(url))


def test_download_connects_to_the_validated_address_not_the_name(dns, http) -> None:
    seen, script = http
    script.append(httpx.Response(200, content=b"audio-bytes"))
    out = _run("https://feeds.example.com/episode.mp3")
    assert out == {"text": "ok", "model": "fake"}
    # The name is resolved exactly once: the validated address is the target.
    assert dns == ["feeds.example.com"]
    assert len(seen) == 1
    assert seen[0]["url"].startswith(f"https://{PUBLIC_IP}/"), seen[0]["url"]
    assert seen[0]["headers"]["Host"] == "feeds.example.com"
    assert seen[0]["extensions"]["sni_hostname"] == "feeds.example.com"


def test_pinned_request_keeps_port_and_path(dns, http) -> None:
    seen, script = http
    script.append(httpx.Response(200, content=b"audio-bytes"))
    _run("https://feeds.example.com:8443/a/b.mp3?x=1")
    assert seen[0]["url"] == f"https://{PUBLIC_IP}:8443/a/b.mp3?x=1"
    assert seen[0]["headers"]["Host"] == "feeds.example.com:8443"


def test_redirect_to_an_internal_address_is_rejected(dns, http) -> None:
    seen, script = http
    script.append(httpx.Response(302, headers={"location": "http://127.0.0.1/admin"}))
    out = _run("https://feeds.example.com/episode.mp3")
    assert "url rejected" in out.get("error", "")
    assert len(seen) == 1  # the internal hop is never requested


def test_redirect_to_a_name_is_validated_and_pinned_too(dns, http) -> None:
    seen, script = http
    script.append(httpx.Response(302, headers={"location": "https://cdn.example.net/x.mp3"}))
    script.append(httpx.Response(200, content=b"audio-bytes"))
    dns.clear()
    _run("https://feeds.example.com/episode.mp3")
    assert dns == ["feeds.example.com", "cdn.example.net"]
    assert seen[1]["url"].startswith(f"https://{PUBLIC_IP}/")
    assert seen[1]["extensions"]["sni_hostname"] == "cdn.example.net"


def test_private_literal_host_is_refused_before_any_request(http) -> None:
    seen, _ = http
    out = _run("http://127.0.0.1/audio.mp3")
    assert "url rejected" in out.get("error", "")
    assert seen == []


def test_assert_public_url_returns_the_validated_address(monkeypatch) -> None:
    monkeypatch.setattr(transcription.socket, "getaddrinfo",
                        lambda host, *a, **k: _addrinfo(PUBLIC_IP))
    assert transcription._assert_public_url("https://feeds.example.com/x") == PUBLIC_IP
