"""CACT — Corporate Actions (8-K, splits, M&A, name change).

SEC EDGAR is the canonical source for 8-K filings; yfinance provides the
clean split / dividend / merger events. Both are normalized into a single
typed action list (date, type, value/text, source filing URL when known).
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
def cact() -> FunctionManifest:
    return FunctionManifest(
        code="CACT",
        name="Corporate Actions",
        category=Category.EQUITIES,
        intent=(
            "List recent corporate actions for a company: 8-K filings, stock splits, dividends, "
            "M&A events, and name changes, ranked by event date."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker.",
            ),
            InputSpec(
                name="months",
                label="History (months)",
                control=ControlKind.NUMBER,
                required=False,
                description="Lookback for action list.",
                min=3,
                max=60,
                step=1,
                unit="months",
            ),
            InputSpec(
                name="action_types",
                label="Action types",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Filter the action stream.",
                options=["split", "dividend", "merger", "name_change", "8-K"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "months": 24,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="sec_edgar",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=14400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "actions"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="date", label="Date", kind="date"),
                ColumnSpec(key="action_type", label="Type", kind="tag"),
                ColumnSpec(key="description", label="Description", kind="text"),
                ColumnSpec(key="value", label="Value", kind="text"),
                ColumnSpec(key="filing_url", label="Filing", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="action_count", label="Actions", kind="big_number"),
                CardSlot(key="latest_action_date", label="Latest", kind="timestamp"),
                CardSlot(key="latest_action_type", label="Type", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "CACT queries SEC EDGAR for 8-K filings within the lookback window and pulls split / "
            "dividend / merger events from yfinance's actions DataFrame. Both streams are normalized "
            "into a single typed action list with deterministic (date, action_type, description, "
            "value, filing_url) shape. The pane ranks by event date descending; the action_types "
            "filter is applied server-side. Empty windows yield status=ok with an empty actions array "
            "(not provider_unavailable)."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "actions": FieldDef(description="Normalized list of typed corporate actions.", source="provider"),
            "action_count": FieldDef(description="Total actions in the lookback window.", source="computed"),
            "filing_url": FieldDef(description="Direct link to the source 8-K filing on SEC EDGAR.", source="sec_edgar"),
            "action_type": FieldDef(description="split | dividend | merger | name_change | 8-K.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="cact_aapl_returns_action_history",
                description="CACT for AAPL returns at least one action (AAPL has had splits + dividends).",
                inputs={"symbol": "AAPL", "months": 24},
                assertions=[
                    "status_in_ok_set",
                    "actions_non_empty",
                    "action_types_in_known_set",
                ],
            ),
            SemanticTest(
                name="cact_action_type_filter_applies",
                description="Filtering to action_types=['split'] returns only split rows.",
                inputs={"symbol": "AAPL", "action_types": ["split"]},
                assertions=["all_actions_have_action_type_split"],
            ),
            SemanticTest(
                name="cact_provider_outage_returns_unavailable",
                description="When both SEC and yfinance fail the response is provider_unavailable, not a fake action.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "actions_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["cact"]
