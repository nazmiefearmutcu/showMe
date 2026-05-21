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
    """Register ``factory`` under ``name`` so :func:`get_broker` can look it up."""
    _REGISTRY[name] = factory


def list_brokers() -> list[str]:
    """Return the sorted list of registered broker names."""
    return sorted(_REGISTRY.keys())


def get_broker(name: str | None = None) -> BaseBroker:
    """Return a broker instance.

    ``name`` defaults to ``$SHOWME_BROKER`` and finally to ``"paper"``.
    Raises ``KeyError`` if the requested broker is not registered.
    """
    target = (name or os.environ.get("SHOWME_BROKER") or "paper").strip()
    factory = _REGISTRY.get(target)
    if not factory:
        raise KeyError(f"unknown broker: {target}. registered: {list_brokers()}")
    return factory()


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
            _secrets: dict[str, str] = secrets,
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

        def _factory(_secrets: dict[str, str] = secrets) -> BaseBroker:  # type: ignore[misc]
            # Live Alpaca shares the paper adapter's class — adapter
            # constructor picks base URL from env. Future: dedicated
            # AlpacaLiveBroker; for now we keep the wiring trivial.
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


def close_all_brokers() -> None:
    """Hook for sidecar lifespan shutdown; closes ccxt sessions etc.

    Kept as a no-op-friendly best-effort sweep so the lifespan handler
    can always call it.
    """
    import asyncio
    for name, builder in list(_REGISTRY.items()):
        try:
            broker = builder()
        except Exception:  # noqa: BLE001
            continue
        close = getattr(broker, "aclose", None)
        if close is None:
            continue
        try:
            asyncio.get_event_loop().run_until_complete(close())
        except RuntimeError:
            # No running loop / loop closed — skip.
            pass


# ── Built-in registrations ───────────────────────────────────────────────

register_broker("paper", lambda: PaperBroker())

try:
    from .alpaca import AlpacaPaperBroker

    register_broker("alpaca-paper", lambda: AlpacaPaperBroker())
except Exception as exc:  # noqa: BLE001  # pragma: no cover — optional
    LOG.debug("alpaca broker unavailable: %s", exc)
