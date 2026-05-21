"""``CcxtBroker(BaseBroker)`` — generic adapter that wraps any ccxt async
exchange. Selected by ``adapter: ccxt`` in the catalog.

Tests mock the ccxt module at construction time via the ``ccxt_module``
parameter; production passes the real ``ccxt`` package.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

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

LOG = logging.getLogger("showme.brokers.ccxt")


def _to_order_status(text: str) -> OrderStatus:
    mapping = {
        "open": OrderStatus.NEW,
        "new": OrderStatus.NEW,
        "accepted": OrderStatus.ACCEPTED,
        "partial": OrderStatus.PARTIALLY_FILLED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "closed": OrderStatus.FILLED,
        "filled": OrderStatus.FILLED,
        "canceled": OrderStatus.CANCELLED,
        "cancelled": OrderStatus.CANCELLED,
        "rejected": OrderStatus.REJECTED,
        "expired": OrderStatus.EXPIRED,
    }
    return mapping.get((text or "").lower(), OrderStatus.NEW)


def _to_side(text: str) -> OrderSide:
    return OrderSide.BUY if (text or "").lower() in {"buy", "long"} else OrderSide.SELL


def _to_type(text: str) -> OrderType:
    text = (text or "market").lower()
    if text in {"market"}:
        return OrderType.MARKET
    if text in {"limit"}:
        return OrderType.LIMIT
    if text in {"stop"}:
        return OrderType.STOP
    if text in {"stop_limit", "stop-limit", "stoplimit"}:
        return OrderType.STOP_LIMIT
    return OrderType.MARKET


def _to_tif(text: str) -> TimeInForce:
    text = (text or "GTC").upper()
    mapping = {"GTC": TimeInForce.GTC, "DAY": TimeInForce.DAY,
               "IOC": TimeInForce.IOC, "FOK": TimeInForce.FOK}
    return mapping.get(text, TimeInForce.GTC)


class CcxtBroker(BaseBroker):
    """One adapter class, ~120 crypto exchanges (whichever ``exchange_id``
    is constructed). ``credentials`` is a dict like
    ``{"api_key": ..., "api_secret": ..., "passphrase": ...}``."""

    def __init__(
        self,
        *,
        exchange_id: str,
        credentials: dict[str, str],
        permissions: Sequence[str],
        ccxt_module: Any | None = None,
    ) -> None:
        if ccxt_module is None:
            import ccxt as ccxt_module  # noqa: PLW2901 — intentional rebind
        try:
            factory = getattr(ccxt_module.async_support, exchange_id)
        except AttributeError as exc:
            raise BrokerError(f"ccxt has no exchange '{exchange_id}'") from exc
        kwargs: dict[str, Any] = {"enableRateLimit": True}
        # ccxt's required-credentials keys are stable: apiKey, secret, password.
        if "api_key" in credentials:
            kwargs["apiKey"] = credentials["api_key"]
        if "api_secret" in credentials:
            kwargs["secret"] = credentials["api_secret"]
        if "passphrase" in credentials:
            kwargs["password"] = credentials["passphrase"]
        # Real ccxt exchanges accept a positional dict; the test mock uses **kwargs.
        # Try positional first (production path), fall back to kwargs spread (test path).
        try:
            self._ex = factory(kwargs)
        except TypeError:
            self._ex = factory(**kwargs)
        self._exchange_id = exchange_id
        self._permissions = tuple(permissions)
        self.name = f"ccxt:{exchange_id}"

    def _require(self, perm: str) -> None:
        if perm not in self._permissions:
            raise NotSupported(
                f"credential lacks '{perm}' permission "
                f"(has: {','.join(self._permissions) or 'none'})"
            )

    async def aclose(self) -> None:
        try:
            await self._ex.close()
        except Exception as exc:  # noqa: BLE001
            LOG.debug("ccxt %s close ignored: %s", self._exchange_id, exc)

    async def account(self) -> dict[str, Any]:
        bal = await self._ex.fetch_balance()
        return self._normalise_account(bal)

    async def list_positions(self) -> list[Position]:
        try:
            rows = await self._ex.fetch_positions()
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"fetch_positions failed: {exc}") from exc
        out: list[Position] = []
        for r in rows or []:
            contracts = float(r.get("contracts") or r.get("contractSize") or 0)
            if contracts == 0:
                continue
            out.append(self._to_position(r, contracts))
        return out

    async def list_orders(self, *, status: str = "open", limit: int = 100) -> list[Order]:
        try:
            if status == "open":
                rows = await self._ex.fetch_open_orders(limit=limit)
            else:
                fn = getattr(self._ex, "fetch_closed_orders", None)
                if fn is None:
                    raise NotSupported(f"{self._exchange_id} has no fetch_closed_orders")
                rows = await fn(limit=limit)
        except NotSupported:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"list_orders failed: {exc}") from exc
        return [self._to_order(r) for r in (rows or [])]

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
        self._require("trade")
        s = self.coerce_side(side)
        t = self.coerce_type(order_type)
        params: dict[str, Any] = {}
        if stop_price is not None:
            params["stopPrice"] = stop_price
        if notes:
            params["clientOrderId"] = notes
        try:
            raw = await self._ex.create_order(
                symbol=symbol,
                type=t.value if t != OrderType.MARKET else "market",
                side=s.value,
                amount=quantity,
                price=limit_price,
                params=params,
            )
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"create_order failed: {exc}") from exc
        return self._to_order(raw)

    async def cancel_order(self, order_id: str) -> bool:
        self._require("trade")
        try:
            await self._ex.cancel_order(order_id)
            return True
        except Exception as exc:  # noqa: BLE001
            LOG.debug("cancel_order(%s) → %s", order_id, exc)
            return False

    async def close_position(self, symbol: str, *, quantity: float | None = None) -> Order:
        self._require("trade")
        positions = await self.list_positions()
        target = next((p for p in positions if p.symbol == symbol), None)
        if target is None:
            raise BrokerError(f"no open position in {symbol}")
        qty = float(quantity) if quantity is not None else target.quantity
        opposite_side = OrderSide.SELL if target.side == OrderSide.BUY else OrderSide.BUY
        return await self.submit_order(
            symbol=symbol, side=opposite_side, quantity=qty,
            order_type=OrderType.MARKET, time_in_force=TimeInForce.IOC,
            notes="close_position",
        )

    @staticmethod
    def _normalise_account(bal: dict[str, Any]) -> dict[str, Any]:
        total = bal.get("total") or {}
        free = bal.get("free") or {}
        ccy = max(total.keys(), key=lambda c: float(total.get(c) or 0), default="USD")
        equity = float(total.get(ccy) or 0)
        cash = float(free.get(ccy) or 0)
        return {
            "cash": cash,
            "equity": equity,
            "buying_power": cash,
            "currency": ccy,
            "raw": bal.get("info") or {},
        }

    @staticmethod
    def _to_position(raw: dict[str, Any], contracts: float) -> Position:
        side = _to_side(raw.get("side") or "long")
        entry = raw.get("entryPrice") or raw.get("entry_price")
        mark = raw.get("markPrice") or raw.get("mark_price") or raw.get("lastPrice")
        pnl = raw.get("unrealizedPnl") or raw.get("unrealized_pnl")
        return Position(
            symbol=str(raw.get("symbol", "")),
            side=side,
            quantity=float(contracts),
            entry_price=float(entry) if entry not in (None, "") else None,
            current_price=float(mark) if mark not in (None, "") else None,
            unrealized_pnl=float(pnl) if pnl not in (None, "") else None,
            raw=raw,
        )

    @staticmethod
    def _to_order(raw: dict[str, Any]) -> Order:
        return Order(
            id=str(raw.get("id") or ""),
            symbol=str(raw.get("symbol", "")),
            side=_to_side(raw.get("side") or "buy"),
            quantity=float(raw.get("amount") or 0),
            order_type=_to_type(raw.get("type") or "market"),
            time_in_force=_to_tif(raw.get("timeInForce") or "GTC"),
            limit_price=float(raw["price"]) if raw.get("price") not in (None, "") else None,
            stop_price=float(raw["stopPrice"]) if raw.get("stopPrice") not in (None, "") else None,
            status=_to_order_status(str(raw.get("status") or "")),
            filled_quantity=float(raw.get("filled") or 0),
            avg_fill_price=float(raw["average"]) if raw.get("average") not in (None, "") else None,
            submitted_at=str(raw.get("datetime") or raw.get("timestamp") or ""),
            filled_at=str(raw.get("lastTradeTimestamp") or "") or None,
            notes=str(raw.get("clientOrderId") or ""),
            raw=raw,
        )
