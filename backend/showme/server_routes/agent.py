"""Best-symbol agent route."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps

# HNT-06: route-level budget for the agent run. Live mode walks
# candidates x catalog functions serially; without a cap the worst case
# is hours of orphan server-side work after the client aborts (a
# cancelled to_thread keeps running). 120s covers the default probe
# profile (8 candidates, nonblocking) with wide margin.
_AGENT_ROUTE_BUDGET_S = 120.0


def _as_int(value: Any, default: int, *, low: int, high: int) -> int:
    # mis.py parity: a malformed ``max_candidates: "abc"`` used to raise
    # ValueError inside the runtime -> 500 instead of a clean 400.
    try:
        out = int(value) if value not in (None, "") else default
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid integer value: {value!r} ({exc})"
        ) from exc
    return max(low, min(high, out))


def _as_float(value: Any, default: float, *, low: float, high: float) -> float:
    try:
        out = float(value) if value not in (None, "") else default
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid number value: {value!r} ({exc})"
        ) from exc
    return max(low, min(high, out))


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import _run_best_symbol_agent_blocking

    router = APIRouter()

    @router.post("/api/agent/best-symbol")
    async def best_symbol_agent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the full function set over candidate symbols and rank the winner."""
        if not deps.boot_state.get("engine_attached"):
            raise HTTPException(status_code=503, detail="ShowMe engine not attached")
        body = payload or {}
        # HNT-06: validate + clamp the numeric knobs at the route layer
        # (the runtime's own int()/float() calls would 500 on bad types).
        _as_int(body.get("max_candidates"), 8, low=1, high=12)
        _as_float(body.get("per_function_timeout"), 12.0, low=2.0, high=30.0)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_run_best_symbol_agent_blocking, body),
                timeout=_AGENT_ROUTE_BUDGET_S,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=(
                    "best-symbol agent exceeded its "
                    f"{_AGENT_ROUTE_BUDGET_S:.0f}s server budget; narrow "
                    "candidates or function_codes"
                ),
            ) from exc

    app.include_router(router)
