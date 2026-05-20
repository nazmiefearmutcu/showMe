"""EMSX, AIM, TSOX, FXGO, BBGT, TCA — trade function suite."""

from __future__ import annotations

import logging
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.broker import (
    BrokerOrder, OrderSide, OrderType, TimeInForce
)
from showme.engine.core.instrument import AssetClass, Instrument

LOG = logging.getLogger("showme.engine.functions.trade")


def _select_broker(deps: Any, asset_class: AssetClass) -> Any:
    """Map asset class → broker adapter from deps."""
    pref = {
        AssetClass.CRYPTO: "binance_broker",
        AssetClass.EQUITY: "alpaca_broker",
        AssetClass.ETF: "alpaca_broker",
        AssetClass.FX: "oanda_broker",
        AssetClass.BOND: "ibkr_broker",
        AssetClass.COMMODITY: "ibkr_broker",
        AssetClass.DERIVATIVE: "ibkr_broker",
    }
    return getattr(deps, pref.get(asset_class, "binance_broker"), None)


@FunctionRegistry.register
class EMSXFunction(BaseFunction):
    """EMSX — Execution Management."""
    code = "EMSX"
    name = "Execution Management"
    category = "trade"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_required",
                    "reason": f"{self.code} ticket requires a symbol before preview or submit.",
                    "broker": "paper",
                    "next_actions": [
                        "Pass ?symbol=... (e.g. ?symbol=EURUSD for FXGO).",
                        "Or set a symbol via the ticket controls in the workspace.",
                    ],
                },
                sources=["paper_ticket"],
                metadata={"preview_only": True},
            )
        quantity = _float_param(params.get("quantity"))
        side = str(params.get("side", "BUY")).upper()
        order_type = str(params.get("type", params.get("order_type", "MARKET"))).upper()
        tif = str(params.get("tif", params.get("time_in_force", "GTC"))).upper()
        submit = _truthy(params.get("submit"))
        if quantity <= 0:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_required",
                    "reason": "Trade ticket needs a positive quantity before it can be previewed or submitted.",
                    "broker": "paper",
                    "symbol": instrument.symbol,
                    "asset_class": instrument.asset_class.value,
                    "side": side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "time_in_force": tif,
                    "tif": tif,
                    "next_actions": [
                        "Enter a positive quantity in the ticket controls.",
                        "Keep submit=false for preview-only runs.",
                    ],
                },
                sources=["paper_ticket"],
                metadata={"preview_only": True},
            )
        broker = _select_broker(self.deps, instrument.asset_class)
        if broker is None and submit:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": (
                        f"No broker is configured for asset class "
                        f"{instrument.asset_class.value}; cannot submit."
                    ),
                    "broker": None,
                    "symbol": instrument.symbol,
                    "asset_class": instrument.asset_class.value,
                    "side": side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "time_in_force": tif,
                    "tif": tif,
                    "next_actions": [
                        "Configure a broker for this asset class in Settings -> Secrets.",
                        "Re-run with submit=false to keep working in preview mode.",
                    ],
                },
                sources=["no_live_source"],
                metadata={
                    "fallback": True,
                    "provider_errors": [
                        f"no broker adapter wired for {instrument.asset_class.value}",
                    ],
                },
            )
        if broker is None or not submit:
            # Session-14 fix: preview used to drop the user-supplied limit
            # price and leverage entirely. The UI then showed an empty
            # "Price: —" row, hiding the fact that the value the user typed
            # was carried through. Echo both fields back so the preview is
            # actually a faithful round-trip of what the trader requested.
            price_param = _float_param(params.get("price"), default=0.0) if params.get("price") not in (None, "") else None
            leverage_param = params.get("leverage")
            preview = {
                "broker": "paper",
                "status": "preview",
                "submit": False,
                "broker_available": broker is not None,
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class.value,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "time_in_force": tif,
                "tif": tif,
                "price": price_param,
                "leverage": leverage_param,
                "next_actions": [
                    "Review the ticket values.",
                    "Use the broker order endpoint or Advanced submit=true only after confirming the trade.",
                ],
            }
            return FunctionResult(code=self.code, instrument=instrument, data=preview,
                                  sources=["paper_ticket"], metadata={"preview_only": True})
        order = BrokerOrder(
            instrument=instrument,
            side=OrderSide(side),
            quantity=quantity,
            order_type=OrderType(order_type),
            price=params.get("price"),
            time_in_force=TimeInForce(tif),
            leverage=params.get("leverage"),
        )
        order_id = await broker.place_order(order)
        # Per PY-LINT-05 P0: do NOT silently swallow audit-write failures
        # after a real broker fill. The local audit row is the regulatory /
        # reconciliation trail; losing it after a successful place_order
        # is the data-loss-mask scenario the audit calls out.
        try:
            from showme.engine.services.order_history import record_order
            record_order(
                broker=broker.name, order_id=str(order_id),
                symbol=instrument.symbol,
                asset_class=instrument.asset_class.value,
                side=order.side.value, quantity=order.quantity,
                price=order.price, leverage=order.leverage,
                type=order.order_type.value, tif=order.time_in_force.value,
                metadata={"client_order_id": order.client_order_id},
            )
        except Exception:
            LOG.exception(
                "audit_event failed for order %s (broker=%s, symbol=%s)",
                order.client_order_id,
                broker.name,
                instrument.symbol,
            )
            raise
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"order_id": order_id, "broker": broker.name})


