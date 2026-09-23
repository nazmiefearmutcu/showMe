"""AlpacaPaperBroker — paper-trading adapter for Alpaca.

Uses the ``v2`` REST API. The HTTP transport is injectable so unit tests
can drive the adapter without ``httpx``.

Environment:
    * ``ALPACA_PAPER_KEY``     — API key id.
    * ``ALPACA_PAPER_SECRET``  — secret.
    * ``ALPACA_PAPER_BASE_URL`` — defaults to https://paper-api.alpaca.markets.
"""
from __future__ import annotations

import os
from typing import Any
from collections.abc import Awaitable, Callable, Sequence

from .base import (
    BaseBroker,
    BrokerError,
    NotSupported,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    TimeInForce,
)

DEFAULT_BASE_URL = "https://paper-api.alpaca.markets"

HttpCall = Callable[[str, str, dict[str, Any] | None, dict[str, Any] | None], Awaitable[dict[str, Any]]]
"""(method, path, query, json_body) → response JSON."""


def _alpaca_status(text: str) -> OrderStatus:
    mapping = {
        "new": OrderStatus.NEW,
        "accepted": OrderStatus.ACCEPTED,
        "pending_new": OrderStatus.ACCEPTED,
        "pending_replace": OrderStatus.ACCEPTED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "filled": OrderStatus.FILLED,
        "canceled": OrderStatus.CANCELLED,
        "cancelled": OrderStatus.CANCELLED,
        "expired": OrderStatus.EXPIRED,
        "rejected": OrderStatus.REJECTED,
    }
    return mapping.get((text or "").lower(), OrderStatus.NEW)


def _to_side(text: str) -> OrderSide:
    return OrderSide.BUY if (text or "").lower() in {"buy", "long"} else OrderSide.SELL


def _to_type(text: str) -> OrderType:
    mapping = {
        "market": OrderType.MARKET,
        "limit": OrderType.LIMIT,
        "stop": OrderType.STOP,
        "stop_limit": OrderType.STOP_LIMIT,
        "stop-limit": OrderType.STOP_LIMIT,
        "trailing_stop": OrderType.MARKET,
        "trailing_stop_limit": OrderType.STOP_LIMIT,
    }
    return mapping.get((text or "market").lower(), OrderType.MARKET)


def _to_tif(text: str) -> TimeInForce:
    mapping = {
        "day": TimeInForce.DAY,
        "gtc": TimeInForce.GTC,
        "ioc": TimeInForce.IOC,
        "fok": TimeInForce.FOK,
        "opg": TimeInForce.DAY,
        "cls": TimeInForce.DAY,
    }
    return mapping.get((text or "day").lower(), TimeInForce.DAY)


def _to_order(payload: dict[str, Any]) -> Order:
    # HNT-05: tolerant mappings — Alpaca returns order types / TIF values
    # (trailing_stop, opg, cls, ...) that have no enum member; a hard
    # OrderType(...) would crash list_orders. Unknown values stay visible
    # in ``raw`` (ccxt_broker pattern).
    side = _to_side(str(payload.get("side", "buy")))
    order_type = _to_type(str(payload.get("type", "market")))
    tif = _to_tif(str(payload.get("time_in_force", "day")))
    qty = float(payload.get("qty") or payload.get("quantity") or 0)
    filled = float(payload.get("filled_qty") or 0)
    avg = payload.get("filled_avg_price")
    avg_f = float(avg) if avg not in (None, "") else None
    return Order(
        id=str(payload.get("id") or payload.get("client_order_id") or ""),
        symbol=str(payload.get("symbol", "")).upper(),
        side=side,
        quantity=qty,
        order_type=order_type,
        time_in_force=tif,
        limit_price=float(payload["limit_price"]) if payload.get("limit_price") not in (None, "") else None,
        stop_price=float(payload["stop_price"]) if payload.get("stop_price") not in (None, "") else None,
        status=_alpaca_status(str(payload.get("status", ""))),
        filled_quantity=filled,
        avg_fill_price=avg_f,
        submitted_at=str(payload.get("submitted_at") or payload.get("created_at") or ""),
        filled_at=str(payload["filled_at"]) if payload.get("filled_at") else None,
        notes=str(payload.get("client_order_id") or ""),
        raw=payload,
    )


def _to_position(payload: dict[str, Any]) -> Position:
    side = (payload.get("side") or "long").lower()
    quantity = abs(float(payload.get("qty") or 0))
    return Position(
        symbol=str(payload.get("symbol", "")).upper(),
        side=OrderSide.BUY if side == "long" else OrderSide.SELL,
        quantity=quantity,
        entry_price=float(payload["avg_entry_price"]) if payload.get("avg_entry_price") else None,
        current_price=float(payload["current_price"]) if payload.get("current_price") else None,
        unrealized_pnl=float(payload["unrealized_pl"]) if payload.get("unrealized_pl") else None,
        realized_pnl=0.0,
        raw=payload,
    )


