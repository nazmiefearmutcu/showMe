"""Routes: /api/exchange/* — catalog discovery + credential CRUD.

The CredentialStore is constructed lazily per-request via
``CredentialStore.fresh()`` so a) tests can swap env vars between
requests and b) we don't hold a long-lived reference that hides
state across the lifespan.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import AppDeps


class CredentialCreate(BaseModel):
    exchange_id: str
    account_label: str = Field(..., min_length=1, max_length=64)
    secrets: dict[str, str]
    permissions: list[str] = Field(default_factory=lambda: ["read"])
    skip_test: bool = False


class CredentialPatch(BaseModel):
    permissions: list[str] | None = None
    account_label: str | None = Field(default=None, min_length=1, max_length=64)
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

    @router.delete("/api/exchange/credentials/{credential_id}")
    async def delete_credential(credential_id: str) -> dict[str, Any]:
        from showme.brokers import CredentialStore, factory as factory_mod
        store = CredentialStore.fresh()
        if not store.delete(credential_id):
            raise HTTPException(404, detail="credential not found")
        factory_mod.unregister_credential(credential_id)
        return {"ok": True}

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
            return {"ok": True, "account": account}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    app.include_router(router)
