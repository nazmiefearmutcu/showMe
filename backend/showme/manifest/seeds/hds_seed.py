"""HDS — Holders / Institutional Holdings.

Surfaces the issuer's institutional and insider holders. Backed by SEC
EDGAR (10-Q / 10-K direct holdings tables) with yfinance institutional /
major holders DataFrames as the fast fallback. Renders KPIs (% institutional,
% insider, holder counts) plus a ranked holder table.
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
def hds() -> FunctionManifest:
    return FunctionManifest(
        code="HDS",
        name="Holders",
        category=Category.EQUITIES,
        intent=(
            "Show institutional and insider holders for an issuer: % held by institutions / "
            "insiders, holder counts, and a ranked list of top holders by shares."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity or ETF ticker.",
            ),
            InputSpec(
                name="holder_type",
                label="Holder type",
                control=ControlKind.SELECT,
                required=False,
                description="Restrict the ranked table to a holder subset.",
                options=["all", "institutional", "insider", "mutual_fund"],
            ),
            InputSpec(
                name="live",
                label="Live mode",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true the handler calls SEC + yfinance live; otherwise a model template.",
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
            "holder_type": "all",
            "live": True,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
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
        caching=CachingPolicy(ttl_seconds=21600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "holders"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="holder", label="Holder", kind="text"),
                ColumnSpec(key="holder_type", label="Type", kind="tag"),
                ColumnSpec(key="shares", label="Shares", kind="number", format="%.0f"),
                ColumnSpec(key="pct_held", label="% held", kind="percent", format="%.2f"),
                ColumnSpec(key="value", label="Value", kind="currency", format="%.0f"),
                ColumnSpec(key="as_of_filing", label="As of", kind="date"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="pct_institutional", label="% institutional", kind="big_number", unit="%"),
                CardSlot(key="pct_insider", label="% insider", kind="kpi", unit="%"),
                CardSlot(key="institutional_count", label="Inst. holders", kind="kpi"),
                CardSlot(key="float_shares", label="Float", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "HDS resolves the issuer's CIK via SEC EDGAR, fetches the most-recent 10-Q / 10-K "
            "holders tables, and joins them with yfinance institutional / major holders for "
            "broader coverage. Each holder row is typed (institutional / insider / mutual_fund) "
            "with shares + % of float + notional value. % institutional / insider are computed "
            "from float shares, not total shares outstanding, so they match the broker convention. "
            "When live=false the handler returns a template stub for offline panel rendering."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "holders": FieldDef(description="Ranked list of holders with shares + % held.", source="provider"),
            "pct_institutional": FieldDef(unit="%", description="Aggregate institutional ownership.", source="computed"),
            "pct_insider": FieldDef(unit="%", description="Aggregate insider ownership.", source="computed"),
            "institutional_count": FieldDef(description="Distinct institutional holders in the table.", source="computed"),
            "float_shares": FieldDef(description="Float-shares baseline used for % calculations.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="hds_aapl_returns_top_holders",
                description="HDS for AAPL returns at least one holder row + non-null % institutional.",
                inputs={"symbol": "AAPL", "live": True},
                assertions=[
                    "status_in_ok_set",
                    "holders_non_empty",
                    "pct_institutional_between_0_and_100",
                ],
            ),
            SemanticTest(
                name="hds_holder_type_filter_applies",
                description="holder_type=institutional returns only institutional rows.",
                inputs={"symbol": "AAPL", "holder_type": "institutional"},
                assertions=["all_holders_have_holder_type_institutional"],
            ),
            SemanticTest(
                name="hds_provider_outage_returns_unavailable",
                description="When SEC + yfinance both fail, status=provider_unavailable; no fake holders.",
                inputs={"symbol": "ZZZZZZ", "live": True},
                assertions=[
                    "status_equals_provider_unavailable",
                    "holders_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["hds"]
