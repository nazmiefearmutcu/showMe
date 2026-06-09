"""Credential vault for exchange API keys.

Two backends:
    * macOS Keychain (default) via ``keyring``; service name
      ``com.showme.exchanges``, account key ``{exchange_id}:{credential_id}``.
    * In-memory (test) — selected via ``SHOWME_CREDENTIAL_BACKEND=memory``.

Non-secret metadata is mirrored to a JSON file at
``$SHOWME_HOME/credentials.json`` so the Connect-Exchange UI can list
saved connections without unlocking the keychain on every load. Secrets
never appear in that file.

API is intentionally narrow: ``add``, ``list``, ``get``, ``delete``,
``update_permissions``. All redaction work lives in this module.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

LOG = logging.getLogger("showme.brokers.credential_store")

SERVICE = "com.showme.exchanges"
"""Keychain service name."""

PERMISSION_VALUES = ("read", "trade")
"""Permissions a credential can grant."""


class UnknownCredential(KeyError):
    """Raised when a credential id is not in the vault."""


class CredentialError(RuntimeError):
    """Raised when the vault fails (keychain unavailable, decode error, ...)."""


@dataclass(frozen=True)
class CredentialRecord:
    id: str
    exchange_id: str
    account_label: str
    permissions: tuple[str, ...]
    created_at: str
    # B1 — UTC ISO-8601 timestamp of the last *successful* connection test
    # (a real ``broker.account()`` call). ``None`` means "never verified".
    # This is METADATA, not a secret: it carries no key/secret material and
    # is safe to persist to the JSON index + return in API responses. It lets
    # the CONN pane answer "is this connection actually working / when last
    # verified" honestly instead of implying "connected" without proof.
    last_verified: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "exchange_id": self.exchange_id,
            "account_label": self.account_label,
            "permissions": list(self.permissions),
            "created_at": self.created_at,
            "last_verified": self.last_verified,
        }


class _SecretBackend(Protocol):
    def put(self, key: str, blob: str) -> None: ...
    def get(self, key: str) -> str | None: ...
    def delete(self, key: str) -> bool: ...


class _MemoryBackend:
    """In-memory backend used by tests. Persists to a JSON sidecar so
    multi-process tests (and the multi-process-flavoured fixture in
    ``test_credential_store.py``) can observe each other."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: dict[str, str] = {}
        if path.exists():
            try:
                self._cache = json.loads(path.read_text())
            except Exception:  # noqa: BLE001
                self._cache = {}

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._cache))

    def put(self, key: str, blob: str) -> None:
        self._cache[key] = blob
        self._flush()

    def get(self, key: str) -> str | None:
        return self._cache.get(key)

    def delete(self, key: str) -> bool:
        if key not in self._cache:
            return False
        self._cache.pop(key)
        self._flush()
        return True


class _KeyringBackend:
    """macOS Keychain (or whatever ``keyring.get_keyring()`` returns)."""

    def __init__(self) -> None:
        import keyring
        self._k = keyring

    def put(self, key: str, blob: str) -> None:
        try:
            self._k.set_password(SERVICE, key, blob)
        except Exception as exc:  # noqa: BLE001
            raise CredentialError(f"vault: cannot write {key}: {exc}") from exc

    def get(self, key: str) -> str | None:
        try:
            return self._k.get_password(SERVICE, key)
        except Exception as exc:  # noqa: BLE001
            raise CredentialError(f"vault: cannot read {key}: {exc}") from exc

    def delete(self, key: str) -> bool:
        try:
            self._k.delete_password(SERVICE, key)
            return True
        except Exception:  # noqa: BLE001
            return False


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


_REDACT_KEYS = frozenset({
    "api_key", "api_secret", "passphrase", "secret",
    "private_key", "wallet_address", "uid", "token", "access_token",
    "twofa", "login",
})


