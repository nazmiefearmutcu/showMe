"""EXEC — VWAP/TWAP execution monitor function."""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.services import exec_monitor


# Required parameter sets per ``action``. Keeping them up here lets
# ``execute`` reject missing fields with a clean ``reason`` message
# instead of dropping a Python ``KeyError`` repr (``"'parent_id'"``)
# straight into the UI — that was the EXEC half of the
# A02-2026-05-24 bug report.
_REQUIRED_BY_ACTION = {
    "open":  ("parent_id", "symbol", "side", "target_qty"),
    "slice": ("parent_id", "slice_idx", "qty", "avg_px"),
    "close": ("parent_id",),
    "get":   ("parent_id",),
}


def _missing_fields(params: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    """Return the subset of ``required`` keys that the caller didn't
    supply, treating ``None`` and empty strings as missing."""
    missing: list[str] = []
    for field in required:
        value = params.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)
    return missing


def _error_result(code: str, action: str, reason: str, *, fields: list[str] | None = None,
                  status: str = "invalid_request") -> FunctionResult:
    data: dict[str, Any] = {"status": status, "action": action, "reason": reason}
    if fields:
        data["missing_fields"] = fields
    return FunctionResult(code=code, instrument=None, data=data, sources=["exec_monitor"],
                          metadata={"error": True, "status": status})


@FunctionRegistry.register
class EXECFunction(BaseFunction):
    code = "EXEC"
    name = "Execution Monitor"
    category = "trade"
    description = "Live VWAP/TWAP slice-by-slice fill quality + pace tracking."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "list").lower()
        required = _REQUIRED_BY_ACTION.get(action)
        if required is not None:
            missing = _missing_fields(params, required)
            if missing:
                return _error_result(
                    self.code, action,
                    f"missing required field(s): {', '.join(missing)}",
                    fields=missing,
                )
        if action == "open":
            try:
                pid = exec_monitor.open_parent(
                    parent_id=params["parent_id"],
                    symbol=params["symbol"], side=params["side"],
                    target_qty=float(params["target_qty"]),
                    arrival_price=params.get("arrival_price"),
                    algo=params.get("algo", "TWAP"),
                    horizon_seconds=int(params.get("horizon_seconds", 600)),
                    metadata=params.get("metadata") or {},
                )
            except (TypeError, ValueError) as exc:
                return _error_result(self.code, action, f"invalid field value: {exc}")
            return FunctionResult(code=self.code, instrument=None,
                                  data={"id": pid, "parent_id": params["parent_id"]})
        if action == "slice":
            # A02-2026-05-24: refuse orphan slices. Recording a slice
            # against a parent_id that the monitor doesn't know about
            # corrupts every downstream metric (avg_fill, pace, IS bps)
            # because compute_metrics joins on parent_id; the row is
            # silently rolled into a non-existent parent. 404 here so
            # the caller surfaces a clean "open the parent first" error.
            parent_id = params["parent_id"]
            if exec_monitor.get_parent(parent_id) is None:
                return _error_result(
                    self.code, action,
                    f"unknown parent_id: '{parent_id}' — open it with action=open first",
                    status="unknown_parent",
                )
            try:
                sid = exec_monitor.record_slice(
                    parent_id=parent_id,
                    slice_idx=int(params["slice_idx"]),
                    qty=float(params["qty"]),
                    avg_px=float(params["avg_px"]),
                    benchmark_px=params.get("benchmark_px"),
                    vwap_running=params.get("vwap_running"),
                )
            except (TypeError, ValueError) as exc:
                return _error_result(self.code, action, f"invalid field value: {exc}")
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
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty",
                    "reason": "No execution parent orders are being monitored.",
                    "orders": [],
                    "n": 0,
                    "next_actions": [
                        "Open a parent order with action=open before monitoring slices.",
                        "Use action=slice to record fill slices, then action=close when complete.",
                    ],
                },
                sources=["exec_monitor"],
                metadata={"empty": True},
            )
        filled_not_closed = [row for row in rows if row.get("status") == "filled_not_closed"]
        status = "needs_close" if filled_not_closed else "ok"
        reason = (
            f"{len(filled_not_closed)} parent order(s) are fully filled but still stored as live."
            if filled_not_closed
            else None
        )
        return FunctionResult(code=self.code, instrument=None,
                              data={
                                  "status": status,
                                  "reason": reason,
                                  "orders": rows,
                                  "n": len(rows),
                                  "next_actions": [
                                      "Close fully filled parent orders with action=close after confirming fills.",
                                      "Inspect per_slice metrics for slippage and benchmark quality.",
                                  ] if filled_not_closed else [],
                              },
                              sources=["exec_monitor"])
