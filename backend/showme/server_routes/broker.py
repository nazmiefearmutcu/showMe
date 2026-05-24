"""Broker routes: account info, positions, orders, cancel."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps
from ._models import OrderRequest

LOG = logging.getLogger("showme.server.broker")


def _expected_confirmation_token(broker_name: str | None) -> str:
    """Return the typed-confirmation string the server expects.

    For ``paper`` (and any short, non-dynamic broker name) the broker
    name itself is the identity — the UI already prints it as the
    expected label in the confirmation modal. For credential-backed
    brokers (registered as ``{exchange_id}:{credential_id}``) we look
    up the credential record and use its ``account_label``.

    Returns ``""`` if the broker can't be resolved or the credential
    has been removed; the route then rejects with 400 so the caller
    cannot submit an ambiguous order.
    """
    if not broker_name:
        # ``None`` → caller wants the env default. Resolve through
        # ``get_broker`` so we still validate against the real name.
        try:
            from showme.brokers import get_broker
            broker_name = get_broker(None).name
        except Exception as exc:  # noqa: BLE001
            LOG.debug("default broker lookup failed: %s", exc)
            return ""
    if ":" not in broker_name:
        # ``paper``, ``alpaca``, etc. — single-token identity.
        return broker_name
    # Dynamic credential broker. Format: ``{exchange_id}:{credential_id}``.
    try:
        _, credential_id = broker_name.split(":", 1)
        from showme.brokers import CredentialStore
        store = CredentialStore.fresh()
        rec, _ = store.get(credential_id)
        return rec.account_label or ""
    except Exception as exc:  # noqa: BLE001
        LOG.debug("credential label lookup failed for %s: %s", broker_name, exc)
        return ""


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/broker/info")
    async def broker_info(name: str | None = None) -> dict[str, Any]:
        from showme.brokers import get_broker, list_brokers
        try:
            broker = get_broker(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            account = await broker.account()
        except Exception as exc:  # noqa: BLE001
            account = {"error": str(exc)}
        return {
            "broker": broker.name,
            "registered": list_brokers(),
            "account": account,
        }

    @router.get("/api/broker/positions")
    async def broker_positions(name: str | None = None) -> dict[str, Any]:
        from showme.brokers import get_broker
        try:
            broker = get_broker(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            rows = await broker.list_positions()
            return {"broker": broker.name, "rows": [r.to_dict() for r in rows]}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/api/broker/positions/{symbol}/close")
    async def broker_close_position(
        symbol: str,
        payload: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        from showme.brokers import get_broker
        body = payload or {}
        try:
            broker = get_broker(
                str(body.get("broker") or name) if (body.get("broker") or name) else None
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        qty = body.get("quantity")
        try:
            quantity = float(qty) if qty not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="quantity must be numeric") from exc
        try:
            order = await broker.close_position(symbol, quantity=quantity)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"broker": broker.name, "order": order.to_dict()}

    @router.get("/api/broker/orders")
    async def broker_orders(
        name: str | None = None,
        status: str = "open",
        limit: int = 100,
    ) -> dict[str, Any]:
        from showme.brokers import get_broker
        try:
            broker = get_broker(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            rows = await broker.list_orders(status=status, limit=limit)
            return {"broker": broker.name, "rows": [r.to_dict() for r in rows]}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/api/broker/orders")
    async def broker_submit_order(payload: OrderRequest) -> dict[str, Any]:
        from showme.brokers import BrokerError, get_broker
        try:
            broker = get_broker(payload.broker)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # SEC-09 — A02-2026-05-24. Server-side typed-confirmation gate.
        # The UI ``OrderTicket.tsx`` makes the user re-type the account
        # label; here we enforce the same contract so any client
        # (curl, mis-wired UI, broken script) gets rejected before the
        # broker is asked to fill anything. Applies to paper too: keeping
        # the contract uniform makes wiring a live credential a no-op for
        # the UI and removes "but it worked in paper" regressions.
        provided = payload.resolved_confirmation()
        expected = _expected_confirmation_token(broker.name)
        if not expected:
            raise HTTPException(
                status_code=400,
                detail=(
                    "confirmation_token required: no active account label "
                    "could be resolved for broker "
                    f"'{broker.name}'. Reconnect the credential and retry."
                ),
            )
        if not provided:
            raise HTTPException(
                status_code=400,
                detail=(
                    "confirmation_token required: client must echo the "
                    "account label as the typed confirmation "
                    f"(expected '{expected}')."
                ),
            )
        if provided != expected:
            raise HTTPException(
                status_code=400,
                detail=(
                    "confirmation_token mismatch: typed label does not "
                    "match the active account."
                ),
            )
        try:
            order = await broker.submit_order(
                symbol=payload.symbol.upper(),
                side=payload.side,
                quantity=payload.quantity,
                order_type=payload.order_type,
                time_in_force=payload.time_in_force,
                limit_price=payload.limit_price,
                stop_price=payload.stop_price,
                notes=payload.notes,
            )
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"broker": broker.name, "order": order.to_dict()}

    @router.delete("/api/broker/orders/{order_id}")
    async def broker_cancel_order(order_id: str, name: str | None = None) -> dict[str, Any]:
        from showme.brokers import get_broker
        try:
            broker = get_broker(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            ok = await broker.cancel_order(order_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"broker": broker.name, "ok": bool(ok)}

    app.include_router(router)
