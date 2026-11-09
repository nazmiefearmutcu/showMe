"""P1a-g03 BIO#1 — BIO must not claim a macOS bridge on other hosts.

BIOFunction returned hard-coded rows saying the macOS LocalAuthentication
bridge is available, labeled as live data, on every platform. On Windows the
Tauri shell denies every prompt, so the claim was false. The fixed function
derives the capability rows from the host platform and labels its static
documentation as reference, not live.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from showme.engine.functions.misc._extras import BIOFunction


def _run():
    return asyncio.run(BIOFunction().execute())


def _capability_status(result) -> str:
    row = next(r for r in result.data["rows"] if r["action"] == "capabilities")
    return row["status"]


def test_non_macos_host_does_not_claim_native_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    result = _run()
    # RED before fix: status was "native_bridge_available" on every host.
    assert _capability_status(result) != "native_bridge_available"
    assert _capability_status(result) == "unavailable_non_macos"
    assert result.data["status"] == "unavailable"
    assert result.data["reason"] and "macOS" in result.data["reason"]
    assert any("macOS" in w for w in result.warnings)


def test_non_macos_verify_row_is_denied_not_user_initiated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    result = _run()
    verify = next(r for r in result.data["rows"] if r["action"] == "verify")
    assert verify["status"] == "denied_non_macos"
    card_values = {c["label"]: c["value"] for c in result.data["cards"]}
    assert card_values["Prompt"] == "unavailable"


def test_static_documentation_is_labeled_reference_not_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    result = _run()
    # RED before fix: sources were ["macos_local_auth_bridge"] (classified live).
    assert result.sources == ["static_reference_documentation"]
    assert result.metadata.get("live") is False
    assert result.metadata.get("mode") == "reference"
    assert result.metadata.get("host_platform") == "win32"


def test_macos_host_reports_bridge_as_expected_not_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    result = _run()
    # The sidecar cannot probe LocalAuthentication itself; the Tauri shell does.
    assert _capability_status(result) == "native_bridge_expected"
    assert result.data["status"] == "ready"
    assert result.sources == ["static_reference_documentation"]
    assert result.metadata.get("live") is False


def test_non_macos_methodology_does_not_claim_bridge_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    result = _run()
    # RED before fix: the methodology said BIO "uses the native macOS
    # LocalAuthentication bridge" regardless of host.
    methodology = result.data["methodology"]
    assert "uses the native macOS" not in methodology
    assert "win32" in methodology or "not available" in methodology
