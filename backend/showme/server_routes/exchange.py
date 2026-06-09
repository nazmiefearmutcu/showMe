"""Routes: /api/exchange/* — catalog discovery + credential CRUD.

The CredentialStore is constructed lazily per-request via
``CredentialStore.fresh()`` so a) tests can swap env vars between
requests and b) we don't hold a long-lived reference that hides
state across the lifespan.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.exchange")


def _bot_refs_for_credential(credential_id: str) -> list[Any]:
    """Return BotMeta entries that reference ``credential_id`` (used by cascade)."""
    from showme.bots.store import BotStore
    return [m for m in BotStore.fresh().list() if m.credential_id == credential_id]


async def _cascade_disable_bots(bot_ids: list[str]) -> list[dict[str, str]]:
    """Best-effort cascade-disable for each bot id. C-INT-1 / FIX_CONTRACT.md C3.

    Identical contract to the strategies-route helper, kept here so route
    modules don't form an import cycle.
    """
    from showme.bots.lifespan import get_runner
    from showme.bots.store import BotStore
    results: list[dict[str, str]] = []
    runner = get_runner()
    store = BotStore.fresh()
    for bid in bot_ids:
        try:
            await runner.disable(bid, store)
            locks = getattr(runner, "_locks", None)
            if isinstance(locks, dict):
                locks.pop(bid, None)
            results.append({"bot_id": bid, "status": "disabled"})
        except Exception as exc:  # noqa: BLE001
            LOG.warning("cascade disable failed for bot %s: %s", bid, exc)
            results.append({"bot_id": bid, "status": "error", "error": str(exc)})
    return results


class CredentialCreate(BaseModel):
    exchange_id: str
    account_label: str = Field(..., min_length=1, max_length=64)
    secrets: dict[str, str]
    permissions: list[str] = Field(default_factory=lambda: ["read"])
    skip_test: bool = False


class CredentialPatch(BaseModel):
    permissions: list[str] | None = None
    confirm_account_label: str | None = None


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/exchange/catalog")
    async def exchange_catalog() -> list[dict[str, Any]]:
        from showme.brokers import factory as factory_mod
        factory_mod._ensure_catalog()
        return factory_mod._CATALOG.to_payload()

    @router.get("/api/exchange/credentials")
    async def list_credentials() -> dict[str, Any]:
        from showme.brokers import CredentialStore
        store = CredentialStore.fresh()
        return {"records": [r.to_dict() for r in store.list()]}

    @router.post("/api/exchange/credentials")
    async def create_credential(payload: CredentialCreate) -> dict[str, Any]:
        from showme.brokers import (
            CredentialStore, factory as factory_mod, get_broker,
        )
        factory_mod._ensure_catalog()
        try:
            entry = factory_mod._CATALOG.by_id(payload.exchange_id)
        except KeyError:
            raise HTTPException(400, detail=f"unknown exchange: {payload.exchange_id}")
        missing = [k for k in entry.requires if not payload.secrets.get(k)]
        if missing:
            raise HTTPException(
                400, detail=f"missing required secret fields: {','.join(missing)}",
            )
        for p in payload.permissions:
            if p not in {"read", "trade"}:
                raise HTTPException(400, detail=f"invalid permission: {p}")
        store = CredentialStore.fresh()
        rec = store.add(
            exchange_id=payload.exchange_id,
            account_label=payload.account_label,
            secrets=payload.secrets,
            permissions=tuple(payload.permissions),
        )
        factory_mod.register_credential(rec, payload.secrets)

        if not payload.skip_test:
            try:
                broker = get_broker(f"{payload.exchange_id}:{rec.id}")
                await broker.account()
            except Exception as exc:  # noqa: BLE001
                factory_mod.unregister_credential(rec.id)
                store.delete(rec.id)
                raise HTTPException(400, detail=f"auth test failed: {exc}") from exc

        return rec.to_dict()

    @router.get("/api/exchange/credentials/{credential_id}/dependents")
    async def credential_dependents(credential_id: str) -> dict[str, Any]:
        """List bots that reference ``credential_id``.

        Used by the CONN UI (FIX_CONTRACT.md C9) so the delete-credential
        confirmation can warn that live bots will be cascade-disabled.
        """
        refs = _bot_refs_for_credential(credential_id)
        return {
            "credential_id": credential_id,
            "bot_count": len(refs),
            "bot_ids": [m.id for m in refs],
            "bots": [
                {
                    "id": m.id, "symbol": m.symbol, "mode": m.mode,
                    "enabled": m.enabled,
                }
                for m in refs
            ],
        }

    @router.delete("/api/exchange/credentials/{credential_id}")
    async def delete_credential(
        credential_id: str,
        force: bool = Query(False),
    ) -> dict[str, Any]:
        """Delete a credential. C-INT-1 / FIX_CONTRACT.md C3.

        Without ``force=true``: refuses with 409 when any bot still
        references the credential. With ``force=true``: cascade-disables
        the referencing bots (asyncio task cancelled, ``enabled=False``
        persisted) BEFORE removing the credential from the vault and
        unregistering the broker. This prevents the C-INT-1 zombie-task
        scenario from the audit.
        """
        from showme.brokers import CredentialStore, factory as factory_mod
        store = CredentialStore.fresh()
        # FK check BEFORE delete so a stale 404 doesn't leak references.
        refs = _bot_refs_for_credential(credential_id)
        if refs and not force:
            raise HTTPException(
                409,
                detail={
                    "error": "credential_has_bots",
                    "bot_count": len(refs),
                    "bot_ids": [m.id for m in refs[:10]],
                    "hint": "Use ?force=true to cascade-disable referencing bots.",
                },
            )
        cascade_results: list[dict[str, str]] = []
        if refs and force:
            cascade_results = await _cascade_disable_bots([m.id for m in refs])
        if not store.delete(credential_id):
            raise HTTPException(404, detail="credential not found")
        factory_mod.unregister_credential(credential_id)
        return {
            "ok": True,
            "cascade": cascade_results,
            "bots_affected": len(cascade_results),
        }

    @router.patch("/api/exchange/credentials/{credential_id}")
    async def patch_credential(credential_id: str, payload: CredentialPatch) -> dict[str, Any]:
        from showme.brokers import (
            CredentialStore, UnknownCredential, factory as factory_mod,
        )
        store = CredentialStore.fresh()
        try:
            rec, secrets = store.get(credential_id)
        except UnknownCredential:
            raise HTTPException(404, detail="credential not found")

        if payload.permissions is not None:
            wants_escalation = "trade" in payload.permissions and "trade" not in rec.permissions
            if wants_escalation:
                if payload.confirm_account_label != rec.account_label:
                    raise HTTPException(
                        400,
                        detail="privilege escalation requires confirm_account_label "
                               "matching the credential's account_label",
                    )
            for p in payload.permissions:
                if p not in {"read", "trade"}:
                    raise HTTPException(400, detail=f"invalid permission: {p}")
            rec = store.update_permissions(credential_id, tuple(payload.permissions))
            factory_mod.unregister_credential(credential_id)
            factory_mod.register_credential(rec, secrets)
        return rec.to_dict()

    @router.post("/api/exchange/credentials/{credential_id}/test")
    async def test_credential(credential_id: str) -> dict[str, Any]:
        from showme.brokers import CredentialStore, get_broker
        store = CredentialStore.fresh()
        try:
            rec, _ = store.get(credential_id)
        except KeyError:
            raise HTTPException(404, detail="credential not found")
        try:
            broker = get_broker(f"{rec.exchange_id}:{rec.id}")
            account = await broker.account()
        except Exception as exc:  # noqa: BLE001
            # B1 — a failed test must NOT update last_verified (stay honest).
            return {"ok": False, "error": str(exc)}
        # B1 — only on a genuine successful account() call do we stamp the
        # last-verified timestamp. Metadata-only (no secret), persisted to
        # the JSON index, and echoed back so the CONN pane can show it.
        verified = store.set_last_verified(rec.id)
        return {
            "ok": True,
            "account": account,
            "last_verified": verified.last_verified,
        }

    app.include_router(router)