class AlpacaPaperBroker(BaseBroker):
    name = "alpaca-paper"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        secret: str | None = None,
        base_url: str | None = None,
        http_call: HttpCall | None = None,
        permissions: Sequence[str] | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ALPACA_PAPER_KEY", "")
        self.secret = secret or os.environ.get("ALPACA_PAPER_SECRET", "")
        self.base_url = (
            base_url or os.environ.get("ALPACA_PAPER_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._http_call = http_call
        # HNT-04: permission gate — ``None`` keeps the legacy env-key
        # behaviour ungated; a credential-scoped broker (factory passes the
        # saved credential's permissions) enforces the same "trade" gate
        # as CcxtBroker so a read-only key cannot submit orders.
        self._permissions: tuple[str, ...] | None = (
            tuple(permissions) if permissions is not None else None
        )

    def _require(self, perm: str) -> None:
        if self._permissions is not None and perm not in self._permissions:
            raise NotSupported(
                f"credential lacks '{perm}' permission "
                f"(has: {','.join(self._permissions) or 'none'})"
            )

    # ── HTTP transport (injectable) ──────────────────────────────────────

    async def _call(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if self._http_call is not None:
            return await self._http_call(method, path, query, json_body)
        if not (self.api_key and self.secret):
            raise BrokerError("ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET not configured")
        import httpx  # lazy import — tests inject http_call

        url = f"{self.base_url}{path}"
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.request(
                method, url, headers=headers, params=query, json=json_body,
            )
            if res.status_code >= 400:
                raise BrokerError(f"alpaca {method} {path}: {res.status_code} {res.text}")
            if res.status_code == 204:
                return {}
            return res.json()

    # ── BaseBroker contract ──────────────────────────────────────────────

    async def account(self) -> dict[str, Any]:
        data = await self._call("GET", "/v2/account")
        return {
            "name": self.name,
            "cash": float(data.get("cash") or 0),
            "equity": float(data.get("equity") or 0),
            "buying_power": float(data.get("buying_power") or 0),
            "currency": data.get("currency", "USD"),
            "status": data.get("status", "ACTIVE"),
            "raw": data,
        }

    async def list_positions(self) -> list[Position]:
        rows = await self._call("GET", "/v2/positions")
        return [_to_position(r) for r in rows or []]

    async def list_orders(
        self, *, status: str = "open", limit: int = 100,
    ) -> list[Order]:
        rows = await self._call(
            "GET", "/v2/orders", query={"status": status, "limit": limit},
        )
        return [_to_order(r) for r in rows or []]

    async def submit_order(
        self,
        *,
        symbol: str,
        side: OrderSide | str,
        quantity: float,
        order_type: OrderType | str = OrderType.MARKET,
        time_in_force: TimeInForce | str = TimeInForce.DAY,
        limit_price: float | None = None,
        stop_price: float | None = None,
        notes: str = "",
    ) -> Order:
        if quantity <= 0:
            raise BrokerError("quantity must be positive")
        self._require("trade")
        body: dict[str, Any] = {
            "symbol": symbol.upper(),
            "qty": quantity,
            "side": self.coerce_side(side).value,
            "type": self.coerce_type(order_type).value,
            "time_in_force": self.coerce_tif(time_in_force).value,
        }
        if limit_price is not None:
            body["limit_price"] = limit_price
        if stop_price is not None:
            body["stop_price"] = stop_price
        if notes:
            body["client_order_id"] = notes[:128]
        data = await self._call("POST", "/v2/orders", json_body=body)
        return _to_order(data)

    async def cancel_order(self, order_id: str) -> bool:
        self._require("trade")
        try:
            await self._call("DELETE", f"/v2/orders/{order_id}")
        except BrokerError as exc:
            # Alpaca returns 422 for already-filled orders, surface as False.
            if "422" in str(exc) or "404" in str(exc):
                return False
            raise
        return True

    async def close_position(
        self, symbol: str, *, quantity: float | None = None,
    ) -> Order:
        self._require("trade")
        # HNT-03: Alpaca's DELETE /v2/positions/{symbol} reads the partial
        # close size from the QUERY STRING (the official SDK routes DELETE
        # bodies to params); a JSON body is ignored and the whole position
        # gets liquidated.
        query: dict[str, Any] | None = (
            {"qty": quantity} if quantity is not None else None
        )
        try:
            data = await self._call(
                "DELETE",
                f"/v2/positions/{symbol.upper()}",
                query=query,
            )
        except BrokerError as exc:
            raise NotSupported(str(exc)) from exc
        return _to_order(data)
