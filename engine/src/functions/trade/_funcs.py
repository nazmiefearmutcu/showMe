"""EMSX, AIM, TSOX, FXGO, BBGT, TCA — trade function suite."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.broker import (
    BrokerOrder, OrderSide, OrderType, TimeInForce
)
from src.core.instrument import AssetClass, Instrument


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
            raise ValueError
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
        if broker is None or not submit:
            preview = {
                "broker": "paper",
                "status": "preview",
                "submit": False,
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class.value,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "time_in_force": tif,
                "tif": tif,
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
        try:
            from src.services.order_history import record_order
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
            pass
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
        for name in ("binance_broker", "alpaca_broker", "ibkr_broker", "oanda_broker"):
            broker = getattr(self.deps, name, None)
            if broker is None:
                continue
            try:
                out[name] = await broker.get_open_orders()
            except Exception:
                out[name] = []
        # Persisted order history (cross-broker tail)
        try:
            from src.services.order_history import list_orders
            out["history"] = list_orders(limit=int(params.get("limit", 200)))
        except Exception:
            out["history"] = []
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
                metadata={"empty": True},
            )
        return FunctionResult(code=self.code, instrument=None, data=out, sources=["order_history"])


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


@FunctionRegistry.register
class TCAFunction(BaseFunction):
    """TCA — Transaction Cost Analysis."""
    code = "TCA"
    name = "Transaction Cost Analysis"
    category = "trade"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        import json
        from pathlib import Path
        audit = Path("runtime/algo_audit.jsonl")
        if not audit.exists():
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=["no algo audit yet"])
        rows: list[dict] = []
        for line in audit.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        by_parent: dict[str, dict] = {}
        for r in rows:
            pid = r.get("parent_id")
            if not pid:
                continue
            slot = by_parent.setdefault(pid, {"parent_id": pid, "children": [], "errors": []})
            if "error" in r:
                slot["errors"].append(r)
            else:
                slot["children"].append(r)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={"audit_rows": len(rows), "parents": len(by_parent),
                   "by_parent": list(by_parent.values())[:50]},
            sources=["algo_audit"],
        )


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
