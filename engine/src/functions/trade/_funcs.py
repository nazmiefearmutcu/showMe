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
        broker = _select_broker(self.deps, instrument.asset_class)
        if broker is None:
            preview = {
                "broker": "paper",
                "status": "preview",
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class.value,
                "side": params.get("side", "BUY"),
                "quantity": float(params.get("quantity", 0) or 0),
            }
            return FunctionResult(code=self.code, instrument=instrument, data=preview,
                                  sources=["paper_ticket"])
        order = BrokerOrder(
            instrument=instrument,
            side=OrderSide(params.get("side", "BUY")),
            quantity=float(params.get("quantity", 0)),
            order_type=OrderType(params.get("type", "MARKET")),
            price=params.get("price"),
            time_in_force=TimeInForce(params.get("tif", "GTC")),
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
            out["history"] = [{"status": "no_open_orders", "broker": "paper"}]
        return FunctionResult(code=self.code, instrument=None, data=out)


@FunctionRegistry.register
class TSOXFunction(EMSXFunction):
    """TSOX — Treasury / Bond order ticket."""
    code = "TSOX"
    name = "Treasury Order Entry"


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
