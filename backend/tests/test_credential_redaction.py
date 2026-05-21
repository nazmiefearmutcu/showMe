"""Verify that no api_key / api_secret / passphrase ever lands in a log line."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from showme.brokers.credential_store import CredentialStore, _scrub


def test_scrub_redacts_secret_keys() -> None:
    out = _scrub({"api_key": "AKIAxxx", "api_secret": "shhh",
                  "passphrase": "shhh2", "exchange_id": "binance"})
    assert out["api_key"] == "<redacted>"
    assert out["api_secret"] == "<redacted>"
    assert out["passphrase"] == "<redacted>"
    assert out["exchange_id"] == "binance"


def test_add_does_not_log_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    caplog.set_level(logging.DEBUG, logger="showme")
    store = CredentialStore.fresh()
    store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"api_key": "AKIAxxx_must_not_appear",
                 "api_secret": "secret_must_not_appear"},
        permissions=("read",),
    )
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "AKIAxxx_must_not_appear" not in blob
    assert "secret_must_not_appear" not in blob
