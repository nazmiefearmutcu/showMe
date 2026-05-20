"""Function-index and per-function execution routes.

* GET  /api/function-index    -> static-ish FunctionIndexEntry list
* GET/POST /api/fn/{code}     -> generic dispatch into the bundled engine
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request

from . import AppDeps
from ._models import FunctionIndexEntry

LOG = logging.getLogger("showme.server.function_index")


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import (
        FUNCTION_TIMEOUT_SECONDS,
        _execute_showme_function,
        _load_function_index,
        _route_function_params,
        fallback_function_payload,
        function_warning_payload,
        json_safe,
        sanitize_function_payload,
    )

    router = APIRouter()

    @router.get("/api/function-index", response_model=list[FunctionIndexEntry])
    async def function_index() -> list[FunctionIndexEntry]:
        entries = list(await asyncio.to_thread(_load_function_index))
        if not entries:
            return []
        return entries

    @router.api_route("/api/fn/{code}", methods=["GET", "POST"])
    async def run_function(code: str, request: Request) -> Any:
        """Resolve and execute any registered ShowMe function.

        Round-14 entry point used by the native panes. Returns the function's
        ``FunctionResult.to_dict()`` directly. Inputs come from query params
        (GET) or JSON body (POST); a ``symbol`` field is bound into a fresh
        ``Instrument`` automatically when present.
        """
        if not deps.boot_state.get("engine_attached"):
            raise HTTPException(status_code=503, detail="ShowMe engine not attached")
        params: dict[str, Any] = {}
        if request.method == "GET":
            params = dict(request.query_params)
        else:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    params = body
            except Exception:
                params = {}
        params = _route_function_params(code, params)
        try:
            result = await _execute_showme_function(code, params)
            deps.boot_state["function_factory_warmed"] = True
            deps.boot_state.pop("function_factory_warm_error", None)
        except HTTPException:
            raise
        except TypeError as exc:
            raise HTTPException(status_code=400, detail=f"argument error: {exc}")
        except TimeoutError:
            return fallback_function_payload(
                code,
                params,
                f"function timed out after {FUNCTION_TIMEOUT_SECONDS:.0f}s",
                "TimeoutError",
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("function %s failed", code)
            return function_warning_payload(code, params, exc)
        try:
            payload = json_safe(result.to_dict())
            return sanitize_function_payload(code, params, payload)
        except Exception:
            payload = json_safe({"code": code.upper(), "data": getattr(result, "data", None)})
            return sanitize_function_payload(code, params, payload)

    app.include_router(router)