def _scrub(blob: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``blob`` with any secret-bearing keys replaced
    by ``"<redacted>"`` so it's safe to log. Covers the full set of
    credential field names that may appear in `catalog/exchanges.yml`
    plus a few common OAuth-style tokens."""
    redacted = {**blob}
    for k in list(redacted.keys()):
        if k in _REDACT_KEYS:
            redacted[k] = "<redacted>"
    return redacted


class CredentialStore:
    """Index + secret backend together. Construct via ``CredentialStore.fresh()``."""

    def __init__(self, backend: _SecretBackend, index_path: Path) -> None:
        self._backend = backend
        self._index_path = index_path
        self._records: dict[str, CredentialRecord] = {}
        self._load_index()

    @classmethod
    def fresh(cls) -> "CredentialStore":
        from showme.app_paths import credentials_path
        raw = os.environ.get("SHOWME_CREDENTIAL_BACKEND") or ""
        backend_name = raw.strip().lower() or "keyring"
        if backend_name not in {"memory", "keyring"}:
            LOG.warning(
                "unknown SHOWME_CREDENTIAL_BACKEND %r; defaulting to keyring", raw,
            )
            backend_name = "keyring"
        index_path = credentials_path()
        if backend_name == "memory":
            mem_sidecar = index_path.with_suffix(".memvault.json")
            backend: _SecretBackend = _MemoryBackend(mem_sidecar)
        else:
            backend = _KeyringBackend()
        return cls(backend, index_path)

    def list(self) -> list[CredentialRecord]:
        return list(self._records.values())

    def get(self, credential_id: str) -> tuple[CredentialRecord, dict[str, str]]:
        rec = self._records.get(credential_id)
        if rec is None:
            raise UnknownCredential(credential_id)
        secret_key = self._secret_key(rec)
        blob = self._backend.get(secret_key)
        if blob is None:
            raise CredentialError(
                f"vault: secrets missing for {credential_id} (key={secret_key})"
            )
        try:
            secrets = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise CredentialError(f"vault: cannot decode secrets for {credential_id}") from exc
        return rec, secrets

    def add(
        self,
        *,
        exchange_id: str,
        account_label: str,
        secrets: dict[str, str],
        permissions: tuple[str, ...] = ("read",),
    ) -> CredentialRecord:
        for p in permissions:
            if p not in PERMISSION_VALUES:
                raise CredentialError(f"invalid permission {p!r}")
        rec = CredentialRecord(
            id=uuid.uuid4().hex,
            exchange_id=exchange_id,
            account_label=account_label,
            permissions=tuple(permissions),
            created_at=_now_iso(),
        )
        self._backend.put(self._secret_key(rec), json.dumps(secrets))
        self._records[rec.id] = rec
        self._save_index()
        LOG.info("credential added: %s", _scrub({"exchange": exchange_id, "label": account_label}))
        return rec

    def delete(self, credential_id: str) -> bool:
        rec = self._records.pop(credential_id, None)
        if rec is None:
            return False
        try:
            self._backend.delete(self._secret_key(rec))
        finally:
            self._save_index()
        return True

    def update_permissions(
        self, credential_id: str, permissions: tuple[str, ...],
    ) -> CredentialRecord:
        for p in permissions:
            if p not in PERMISSION_VALUES:
                raise CredentialError(f"invalid permission {p!r}")
        rec = self._records.get(credential_id)
        if rec is None:
            raise UnknownCredential(credential_id)
        new_rec = replace(rec, permissions=tuple(permissions))
        self._records[credential_id] = new_rec
        self._save_index()
        return new_rec

    def set_last_verified(
        self, credential_id: str, when: str | None = None,
    ) -> CredentialRecord:
        """Record a successful connection test (B1).

        Stamps ``last_verified`` with ``when`` (defaults to now, UTC ISO).
        Metadata-only — carries no secret material — so it is persisted to
        the JSON index. Callers MUST only invoke this after a *successful*
        ``broker.account()`` so the timestamp stays honest.
        """
        rec = self._records.get(credential_id)
        if rec is None:
            raise UnknownCredential(credential_id)
        new_rec = replace(rec, last_verified=when or _now_iso())
        self._records[credential_id] = new_rec
        self._save_index()
        return new_rec

    @staticmethod
    def _secret_key(rec: CredentialRecord) -> str:
        return f"{rec.exchange_id}:{rec.id}"

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        try:
            raw = json.loads(self._index_path.read_text())
        except Exception as exc:  # noqa: BLE001
            LOG.warning("credentials index corrupt; ignoring: %s", exc)
            return
        for r in raw.get("records") or []:
            self._records[r["id"]] = CredentialRecord(
                id=r["id"],
                exchange_id=r["exchange_id"],
                account_label=r["account_label"],
                permissions=tuple(r.get("permissions") or ("read",)),
                created_at=r.get("created_at") or _now_iso(),
                last_verified=r.get("last_verified"),
            )

    def _save_index(self) -> None:
        payload = {"version": 1, "records": [r.to_dict() for r in self._records.values()]}
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
