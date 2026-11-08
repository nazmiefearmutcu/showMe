"""SEC-6: the plaintext memory vault needs an explicit opt-in and is not silent.

``SHOWME_CREDENTIAL_BACKEND=memory`` stores exchange API secrets as plaintext
JSON. A stray env var must not move real keys out of the OS keyring, so the
memory backend is refused unless ``SHOWME_ALLOW_PLAINTEXT_VAULT=1`` is set,
and when it is active the store logs a warning and writes the file owner-only.

The keyring is replaced by a stub, so nothing touches the host keychain.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

import showme.brokers.credential_store as cs

SECRET_VALUE = "sec6-plaintext-probe-do-not-leak"


class _StubKeyring:
    """Records every put so the test can see where secrets went."""

    puts: list[tuple[str, str]] = []

    def __init__(self) -> None:
        pass

    def put(self, key: str, blob: str) -> None:
        _StubKeyring.puts.append((key, blob))

    def get(self, key: str) -> str | None:
        for k, v in _StubKeyring.puts:
            if k == key:
                return v
        return None

    def delete(self, key: str) -> bool:
        return False


@pytest.fixture
def stub_keyring(monkeypatch: pytest.MonkeyPatch) -> type[_StubKeyring]:
    _StubKeyring.puts = []
    monkeypatch.setattr(cs, "_KeyringBackend", _StubKeyring)
    return _StubKeyring


@pytest.fixture
def memory_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.delenv("SHOWME_ALLOW_PLAINTEXT_VAULT", raising=False)
    return tmp_path


def _add_probe(store: cs.CredentialStore) -> None:
    store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"api_key": "k", "api_secret": SECRET_VALUE},
        permissions=("read",),
    )


def _files_containing(root: Path, needle: str) -> list[Path]:
    hits: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and needle in path.read_text(encoding="utf-8", errors="ignore"):
            hits.append(path)
    return hits


def test_memory_backend_is_refused_without_explicit_flag(
    memory_env: Path, stub_keyring: type[_StubKeyring], caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="showme.brokers.credential_store")
    store = cs.CredentialStore.fresh()

    # Falls back to the keyring, never to the plaintext file.
    assert not isinstance(store._backend, cs._MemoryBackend)  # type: ignore[attr-defined]
    assert isinstance(store._backend, stub_keyring)  # type: ignore[attr-defined]
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("SHOWME_ALLOW_PLAINTEXT_VAULT" in r.getMessage() for r in errors)

    _add_probe(store)
    assert stub_keyring.puts, "secret must go to the keyring"
    assert not list(memory_env.rglob("*.memvault.json"))
    assert _files_containing(memory_env, SECRET_VALUE) == []


@pytest.mark.parametrize("flag", ["0", "", "no"])
def test_non_truthy_flag_does_not_enable_plaintext_vault(
    memory_env: Path,
    stub_keyring: type[_StubKeyring],
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
) -> None:
    monkeypatch.setenv("SHOWME_ALLOW_PLAINTEXT_VAULT", flag)
    store = cs.CredentialStore.fresh()
    assert not isinstance(store._backend, cs._MemoryBackend)  # type: ignore[attr-defined]


def test_memory_backend_with_explicit_flag_warns_loudly(
    memory_env: Path,
    stub_keyring: type[_StubKeyring],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SHOWME_ALLOW_PLAINTEXT_VAULT", "1")
    caplog.set_level(logging.WARNING, logger="showme.brokers.credential_store")
    store = cs.CredentialStore.fresh()

    assert isinstance(store._backend, cs._MemoryBackend)  # type: ignore[attr-defined]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("PLAINTEXT" in r.getMessage() for r in warnings)

    _add_probe(store)
    assert list(memory_env.rglob("*.memvault.json")), "plaintext vault is written"
    assert stub_keyring.puts == [], "keyring must not be used on the memory path"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not meaningful on Windows")
def test_memvault_file_is_owner_only_on_posix(
    memory_env: Path,
    stub_keyring: type[_StubKeyring],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHOWME_ALLOW_PLAINTEXT_VAULT", "1")
    store = cs.CredentialStore.fresh()
    _add_probe(store)
    vault = next(memory_env.rglob("*.memvault.json"))
    assert vault.stat().st_mode & 0o077 == 0, oct(vault.stat().st_mode)
