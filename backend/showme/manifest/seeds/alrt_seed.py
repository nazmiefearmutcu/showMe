"""ALRT — Alert center (price / change / volume / news conditions).

ALRT is an internal consumer pane: it does not call any external data
provider directly. Instead, it composes signals already surfaced by
WATCH (quotes), TOP (news), and the per-symbol QUOTE service, and fans
out OS-level notifications on threshold breaches. Persistence is the
Round 16 preset filesystem on Tauri (localStorage fallback in the
browser).
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    AlertingSpec,
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
def alrt() -> FunctionManifest:
    return FunctionManifest(
        code="ALRT",
        name="Alert Center",
        category=Category.MISC,
        intent=(
            "Operator alert center that composes price / change / volume / news "
            "conditions from existing panes (WATCH, QUOTE, TOP) and fires native "
            "OS notifications when thresholds trip — no external provider of its own."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.FUTURE,
            AssetClass.INDEX,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Instrument to attach the alert to.",
            ),
            InputSpec(
                name="field",
                label="Field",
                control=ControlKind.SELECT,
                required=True,
                description="Quote field to watch.",
                options=["price", "change_pct", "volume"],
            ),
            InputSpec(
                name="direction",
                label="Direction",
                control=ControlKind.SELECT,
                required=True,
                description="Trigger relationship.",
                options=["above", "below", "cross_up", "cross_down"],
            ),
            InputSpec(
                name="threshold",
                label="Threshold",
                control=ControlKind.NUMBER,
                required=True,
                description="Trigger level in the field's units.",
            ),
            InputSpec(
                name="note",
                label="Note",
                control=ControlKind.TEXT,
                required=False,
                description="Optional operator rationale for the alert.",
            ),
        ],
        defaults={
            "field": "price",
            "direction": "above",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="field", label="Field", kind="tag"),
                ColumnSpec(key="direction", label="Dir", kind="tag"),
                ColumnSpec(key="threshold", label="Level", kind="number", format="%.4f"),
                ColumnSpec(key="active", label="On", kind="tag"),
                ColumnSpec(key="fired_count", label="Fired", kind="number", format="%d"),
                ColumnSpec(key="last_fired_at", label="Last fire", kind="datetime", format="rel"),
                ColumnSpec(key="note", label="Note", kind="text"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="active_count", label="Active", kind="kpi"),
                CardSlot(key="fired_today", label="Fired Today", kind="kpi"),
                CardSlot(key="storage_mode", label="Storage", kind="badge"),
                CardSlot(key="native_notify", label="Notify", kind="badge"),
            ],
        ),
        methodology=(
            "ALRT is a security gate for paper→live transitions and a routing center for "
            "user-defined market conditions. It declares primary='internal' because it owns "
            "no provider: it subscribes to WATCH quotes, the per-symbol QUOTE service, and "
            "TOP news rows. A local poller compares each active rule against the latest "
            "snapshot and, on threshold breach, dispatches the Tauri `notify` command (or "
            "the browser fallback). Persistence rides the Round 16 preset filesystem on "
            "macOS, with localStorage as the cross-platform fallback."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Canonical symbol the rule attaches to.", source="store"),
            "rows[].field": FieldDef(description="Quote field watched (price/change_pct/volume).", source="store"),
            "rows[].direction": FieldDef(description="above / below / cross_up / cross_down.", source="store"),
            "rows[].threshold": FieldDef(description="Trigger level in the field's native units.", source="store"),
            "rows[].active": FieldDef(description="True when the rule is armed.", source="store"),
            "rows[].fired_count": FieldDef(unit="count", description="Total times the rule has fired.", source="store"),
            "rows[].last_fired_at": FieldDef(unit="iso8601", description="Last fire timestamp; null if never.", source="store"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=AlertingSpec(
            conditions=["price_above", "price_below", "change_pct_above", "change_pct_below", "volume_above"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="alrt_add_then_list_round_trip",
                description="Adding an alert persists the row; reload returns it intact with active=True.",
                inputs={"symbol": "AAPL", "field": "price", "direction": "above", "threshold": 200.0},
                assertions=[
                    "row_present_after_reload",
                    "active_is_true",
                    "fired_count_equals_zero",
                ],
            ),
            SemanticTest(
                name="alrt_invalid_threshold_rejected_not_coerced",
                description="A non-finite threshold (Infinity / empty / NaN) is rejected before persisting.",
                inputs={"symbol": "AAPL", "threshold": "Infinity"},
                assertions=["row_not_added", "user_facing_error_present"],
            ),
            SemanticTest(
                name="alrt_internal_only_no_external_provider_calls",
                description="ALRT consumes WATCH/QUOTE/TOP outputs; it never opens a fresh upstream HTTP call.",
                inputs={},
                assertions=["no_outbound_http_during_evaluate"],
            ),
        ],
    )


__all__ = ["alrt"]
