"""BQL — ShowMe Query Language editor.

Bloomberg-BQL-inspired DSL editor for ad-hoc field queries. Primary mode
is the templated computed_model surface (local parse + provider-shaped
rows from the BQL templates); live mode requires yfinance and may report
not_configured if the live adapter is absent.
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
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def bql() -> FunctionManifest:
    return FunctionManifest(
        code="BQL",
        name="ShowMe Query Language",
        category=Category.API_DEV,
        intent=(
            "Run BQL-style queries like get(close, volume) for(['AAPL','MSFT']) by(date) against the "
            "local field templates or, when live mode is armed, the yfinance market-data adapter."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="query",
                label="Query",
                control=ControlKind.TEXT,
                required=True,
                description=(
                    "BQL-style DSL: get(field, ...) for([symbol, ...]) by(date) "
                    "[start=YYYY-MM-DD end=YYYY-MM-DD interval=1d]."
                ),
            ),
            InputSpec(
                name="live_query",
                label="Live mode",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "False (default) returns templated rows from the local field model; "
                    "True attempts a live yfinance fetch and reports not_configured if absent."
                ),
            ),
            InputSpec(
                name="limit",
                label="Row limit",
                control=ControlKind.NUMBER,
                required=False,
                description="Cap on rows returned.",
                min=1.0,
                max=10000.0,
                step=50.0,
            ),
            InputSpec(
                name="start",
                label="Start date",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Optional start date for time-axis queries.",
            ),
            InputSpec(
                name="end",
                label="End date",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Optional end date for time-axis queries.",
            ),
            InputSpec(
                name="interval",
                label="Interval",
                control=ControlKind.SELECT,
                required=False,
                description="Bar interval for the by(date) axis when live_query=True.",
                options=["1d", "1wk", "1mo"],
            ),
        ],
        defaults={
            "query": "get(close, volume) for(['AAPL']) by(date)",
            "live_query": False,
            "limit": 200,
            "interval": "1d",
        },
        # Editor-style surface — primary is internal (templated model). Live
        # mode falls through to yfinance when armed, and degrades to
        # not_configured rather than silently returning synthetic rows.
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=10, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["query", "mode", "rows", "field_dictionary"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="date", label="Date", kind="date"),
                ColumnSpec(key="close", label="Close", kind="currency", unit="quote", format="%.4f"),
                ColumnSpec(key="volume", label="Volume", kind="number", format="%.0f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbols", label="Symbols", kind="kpi"),
                CardSlot(key="fields", label="Fields", kind="kpi"),
                CardSlot(key="row_count", label="Rows", kind="kpi"),
                CardSlot(key="mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BQL parses the user's get(...) for([...]) by(...) DSL into a structured query record "
            "(universe + fields + axis + runtime params). When live_query=False (default), it returns "
            "templated rows generated from a local provider-shaped model so the editor surfaces a "
            "consistent shape for FLDS-listed fields without requiring network. When live_query=True, "
            "BQL invokes the yfinance adapter for the universe with interval/start/end, returning rows "
            "with mode='live'; if the adapter is unavailable, BQL returns status=provider_unavailable "
            "with rows=[] and mode='unavailable' rather than synthesising. Cross-reference with FLDS "
            "for the available field catalog."
        ),
        formula_dict={
            "DSL": Formula(
                expression=r"\text{get}(field, ...) \text{ for}([sym, ...]) \text{ by}(axis)",
                variables={"field": "FLDS-listed field name", "sym": "Instrument identifier", "axis": "date or symbol"},
                notes="Visible DSL accepted by the BQL parser.",
            ),
        },
        field_dict={
            "query": FieldDef(description="Echo of the DSL string sent to the parser.", source="bql"),
            "mode": FieldDef(description="computed_model / live / unavailable.", source="bql"),
            "rows[].symbol": FieldDef(description="Instrument symbol from the for([...]) clause.", source="bql"),
            "rows[].date": FieldDef(description="Provider timestamp for the OHLCV row.", source="provider"),
            "rows[].close": FieldDef(unit="quote", description="Closing/last price.", source="provider"),
            "rows[].volume": FieldDef(unit="shares_or_base", description="Session volume.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[],
            delivery=["log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="bql_template_mode_returns_rows_without_network",
                description="Default live_query=False returns templated rows with mode='computed_model'.",
                inputs={"query": "get(close, volume) for(['AAPL']) by(date)"},
                assertions=[
                    "mode == 'computed_model'",
                    "rows_length_at_least_1",
                ],
            ),
            SemanticTest(
                name="bql_live_mode_without_yfinance_returns_unavailable",
                description="live_query=True with no yfinance adapter returns status=provider_unavailable and rows=[].",
                inputs={"query": "get(close) for(['AAPL']) by(date)", "live_query": True},
                assertions=[
                    "status == 'provider_unavailable'",
                    "rows == []",
                    "mode == 'unavailable'",
                ],
            ),
            SemanticTest(
                name="bql_parser_defaults_fields_when_omitted",
                description="A query missing fields defaults to [close, volume] rather than failing.",
                inputs={"query": "for(['AAPL']) by(date)"},
                assertions=[
                    "rows_contain_close_field",
                    "rows_contain_volume_field",
                ],
            ),
            SemanticTest(
                name="bql_respects_row_limit",
                description="limit=10 caps rows at 10 even when the universe would produce more.",
                inputs={"query": "get(close) for(['AAPL']) by(date)", "limit": 10},
                assertions=["rows_length_at_most_10"],
            ),
        ],
    )


__all__ = ["bql"]
