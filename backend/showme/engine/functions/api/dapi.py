"""DAPI — Data API for Excel/external clients (REST surface specification).

Two-tier resolution:
  1. If the running sidecar wired a live route-table provider into
     ``FunctionDeps.dapi_route_provider`` (set by server.py at startup),
     DAPI returns the actual FastAPI routes — guaranteed in sync.
  2. Otherwise DAPI falls back to the curated manifest below, which is
     kept aligned with ``backend/showme/server_routes/*.py``. Audit gate:
     ``backend/tests/test_dapi.py::test_curated_manifest_matches_routes``
     ensures the curated list does not drift from the real router table.
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


# Curated manifest — keep aligned with ``backend/showme/server_routes/*.py``.
# Each row's ``path`` MUST match the FastAPI route exactly (no /api/v1 prefix,
# the live sidecar mounts everything under /api directly).
DAPI_CURATED_ROUTES: list[dict[str, str]] = [
    # ── health / sidecar ──
    {"method": "GET", "path": "/api/health", "purpose": "Sidecar and engine health check.", "request_body": "-", "response_shape": "{ ok, engine }", "mutates_state": "no", "example": "/api/health"},
    {"method": "GET", "path": "/api/sidecar/info", "purpose": "Sidecar version, build metadata, runtime info.", "request_body": "-", "response_shape": "{ version, build, runtime }", "mutates_state": "no", "example": "/api/sidecar/info"},
    {"method": "GET", "path": "/api/sidecar/ticker", "purpose": "Cheap heartbeat for native UI keep-alive.", "request_body": "-", "response_shape": "{ tick, monotonic }", "mutates_state": "no", "example": "/api/sidecar/ticker"},
    # ── function dispatch ──
    {"method": "GET", "path": "/api/function-index", "purpose": "Registered function catalog used by the native sidebar.", "request_body": "-", "response_shape": "FunctionIndexEntry[]", "mutates_state": "no", "example": "/api/function-index"},
    {"method": "GET/POST", "path": "/api/fn/{code}", "purpose": "Run any ShowMe function with JSON params.", "request_body": "{ symbol?, asset_class?, params... }", "response_shape": "FunctionCallResult", "mutates_state": "depends on function", "example": "/api/fn/BQL"},
    # ── quote / symbol ──
    {"method": "GET", "path": "/api/quote/{symbol}", "purpose": "Fast quote lookup for a symbol.", "request_body": "-", "response_shape": "{ symbol, price, change, source }", "mutates_state": "no", "example": "/api/quote/AAPL"},
    {"method": "GET", "path": "/api/symbol/resolve", "purpose": "Resolve user input to a canonical symbol/asset class.", "request_body": "-", "response_shape": "{ symbol, asset_class, source }", "mutates_state": "no", "example": "/api/symbol/resolve?q=btc"},
    # ── portfolio / state ──
    {"method": "GET", "path": "/api/state/positions", "purpose": "Local portfolio position snapshot.", "request_body": "-", "response_shape": "Position[]", "mutates_state": "no", "example": "/api/state/positions"},
    {"method": "GET", "path": "/api/state/trades", "purpose": "Local trade-log snapshot.", "request_body": "-", "response_shape": "Trade[]", "mutates_state": "no", "example": "/api/state/trades"},
    {"method": "GET", "path": "/api/state/migrations", "purpose": "Migration status for persisted local state.", "request_body": "-", "response_shape": "{ applied, pending }", "mutates_state": "no", "example": "/api/state/migrations"},
    {"method": "GET", "path": "/api/llm/cost", "purpose": "Aggregate LLM cost telemetry for local sessions.", "request_body": "-", "response_shape": "{ total_usd, by_model }", "mutates_state": "no", "example": "/api/llm/cost"},
    {"method": "POST", "path": "/api/portfolio/positions/{symbol}/close", "purpose": "Preview or close a local portfolio position.", "request_body": "{ quantity?, dry_run? }", "response_shape": "{ closed, realized_pnl, remaining_qty }", "mutates_state": "yes unless dry_run=true", "example": "/api/portfolio/positions/BTCUSDT/close"},
    # ── broker (paper) ──
    {"method": "GET", "path": "/api/broker/info", "purpose": "Paper broker identity/status.", "request_body": "-", "response_shape": "{ broker, mode }", "mutates_state": "no", "example": "/api/broker/info"},
    {"method": "GET", "path": "/api/broker/positions", "purpose": "Paper broker position snapshot.", "request_body": "-", "response_shape": "Position[]", "mutates_state": "no", "example": "/api/broker/positions"},
    {"method": "POST", "path": "/api/broker/positions/{symbol}/close", "purpose": "Close a paper broker position.", "request_body": "{ quantity?, dry_run? }", "response_shape": "{ closed, realized_pnl }", "mutates_state": "yes unless dry_run=true", "example": "/api/broker/positions/AAPL/close"},
    {"method": "GET", "path": "/api/broker/orders", "purpose": "Paper broker order blotter.", "request_body": "-", "response_shape": "Order[]", "mutates_state": "no", "example": "/api/broker/orders"},
    {"method": "POST", "path": "/api/broker/orders", "purpose": "Create a paper order.", "request_body": "{ symbol, side, qty, type, tif }", "response_shape": "Order", "mutates_state": "yes", "example": "/api/broker/orders"},
    {"method": "DELETE", "path": "/api/broker/orders/{order_id}", "purpose": "Cancel an open paper order.", "request_body": "-", "response_shape": "{ cancelled, order_id }", "mutates_state": "yes", "example": "/api/broker/orders/{order_id}"},
    # ── scanner ──
    {"method": "GET", "path": "/api/scanner/universes", "purpose": "List available scanner universes.", "request_body": "-", "response_shape": "Universe[]", "mutates_state": "no", "example": "/api/scanner/universes"},
    {"method": "POST", "path": "/api/scanner/run", "purpose": "Run a scanner job synchronously.", "request_body": "{ universe, filters? }", "response_shape": "ScanResult", "mutates_state": "no", "example": "/api/scanner/run"},
    # ── MIS (Multi-Indicator Scan) ──
    {"method": "GET", "path": "/api/mis/markets", "purpose": "List MIS market presets (CRYPTO/EQUITY/...).", "request_body": "-", "response_shape": "MarketPreset[]", "mutates_state": "no", "example": "/api/mis/markets"},
    {"method": "GET", "path": "/api/mis/indicators", "purpose": "List MIS indicators with weights.", "request_body": "-", "response_shape": "Indicator[]", "mutates_state": "no", "example": "/api/mis/indicators"},
    {"method": "GET", "path": "/api/mis/config", "purpose": "Read current MIS calibration.", "request_body": "-", "response_shape": "MISConfig", "mutates_state": "no", "example": "/api/mis/config"},
    {"method": "PUT", "path": "/api/mis/config", "purpose": "Update MIS calibration.", "request_body": "MISConfig", "response_shape": "MISConfig", "mutates_state": "yes", "example": "/api/mis/config"},
    {"method": "POST", "path": "/api/mis/scan", "purpose": "Run MIS consensus scan.", "request_body": "{ market, tfs?, limit? }", "response_shape": "MISRow[]", "mutates_state": "no", "example": "/api/mis/scan"},
    # ── INSTANT line ──
    {"method": "GET", "path": "/api/instant/status", "purpose": "INSTANT line status.", "request_body": "-", "response_shape": "{ ok, sources }", "mutates_state": "no", "example": "/api/instant/status"},
    {"method": "GET", "path": "/api/instant/events", "purpose": "INSTANT recent events.", "request_body": "-", "response_shape": "InstantEvent[]", "mutates_state": "no", "example": "/api/instant/events"},
    {"method": "GET", "path": "/api/instant/health", "purpose": "INSTANT health probe.", "request_body": "-", "response_shape": "{ ok }", "mutates_state": "no", "example": "/api/instant/health"},
    {"method": "GET", "path": "/api/instant/performance", "purpose": "INSTANT latency/perf stats.", "request_body": "-", "response_shape": "{ latency_ms_p50, p95 }", "mutates_state": "no", "example": "/api/instant/performance"},
    {"method": "POST", "path": "/api/instant/backfill", "purpose": "Trigger INSTANT backfill for missed events.", "request_body": "{ since?, source? }", "response_shape": "{ inserted, scanned }", "mutates_state": "yes", "example": "/api/instant/backfill"},
    # ── watchlists ──
    {"method": "GET", "path": "/api/watchlists", "purpose": "List local watchlists.", "request_body": "-", "response_shape": "Watchlist[]", "mutates_state": "no", "example": "/api/watchlists"},
    {"method": "PUT", "path": "/api/watchlists/{name}", "purpose": "Create/replace a watchlist.", "request_body": "{ symbols, meta? }", "response_shape": "Watchlist", "mutates_state": "yes", "example": "/api/watchlists/default"},
    {"method": "DELETE", "path": "/api/watchlists/{name}", "purpose": "Delete a watchlist.", "request_body": "-", "response_shape": "{ deleted }", "mutates_state": "yes", "example": "/api/watchlists/default"},
    # ── agent / ASK ──
    {"method": "POST", "path": "/api/agent/best-symbol", "purpose": "Rank open function set for a chosen symbol.", "request_body": "{ symbol }", "response_shape": "RankedFn[]", "mutates_state": "no", "example": "/api/agent/best-symbol"},
    {"method": "POST", "path": "/api/ask", "purpose": "Conversational research assistant.", "request_body": "{ q, history? }", "response_shape": "{ answer, citations }", "mutates_state": "no", "example": "/api/ask"},
    # ── veryfinder ──
    {"method": "GET", "path": "/api/veryfinder/health", "purpose": "VeryFinder health probe.", "request_body": "-", "response_shape": "{ ok }", "mutates_state": "no", "example": "/api/veryfinder/health"},
    {"method": "GET", "path": "/api/veryfinder/query", "purpose": "VeryFinder lookup.", "request_body": "-", "response_shape": "VeryFinderHit[]", "mutates_state": "no", "example": "/api/veryfinder/query?q=mil"},
    {"method": "POST", "path": "/api/veryfinder/article", "purpose": "Submit an article for VeryFinder analysis.", "request_body": "{ url|text }", "response_shape": "VeryFinderArticle", "mutates_state": "yes", "example": "/api/veryfinder/article"},
    {"method": "POST", "path": "/api/veryfinder/batch", "purpose": "Batch VeryFinder analyses.", "request_body": "Article[]", "response_shape": "VeryFinderArticle[]", "mutates_state": "yes", "example": "/api/veryfinder/batch"},
    # ── X sentiment ──
    {"method": "GET", "path": "/api/x/health", "purpose": "X (Twitter) scraper health probe.", "request_body": "-", "response_shape": "{ ok }", "mutates_state": "no", "example": "/api/x/health"},
    {"method": "POST", "path": "/api/x/analyze", "purpose": "Analyse X posts for a symbol.", "request_body": "{ symbol, limit? }", "response_shape": "XSentiment", "mutates_state": "no", "example": "/api/x/analyze"},
    {"method": "POST", "path": "/api/x/classify", "purpose": "Classify ad-hoc posts.", "request_body": "{ posts }", "response_shape": "XClassification[]", "mutates_state": "no", "example": "/api/x/classify"},
    {"method": "GET", "path": "/api/x/symbol_chip", "purpose": "Compact symbol-level sentiment chip data.", "request_body": "-", "response_shape": "{ bullish, mentions }", "mutates_state": "no", "example": "/api/x/symbol_chip?symbol=AAPL"},
    {"method": "GET", "path": "/api/x/instant_events", "purpose": "X-derived events for INSTANT feed.", "request_body": "-", "response_shape": "InstantEvent[]", "mutates_state": "no", "example": "/api/x/instant_events"},
    # ── streaming ──
    {"method": "GET", "path": "/api/stream/stats", "purpose": "WebSocket stream statistics.", "request_body": "-", "response_shape": "{ connections, by_topic }", "mutates_state": "no", "example": "/api/stream/stats"},
    # ── proxy ──
    {"method": "GET/POST/DELETE", "path": "/api/proxy/{path:path}", "purpose": "Auth-aware proxy to a configured upstream.", "request_body": "(passthrough)", "response_shape": "(passthrough)", "mutates_state": "depends", "example": "/api/proxy/some/upstream"},
]


def _resolve_routes(provider: Any) -> list[dict[str, Any]] | None:
    """If the sidecar wired in a live ``deps.dapi_route_provider`` callable
    or list, prefer that over the curated table. The provider must yield
    rows in the same shape as ``DAPI_CURATED_ROUTES``."""
    if provider is None:
        return None
    try:
        candidate = provider() if callable(provider) else provider
    except Exception:
        return None
    if isinstance(candidate, list) and all(isinstance(r, dict) for r in candidate):
        return [dict(r) for r in candidate]
    return None


@FunctionRegistry.register
class DAPIFunction(BaseFunction):
    code = "DAPI"
    name = "ShowMe Data API"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        query = str(params.get("query") or params.get("filter") or "").strip().lower()
        live = _resolve_routes(getattr(self.deps, "dapi_route_provider", None))
        endpoints = live if live is not None else [dict(row) for row in DAPI_CURATED_ROUTES]
        source_mode = "live_router_introspection" if live is not None else "curated_manifest"
        rows = [
            row for row in endpoints
            if not query or query in str(row.get("path", "")).lower() or query in str(row.get("purpose", "")).lower()
        ]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "rows": rows,
                "summary": {
                    "base_url": "http://127.0.0.1:<sidecar-port>",
                    "endpoints": len(rows),
                    "total_routes": len(endpoints),
                    "state_changing": sum(1 for row in rows if str(row.get("mutates_state", "")).startswith("yes")),
                    "filter": query or "all",
                    "source_mode": source_mode,
                },
                "methodology": (
                    "DAPI surfaces the ShowMe sidecar's REST manifest. When the running sidecar "
                    "publishes a live route-introspection callable (deps.dapi_route_provider), DAPI "
                    "returns the actual FastAPI router table so Excel/external clients see the same "
                    "shape the engine serves. Otherwise it falls back to the curated manifest in "
                    "showme/engine/functions/api/dapi.py::DAPI_CURATED_ROUTES — kept aligned with "
                    "backend/showme/server_routes/*.py and audited by tests/test_dapi.py. "
                    "Auth: X-ShowMe-Token (or Authorization: Bearer ...) gates /api/* when "
                    "SHOWME_AUTH_TOKEN is set; /api/health and the sidecar info endpoints stay open."
                ),
                "field_dictionary": {
                    "method": "HTTP verb (comma-joined when a single path accepts multiple verbs).",
                    "path": "Mounted sidecar route.",
                    "purpose": "User-facing action exposed by the route.",
                    "request_body": "JSON body shape when required.",
                    "response_shape": "High-level response contract.",
                    "mutates_state": "Whether the endpoint can change local portfolio/broker state.",
                    "source_mode": "curated_manifest vs live_router_introspection.",
                },
            },
            sources=["showme_fastapi_routes_live" if live is not None else "showme_fastapi_routes_curated"],
        )
