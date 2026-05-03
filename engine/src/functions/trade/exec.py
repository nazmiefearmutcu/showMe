"""EXEC — VWAP/TWAP execution monitor function."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.services import exec_monitor


@FunctionRegistry.register
class EXECFunction(BaseFunction):
    code = "EXEC"
    name = "Execution Monitor"
    category = "trade"
    description = "Live VWAP/TWAP slice-by-slice fill quality + pace tracking."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "list").lower()
        if action == "open":
            pid = exec_monitor.open_parent(
                parent_id=params["parent_id"],
                symbol=params["symbol"], side=params["side"],
                target_qty=float(params["target_qty"]),
                arrival_price=params.get("arrival_price"),
                algo=params.get("algo", "TWAP"),
                horizon_seconds=int(params.get("horizon_seconds", 600)),
                metadata=params.get("metadata") or {},
            )
            return FunctionResult(code=self.code, instrument=None,
                                  data={"id": pid, "parent_id": params["parent_id"]})
        if action == "slice":
            sid = exec_monitor.record_slice(
                parent_id=params["parent_id"],
                slice_idx=int(params["slice_idx"]),
                qty=float(params["qty"]),
                avg_px=float(params["avg_px"]),
                benchmark_px=params.get("benchmark_px"),
                vwap_running=params.get("vwap_running"),
            )
            return FunctionResult(code=self.code, instrument=None,
                                  data={"slice_id": sid})
        if action == "close":
            ok = exec_monitor.close_parent(
                params["parent_id"],
                status=params.get("status", "complete"))
            return FunctionResult(code=self.code, instrument=None,
                                  data={"closed": ok})
        if action == "get":
            return FunctionResult(code=self.code, instrument=None,
                                  data=exec_monitor.get_parent(params["parent_id"]) or {})
        # default: list
        rows = exec_monitor.list_parents(
            status=params.get("status"),
            symbol=params.get("symbol"),
            limit=int(params.get("limit", 50)))
        return FunctionResult(code=self.code, instrument=None,
                              data={"orders": rows, "n": len(rows)},
                              sources=["exec_monitor"])
