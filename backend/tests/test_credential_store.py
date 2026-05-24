"""CredentialStore CRUD tests against the in-memory backend.

The memory backend is selected via SHOWME_CREDENTIAL_BACKEND=memory so
we never touch the real macOS keychain in CI.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from showme.brokers.credential_store import (
    CredentialRecord,
    CredentialStore,
    UnknownCredential,
)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CredentialStore:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    return CredentialStore.fresh()


def test_add_and_list(store: CredentialStore) -> None:
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
    )
    assert isinstance(rec, CredentialRecord)
    assert rec.exchange_id == "binance"
    assert rec.account_label == "main"
    assert rec.permissions == ("read",)
    listed = store.list()
    assert len(listed) == 1
    assert listed[0].id == rec.id


def test_get_returns_record_and_secrets(store: CredentialStore) -> None:
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
    )
    got, secrets = store.get(rec.id)
    assert got.id == rec.id
    assert secrets == {"api_key": "k", "api_secret": "s"}


def test_get_unknown_raises(store: CredentialStore) -> None:
    with pytest.raises(UnknownCredential):
        store.get("does-not-exist")


def test_delete_removes_record_and_secrets(store: CredentialStore) -> None:
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
    )
    assert store.delete(rec.id) is True
    assert store.list() == []
    with pytest.raises(UnknownCredential):
        store.get(rec.id)
    assert store.delete(rec.id) is False  # idempotent re-delete


def test_multi_account_same_exchange(store: CredentialStore) -> None:
    main = store.add(
        exchange_id="binance", account_label="main",
        secrets={"api_key": "k1", "api_secret": "s1"}, permissions=("read",),
    )
    tax = store.add(
        exchange_id="binance", account_label="tax-2026",
        secrets={"api_key": "k2", "api_secret": "s2"}, permissions=("read", "trade"),
    )
    assert main.id != tax.id
    listed = sorted(store.list(), key=lambda r: r.account_label)
    assert [r.account_label for r in listed] == ["main", "tax-2026"]


def test_update_permissions_returns_new_record(store: CredentialStore) -> None:
    rec = store.add(
        exchange_id="binance", account_label="main",
        secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",),
    )
    updated = store.update_permissions(rec.id, ("read", "trade"))
    assert updated.id == rec.id
    assert updated.permissions == ("read", "trade")
    listed = store.list()
    assert listed[0].permissions == ("read", "trade")


def test_metadata_persists_to_credentials_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Metadata writes survive a fresh CredentialStore.fresh() (re-load)."""
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    store1 = CredentialStore.fresh()
    rec = store1.add(
        exchange_id="binance", account_label="main",
        secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",),
    )
    store2 = CredentialStore.fresh()
    listed = store2.list()
    assert len(listed) == 1
    assert listed[0].id == rec.id
    got, secrets = store2.get(rec.id)
    assert secrets == {"api_key": "k", "api_secret": "s"}


def test_unknown_backend_env_falls_back_to_keyring_with_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memoryy")  # typo
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    import logging
    caplog.set_level(logging.WARNING, logger="showme.brokers.credential_store")
    # We don't actually want to construct a real keychain backend in CI;
    # just verify the fallback decision + warning log line. Patch
    # _KeyringBackend to a stub so the test doesn't depend on the host
    # keyring.
    import showme.brokers.credential_store as cs

    class _StubKeyring:
        def __init__(self): pass
        def put(self, k, v): pass
        def get(self, k): return None
        def delete(self, k): return False

    monkeypatch.setattr(cs, "_KeyringBackend", _StubKeyring)
    store = cs.CredentialStore.fresh()
    assert isinstance(store._backend, _StubKeyring)  # type: ignore[attr-defined]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("memoryy" in r.getMessage() for r in warnings)
