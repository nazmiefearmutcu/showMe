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
        home_swr_capture,
        home_swr_enabled,
        home_swr_get,
        home_swr_key,
        home_swr_schedule,
        home_swr_store,
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
        # Home-page SWR (owner 2026-09-16: the dashboard must load < 1 s):
        # TOP/BRIEF/MOST answer instantly from a warm cache entry, keep
        # serving a stale entry while a background refresh runs, and give a
        # cold call a short head start before returning the honest warming
        # envelope (the in-flight execution is captured into the cache).
        swr_key: str | None = None
        if home_swr_enabled() and code.upper() in ("TOP", "BRIEF", "MOST"):
            swr_key = home_swr_key(code, params)
            hit = home_swr_get(swr_key)
            if hit is not None:
                import time as _time

                if (_time.monotonic() - hit[0]) >= 60.0:
                    home_swr_schedule(code, params, swr_key)
                return hit[1]
            task = asyncio.ensure_future(_execute_showme_function(code, params))
            done, _pending = await asyncio.wait({task}, timeout=1.0)
            if task not in done:
                home_swr_capture(code, params, swr_key, task)
                return fallback_function_payload(
                    code, params, "warming in background", "TimeoutError"
                )
            if task.cancelled():
                home_swr_capture(code, params, swr_key, task)
                return fallback_function_payload(
                    code, params, "warming in background", "TimeoutError"
                )
            try:
                result = task.result()
            except TimeoutError:
                return fallback_function_payload(
                    code,
                    params,
                    f"function timed out after {FUNCTION_TIMEOUT_SECONDS:.0f}s",
                    "TimeoutError",
                )
            except Exception:  # noqa: BLE001 - shared path below reports it
                result = None
            if result is not None:
                payload = sanitize_function_payload(code, params, json_safe(result.to_dict()))
                home_swr_store(swr_key, payload)
                return payload
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
