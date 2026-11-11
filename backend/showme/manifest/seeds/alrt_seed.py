"""ALRT — Alert center (rule store for price / change / volume / news conditions).

ALRT is an internal function: it calls no external data provider. The
backend keeps alert rule definitions in its own alerts.json store (add /
remove / toggle / list). No background evaluator runs those rules in this
build, so a stored rule does not fire and nothing is delivered. The ALRT
pane keeps its own local rule list (lib/alerts.ts) that the backend does
not read or evaluate.
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
            "Operator alert rule store for price / change / volume / news conditions. "
            "It stores and lists rules; no evaluator runs them in this build, so a "
            "stored rule does not fire — no external provider of its own."
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
                options=["above", "below"],
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
                ColumnSpec(key="condition", label="Condition", kind="text"),
                ColumnSpec(key="enabled", label="Enabled", kind="tag"),
                ColumnSpec(key="cooldown_seconds", label="Cooldown", kind="number", format="%d", unit="s"),
                ColumnSpec(key="note", label="Note", kind="text"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="count", label="Rules", kind="kpi"),
                CardSlot(key="evaluator_status", label="Evaluator", kind="badge"),
            ],
        ),
        methodology=(
            "ALRT declares primary='internal' because it owns no provider. The backend "
            "stores each rule as a condition string (for example AAPL.price > 200, or "
            "NEWS(AAPL).importance >= 70) in its alerts.json store, with a cooldown and an "
            "optional note; add, remove, toggle and list manage that store. Conditions are "
            "validated before they are stored. No background evaluator is wired in this "
            "build, so no stored rule fires and no notification is sent; list reports "
            "evaluator_status not_running. The ALRT pane's own local rule list is separate "
            "from this store."
        ),
        field_dict={
            "alerts[].condition": FieldDef(description="Validated rule condition string.", source="store"),
            "alerts[].enabled": FieldDef(description="Operator on/off flag; does not imply the rule is armed.", source="store"),
            "alerts[].cooldown_seconds": FieldDef(unit="s", description="Minimum seconds between fires once an evaluator exists.", source="store"),
            "alerts[].note": FieldDef(description="Optional operator rationale.", source="store"),
            "alerts[].last_fired": FieldDef(unit="iso8601", description="Always null in this build: nothing fires rules.", source="store"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        # No alerting spec: the backend dispatches no notifications in this build.
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="alrt_add_then_list_round_trip",
                description="Adding an alert persists the row; reload returns it with enabled=True and armed=False (no evaluator in this build).",
                inputs={"symbol": "AAPL", "field": "price", "direction": "above", "threshold": 200.0},
                assertions=[
                    "row_present_after_reload",
                    "enabled_is_true",
                    "armed_is_false",
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
                description="ALRT reads only its own alerts.json store; it consumes no WATCH/QUOTE/TOP output and never opens an upstream HTTP call.",
                inputs={},
                assertions=["no_outbound_http_during_evaluate"],
            ),
        ],
    )


__all__ = ["alrt"]
