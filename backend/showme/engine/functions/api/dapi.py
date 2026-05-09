"""DAPI — Data API for Excel/external clients (REST surface specification).

This file declares the field contract; FastAPI routes in dashboard/app.py
mount the actual /api/v1/* endpoints. xlwings UDFs in excel/showme_addin.py
hit those endpoints.
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


@FunctionRegistry.register
class DAPIFunction(BaseFunction):
    code = "DAPI"
    name = "ShowMe Data API"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        query = str(params.get("query") or params.get("filter") or "").strip().lower()
        endpoints = [
            {
                "method": "GET",
                "path": "/api/health",
                "purpose": "Sidecar and engine health check.",
                "request_body": "-",
                "response_shape": "{ ok, engine }",
                "mutates_state": "no",
                "example": "/api/health",
            },
            {
                "method": "GET",
                "path": "/api/function-index",
                "purpose": "Registered function catalog used by the native sidebar.",
                "request_body": "-",
                "response_shape": "FunctionIndexEntry[]",
                "mutates_state": "no",
                "example": "/api/function-index",
            },
            {
                "method": "POST",
                "path": "/api/fn/{code}",
                "purpose": "Run any ShowMe function with JSON params.",
                "request_body": "{ symbol?, asset_class?, params... }",
                "response_shape": "FunctionCallResult",
                "mutates_state": "depends on function",
                "example": "/api/fn/BQL",
            },
            {
                "method": "GET",
                "path": "/api/quote/{symbol}",
                "purpose": "Fast quote lookup for a symbol.",
                "request_body": "-",
                "response_shape": "{ symbol, price, change, source }",
                "mutates_state": "no",
                "example": "/api/quote/AAPL",
            },
            {
                "method": "GET",
                "path": "/api/state/positions",
                "purpose": "Local portfolio position snapshot.",
                "request_body": "-",
                "response_shape": "Position[]",
                "mutates_state": "no",
                "example": "/api/state/positions",
            },
            {
                "method": "POST",
                "path": "/api/portfolio/positions/{symbol}/close",
                "purpose": "Preview or close a local portfolio position.",
                "request_body": "{ quantity?, dry_run? }",
                "response_shape": "{ closed, realized_pnl, remaining_qty }",
                "mutates_state": "yes unless dry_run=true",
                "example": "/api/portfolio/positions/BTCUSDT/close",
            },
            {
                "method": "GET",
                "path": "/api/broker/orders",
                "purpose": "Paper broker order blotter.",
                "request_body": "-",
                "response_shape": "Order[]",
                "mutates_state": "no",
                "example": "/api/broker/orders",
            },
            {
                "method": "POST",
                "path": "/api/broker/orders",
                "purpose": "Create a paper order.",
                "request_body": "{ symbol, side, qty, type, tif }",
                "response_shape": "Order",
                "mutates_state": "yes",
                "example": "/api/broker/orders",
            },
            {
                "method": "DELETE",
                "path": "/api/broker/orders/{order_id}",
                "purpose": "Cancel an open paper order.",
                "request_body": "-",
                "response_shape": "{ cancelled, order_id }",
                "mutates_state": "yes",
                "example": "/api/broker/orders/{order_id}",
            },
        ]
        rows = [
            row for row in endpoints
            if not query or query in row["path"].lower() or query in row["purpose"].lower()
        ]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "rows": rows,
                "summary": {
                    "base_url": "http://127.0.0.1:<sidecar-port>",
                    "endpoints": len(rows),
                    "state_changing": sum(1 for row in rows if row["mutates_state"].startswith("yes")),
                    "filter": query or "all",
                },
                "methodology": (
                    "DAPI is a live route manifest for the packaged ShowMe sidecar. "
                    "Rows list actual mounted endpoints, whether they mutate local state, "
                    "the expected request body, and the response shape. Use dry_run=true for portfolio close previews."
                ),
                "field_dictionary": {
                    "method": "HTTP verb.",
                    "path": "Mounted sidecar route.",
                    "purpose": "User-facing action exposed by the route.",
                    "request_body": "JSON body shape when required.",
                    "response_shape": "High-level response contract.",
                    "mutates_state": "Whether the endpoint can change local portfolio/broker state.",
                },
            },
            sources=["showme_fastapi_routes"],
        )