@FunctionRegistry.register
class AIMFunction(BaseFunction):
    """AIM — Order Management (open + filled across brokers)."""
    code = "AIM"
    name = "Order Management"
    category = "trade"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        out: dict[str, Any] = {}
        provider_errors: list[str] = []
        for name in ("binance_broker", "alpaca_broker", "ibkr_broker", "oanda_broker"):
            broker = getattr(self.deps, name, None)
            if broker is None:
                continue
            try:
                out[name] = await broker.get_open_orders()
            except Exception as exc:  # noqa: BLE001
                out[name] = []
                provider_errors.append(f"{name}.get_open_orders: {exc}")
        # Persisted order history (cross-broker tail)
        raw_limit = params.get("limit", 200)
        try:
            limit_int = int(raw_limit) if raw_limit is not None else 200
        except (TypeError, ValueError):
            limit_int = 200
            provider_errors.append(f"AIM: ignoring non-integer limit={raw_limit!r}")
        try:
            from showme.engine.services.order_history import list_orders
            out["history"] = list_orders(limit=limit_int)
        except Exception as exc:  # noqa: BLE001
            out["history"] = []
            provider_errors.append(f"order_history.list_orders: {exc}")
        if not any(out.values()):
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty",
                    "reason": "No open or recent orders were found in configured brokers or local order history.",
                    "orders": [],
                    "brokers_checked": [
                        "binance_broker",
                        "alpaca_broker",
                        "ibkr_broker",
                        "oanda_broker",
                    ],
                    "next_actions": [
                        "Use BBGT/EMSX/FXGO/TSOX to preview a ticket.",
                        "Submitted broker orders will appear here after they are accepted or filled.",
                    ],
                },
                sources=["order_history"],
                metadata={"empty": True, "provider_errors": provider_errors},
            )
        metadata: dict[str, Any] = {}
        if provider_errors:
            metadata["provider_errors"] = provider_errors
        return FunctionResult(code=self.code, instrument=None, data=out, sources=["order_history"], metadata=metadata)


@FunctionRegistry.register
class TSOXFunction(EMSXFunction):
    """TSOX — Treasury / Bond order ticket."""
    code = "TSOX"
    name = "Treasury Order Entry"
    asset_classes = (AssetClass.BOND,)


@FunctionRegistry.register
class FXGOFunction(EMSXFunction):
    """FXGO — FX trading desk."""
    code = "FXGO"
    name = "FX Trading"


@FunctionRegistry.register
class BBGTFunction(EMSXFunction):
    """BBGT — Bloomberg Trade (multi-asset)."""
    code = "BBGT"
    name = "Multi-Asset Trade Ticket"


# TCA is canonically registered via showme.engine.functions.trade.tca (TCAFunction).
# The legacy stub here was deleted to avoid the duplicate-code drift flagged in
# ARCH-10/PY-LINT-08.


def _float_param(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
