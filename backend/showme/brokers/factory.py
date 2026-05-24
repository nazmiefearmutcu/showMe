"""Broker registry — register and discover broker adapters.

Static registrations (``paper``, ``alpaca-paper``) happen at module import.
Per-credential dynamic registrations are added at sidecar boot via
``replay_stored_credentials(store)`` and at runtime via
``register_credential(record, secrets)`` whenever the user adds a
connection through the Connect-Exchange UI.

Registration is idempotent. ``register_broker(name, factory_fn)`` lets
new built-in adapters drop in without touching this file.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BaseBroker
from .catalog.loader import Catalog, load_catalog
from .paper import PaperBroker

if TYPE_CHECKING:  # pragma: no cover
    from .credential_store import CredentialRecord, CredentialStore


LOG = logging.getLogger("showme.brokers.factory")
_REGISTRY: dict[str, Callable[[], BaseBroker]] = {}
_DYNAMIC: dict[str, str] = {}  # credential_id → broker name (for unregister)
_LIVE: dict[str, BaseBroker] = {}  # name → most-recently-instantiated broker; populated by get_broker
_INVALIDATION_HOOKS: list[Callable[[str], None]] = []  # called with credential_id from unregister_credential


def register_invalidation_hook(hook: Callable[[str], None]) -> None:
    """Register a callable invoked on every ``unregister_credential``.

    The callable receives the deleted credential id. Hooks are best-effort:
    individual failures are logged and swallowed so a misbehaving hook
    can't break the credential DELETE path.

    Idempotent: re-registering the same callable is a no-op so tests and
    sidecar dev-reloads don't accumulate duplicates.
    """
    if hook not in _INVALIDATION_HOOKS:
        _INVALIDATION_HOOKS.append(hook)


def unregister_invalidation_hook(hook: Callable[[str], None]) -> None:
    """Remove a hook previously added via ``register_invalidation_hook``."""
    try:
        _INVALIDATION_HOOKS.remove(hook)
    except ValueError:
        pass

_CATALOG: Catalog = Catalog()  # patched at startup; tests override
_ccxt_module = None  # injectable for tests


def _default_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "catalog" / "exchanges.yml"


def _ensure_catalog() -> None:
    global _CATALOG
    if _CATALOG.entries:
        return
    try:
        _CATALOG = load_catalog(_default_catalog_path())
    except Exception as exc:  # noqa: BLE001
        LOG.warning("catalog load failed: %s", exc)


def register_broker(name: str, factory: Callable[[], BaseBroker]) -> None:
    """Register ``factory`` under ``name`` so :func:`get_broker` can look it up.

    C-RUNTIME-3 / C6 follow-up: also evict any previously-cached broker
    instance for ``name`` so the next ``get_broker(name)`` rebuilds against
    the new factory. This matters when credentials are rotated in place
    (re-register with new secrets) or when tests swap a fixture.
    """
    _REGISTRY[name] = factory
    _LIVE.pop(name, None)


def list_brokers() -> list[str]:
    """Return the sorted list of registered broker names."""
    return sorted(_REGISTRY.keys())


def get_broker(name: str | None = None) -> BaseBroker:
    """Return a broker instance.

    ``name`` defaults to ``$SHOWME_BROKER`` and finally to ``"paper"``.
    Raises ``KeyError`` if the requested broker is not registered.

    C-RUNTIME-3 / C6 fix: previously every call built a brand-new broker
    (e.g. ``CcxtBroker`` opening a fresh ``aiohttp`` connector) and the
    previous instance was left dangling without an ``aclose()``. The cache
    in ``_LIVE`` now serves as a per-process pool — the first call builds,
    every subsequent call returns the same instance. ``unregister_credential``
    and ``close_all_brokers`` are the only paths that evict entries.
    """
    target = (name or os.environ.get("SHOWME_BROKER") or "paper").strip()
    factory = _REGISTRY.get(target)
    if not factory:
        raise KeyError(f"unknown broker: {target}. registered: {list_brokers()}")
    cached = _LIVE.get(target)
    if cached is not None:
        return cached
    broker = factory()
    _LIVE[target] = broker
    return broker


# ── Dynamic credential registration ──────────────────────────────────────


def register_credential(record: "CredentialRecord", secrets: dict[str, str]) -> str:
    """Register ``record`` as a broker named ``{exchange_id}:{credential_id}``."""
    _ensure_catalog()
    try:
        entry = _CATALOG.by_id(record.exchange_id)
    except KeyError as exc:
        raise KeyError(f"catalog missing entry for {record.exchange_id}") from exc
    name = f"{record.exchange_id}:{record.id}"
    perms = record.permissions

    if entry.adapter == "ccxt":
        from .ccxt_broker import CcxtBroker

        def _factory(
            _eid: str = entry.ccxt_id or entry.id,
            _secrets: dict[str, str] = dict(secrets),
            _perms: tuple[str, ...] = perms,
        ) -> BaseBroker:
            return CcxtBroker(
                exchange_id=_eid,
                credentials=_secrets,
                permissions=_perms,
                ccxt_module=_ccxt_module,
            )
    elif entry.adapter == "alpaca":
        from .alpaca import AlpacaPaperBroker

        def _factory() -> BaseBroker:
            # Live Alpaca shares the paper adapter's class — adapter
            # constructor picks base URL from env. Future: dedicated
            # AlpacaLiveBroker that accepts the saved `secrets`; for now
            # we keep the wiring trivial and the secrets argument unused.
            return AlpacaPaperBroker()
    else:
        raise KeyError(f"unsupported adapter '{entry.adapter}' in catalog entry {record.exchange_id}")

    register_broker(name, _factory)
    _DYNAMIC[record.id] = name
    LOG.info("registered broker: %s (perms=%s)", name, ",".join(perms))
    return name


def unregister_credential(credential_id: str) -> bool:
    name = _DYNAMIC.pop(credential_id, None)
    if name is None:
        return False
    _REGISTRY.pop(name, None)
    _LIVE.pop(name, None)
    for hook in _INVALIDATION_HOOKS:
        try:
            hook(credential_id)
        except Exception as exc:  # noqa: BLE001
            LOG.debug("invalidation hook %r failed for %s: %s", hook, credential_id, exc)
    LOG.info("unregistered broker: %s", name)
    return True


def replay_stored_credentials(store: "CredentialStore") -> int:
    """Iterate ``store`` and register every credential. Returns count."""
    count = 0
    for rec in store.list():
        try:
            _, secrets = store.get(rec.id)
            register_credential(rec, secrets)
            count += 1
        except Exception as exc:  # noqa: BLE001
            LOG.warning("skip credential %s on replay: %s", rec.id, exc)
    return count


async def close_all_brokers() -> None:
    """Hook for sidecar lifespan shutdown. Awaits ``aclose()`` on every
    broker that's actually been instantiated this process. Best-effort;
    per-broker exceptions are logged and swallowed so one bad close
    can't take down the whole shutdown.
    """
    for name, broker in list(_LIVE.items()):
        close = getattr(broker, "aclose", None)
        if close is None:
            continue
        try:
            await close()
        except Exception as exc:  # noqa: BLE001
            LOG.debug("aclose(%s) ignored: %s", name, exc)
    _LIVE.clear()


# ── Built-in registrations ───────────────────────────────────────────────

register_broker("paper", lambda: PaperBroker())

try:
    from .alpaca import AlpacaPaperBroker

    register_broker("alpaca-paper", lambda: AlpacaPaperBroker())
except Exception as exc:  # noqa: BLE001  # pragma: no cover — optional
    LOG.debug("alpaca broker unavailable: %s", exc)
