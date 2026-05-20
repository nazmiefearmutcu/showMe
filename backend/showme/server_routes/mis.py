"""MIS routes — Multi Indicator Scan.

* GET  /api/mis/markets       — known markets + universe sizes + default TFs
* GET  /api/mis/indicators    — names of every indicator MIS knows about
* GET  /api/mis/config        — per-market calibration bundle
* PUT  /api/mis/config        — replace the bundle (atomic save)
* POST /api/mis/scan          — run the scan, return top-N ranked rows
* GET  /api/mis/scan/progress — live progress snapshot for the in-flight scan
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException

from . import AppDeps

LOG = logging.getLogger("showme.server.mis")


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import _safe_import, json_safe

    router = APIRouter()

    @router.get("/api/mis/markets")
    async def mis_markets() -> dict[str, Any]:
        from showme.mis import list_markets, MIS_DEFAULT_TIMEFRAMES, MIS_MARKETS
        return {
            "markets": list_markets(),
            "supported": list(MIS_MARKETS),
            "default_timeframes": dict(MIS_DEFAULT_TIMEFRAMES),
        }

    @router.get("/api/mis/indicators")
    async def mis_indicators() -> dict[str, Any]:
        from showme.mis import list_indicator_names
        return {"indicators": list_indicator_names()}

    @router.get("/api/mis/config")
    async def mis_get_config() -> dict[str, Any]:
        from showme.mis import load_mis_config
        return load_mis_config()

    @router.put("/api/mis/config")
    async def mis_put_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        from showme.mis import save_mis_config
        try:
            return save_mis_config(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            LOG.exception("MIS config save failed")
            raise HTTPException(status_code=500, detail=f"save_mis_config: {exc}") from exc

    @router.get("/api/mis/scan/progress")
    async def mis_scan_progress() -> dict[str, Any]:
        """Live progress snapshot. The UI polls this every ~250ms while
        the scan POST is in flight. Returns the same shape regardless of
        scan state (idle/running/done/error) so the UI's parser stays
        simple — ``status`` field disambiguates."""
        from showme.mis import get_scan_progress
        return get_scan_progress()

    @router.post("/api/mis/scan")
    async def mis_scan(payload: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
        from showme.mis import MIS_MARKETS, MisScanRequest, run_mis_scan

        body = payload or {}
        markets = body.get("markets")
        if not isinstance(markets, list) or not markets:
            markets = list(MIS_MARKETS)
        markets = [str(m).upper() for m in markets if isinstance(m, str)]

        timeframes_raw = body.get("timeframes") or {}
        timeframes: dict[str, str] = {}
        if isinstance(timeframes_raw, dict):
            for m, tf in timeframes_raw.items():
                if isinstance(m, str) and isinstance(tf, str):
                    timeframes[m.upper()] = tf

        # New multi-TF override: `tf_set` per market.
        tf_set_raw = body.get("tf_set") or body.get("tf_sets") or body.get("tf_set_override") or {}
        tf_set_override: dict[str, list[str]] = {}
        if isinstance(tf_set_raw, dict):
            for m, tf_list in tf_set_raw.items():
                if isinstance(m, str) and isinstance(tf_list, list):
                    cleaned_list = [str(t) for t in tf_list if isinstance(t, str) and str(t).strip()]
                    if cleaned_list:
                        tf_set_override[m.upper()] = cleaned_list

        # Numeric inputs come from arbitrary JSON bodies — a malformed
        # `top_n: "fast"` previously crashed the route with a 500 ValueError.
        # Validate BEFORE the engine guard so bad input gets 400 even when
        # the engine isn't attached.
        def _as_int(value: Any, default: int, *, low: int | None = None, high: int | None = None) -> int:
            try:
                out = int(value) if value not in (None, "") else default
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"invalid integer value: {value!r} ({exc})"
                ) from exc
            if low is not None:
                out = max(low, out)
            if high is not None:
                out = min(high, out)
            return out

        def _as_float(value: Any, default: float) -> float:
            try:
                return float(value) if value not in (None, "") else default
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"invalid number value: {value!r} ({exc})"
                ) from exc

        top_n = _as_int(body.get("top_n"), 50, low=1, high=500)
        min_confidence = _as_float(body.get("min_confidence"), 0.0)
        only_signals = bool(body.get("only_signals"))
        cap_raw = body.get("max_symbols_per_market")
        if cap_raw in (None, ""):
            cap = None
        else:
            cap = _as_int(cap_raw, 0)
            if cap <= 0:
                cap = None

        if not deps.boot_state.get("engine_attached"):
            raise HTTPException(status_code=503, detail="ShowMe engine not attached")

        factory_mod = _safe_import("showme.engine.services.function_factory")
        if factory_mod is None:
            raise HTTPException(status_code=503, detail="ShowMe modules unavailable")
        try:
            factory = factory_mod.get_factory()
        except Exception as exc:  # noqa: BLE001
            LOG.exception("get_factory failed")
            raise HTTPException(status_code=500, detail=f"factory: {exc}") from exc

        req = MisScanRequest(
            markets=markets,
            timeframes=timeframes,
            tf_set_override=tf_set_override,
            top_n=top_n,
            min_confidence=min_confidence,
            only_signals=only_signals,
            max_symbols_per_market=cap,
        )
        try:
            result = await run_mis_scan(req, getattr(factory, "deps", None))
        except Exception as exc:  # noqa: BLE001
            LOG.exception("mis scan failed")
            # Surface the failure to any UI that's still polling progress
            # — otherwise the bar would freeze at the last in-flight count.
            try:
                from showme.mis import _progress_update
                _progress_update(status="error")
            except Exception:  # noqa: BLE001
                pass
            raise HTTPException(status_code=500, detail=f"mis_scan: {exc}") from exc
        # Indicator results may carry numpy.bool / numpy.float64 inside their
        # ``raw_values`` payloads. FastAPI's pydantic serializer rejects them
        # outright, so coerce the whole tree through ``json_safe`` first.
        return json_safe(result.to_dict())

    app.include_router(router)
