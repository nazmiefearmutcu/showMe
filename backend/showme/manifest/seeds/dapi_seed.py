"""DAPI — ShowMe sidecar route inspector.

Surfaces the mounted FastAPI routes either via the live router-introspection
callable (when the sidecar publishes ``deps.dapi_route_provider``) or from
the curated route manifest baked into the engine. Read-only.
"""
from __future__ import annotations

from ..enums import (
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    CachingPolicy,
    CardSchema,
    CardSlot,
    ColumnSpec,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def dapi() -> FunctionManifest:
    return FunctionManifest(
        code="DAPI",
        name="ShowMe Data API",
        category=Category.API_DEV,
        intent=(
            "Inspect the ShowMe sidecar's mounted REST routes — method, path, purpose, "
            "request/response shape, and state-mutation flag — for Excel and external clients."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="query",
                label="Filter",
                control=ControlKind.TEXT,
                required=False,
                description="Substring filter on path or purpose; empty returns everything.",
            ),
            InputSpec(
                name="mutates_only",
                label="State-changing only",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Restrict to endpoints that mutate local portfolio/broker state.",
            ),
        ],
        defaults={
            "query": "",
            "mutates_only": False,
        },
        # Internal-only: DAPI introspects the local router, not a remote
        # provider. acceptable_modes is MODELED (curated manifest) or
        # LIVE_OFFICIAL (live router introspection).
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["rows", "summary", "field_dictionary"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="method", label="Method", kind="tag"),
                ColumnSpec(key="path", label="Path", kind="text"),
                ColumnSpec(key="purpose", label="Purpose", kind="text"),
                ColumnSpec(key="request_body", label="Request body", kind="text"),
                ColumnSpec(key="response_shape", label="Response", kind="text"),
                ColumnSpec(key="mutates_state", label="Mutates state", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="endpoints", label="Endpoints", kind="big_number"),
                CardSlot(key="total_routes", label="Total routes", kind="kpi"),
                CardSlot(key="state_changing", label="Mutating", kind="kpi"),
                CardSlot(key="base_url", label="Base URL", kind="badge"),
                CardSlot(key="source_mode", label="Source", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DAPI surfaces the ShowMe sidecar's REST manifest. When the running sidecar publishes a "
            "live route-introspection callable via deps.dapi_route_provider, DAPI returns the actual "
            "FastAPI router table so Excel/external clients see the same shape the engine serves. "
            "Otherwise it falls back to the curated route manifest in engine/functions/api/dapi.py:: "
            "DAPI_CURATED_ROUTES — which is kept aligned with backend/showme/server_routes/*.py and "
            "audited by tests/test_dapi.py. Auth: X-ShowMe-Token (or Authorization: Bearer …) gates "
            "/api/* when SHOWME_AUTH_TOKEN is set; /api/health stays open. Source mode is reported "
            "honestly so callers know whether they got a live snapshot or the curated baseline."
        ),
        field_dict={
            "rows[].method": FieldDef(description="HTTP verb (comma-joined when one path accepts multiple).", source="dapi"),
            "rows[].path": FieldDef(description="Mounted sidecar route.", source="dapi"),
            "rows[].purpose": FieldDef(description="User-facing action exposed by the route.", source="dapi"),
            "rows[].request_body": FieldDef(description="Required JSON body shape, if any.", source="dapi"),
            "rows[].response_shape": FieldDef(description="High-level response contract.", source="dapi"),
            "rows[].mutates_state": FieldDef(description="Whether the endpoint can change local portfolio/broker state.", source="dapi"),
            "summary.source_mode": FieldDef(description="curated_manifest vs live_router_introspection.", source="dapi"),
            "summary.endpoints": FieldDef(unit="count", description="Endpoints returned after filtering.", source="dapi"),
            "summary.total_routes": FieldDef(unit="count", description="All routes known to the manifest.", source="dapi"),
            "summary.state_changing": FieldDef(unit="count", description="How many returned routes can mutate state.", source="dapi"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        semantic_tests=[
            SemanticTest(
                name="dapi_returns_curated_routes_when_no_live_provider",
                description="Without deps.dapi_route_provider, DAPI returns rows from DAPI_CURATED_ROUTES with source_mode=curated_manifest.",
                inputs={},
                assertions=[
                    "rows_length_at_least_1",
                    "summary.source_mode == 'curated_manifest'",
                ],
            ),
            SemanticTest(
                name="dapi_live_provider_overrides_curated",
                description="When a live route provider is wired, DAPI returns the live introspection rows with source_mode=live_router_introspection.",
                inputs={},
                assertions=["summary.source_mode == 'live_router_introspection'"],
            ),
            SemanticTest(
                name="dapi_filter_narrows_rows",
                description="query='quote' returns only rows whose path or purpose contains 'quote'.",
                inputs={"query": "quote"},
                assertions=[
                    "every_row_path_or_purpose_contains_quote",
                    "rows_length_strictly_less_than_total_routes",
                ],
            ),
            SemanticTest(
                name="dapi_mutates_only_excludes_safe_routes",
                description="mutates_only=True excludes /api/health and read-only routes.",
                inputs={"mutates_only": True},
                assertions=["no_row_with_mutates_state_no"],
            ),
        ],
    )


__all__ = ["dapi"]
