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
                description="Restrict the ranked table to a holder subset. insider reports unavailable: no HDS provider supplies insider holder rows.",
                options=["all", "institutional", "insider", "mutual_fund"],
            ),
            InputSpec(
                name="live",
                label="Live mode",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true the handler queries Yahoo holder tables and the local SEC 13F store; otherwise no rows are returned (needs_input).",
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
                ColumnSpec(key="pct_outstanding", label="% out", kind="percent", format="%.2f"),
                ColumnSpec(key="market_value", label="Value", kind="currency", format="%.0f"),
                ColumnSpec(key="date_reported", label="Reported", kind="date"),
                ColumnSpec(key="quarter", label="Quarter", kind="date"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="holder_type_filter", label="Holder type", kind="kpi"),
                CardSlot(key="status", label="Status", kind="mode_pill"),
            ],
        ),
        methodology=(
            "HDS lists one holder source per table. The Yahoo institutional / mutual-fund holder tables "
            "(yfinance institutional_holders / mutualfund_holders) are the rows when they return any. "
            "Otherwise the rows are the issuer's per-filer aggregate from the local SEC 13F store (filer CIK, "
            "shares, report date), and the 13F aggregate is also returned as sec_13f_top when present. "
            "Each row is typed (institutional / mutual_fund / institutional_13f). pct_outstanding is Yahoo's "
            "pctHeld: the holder's shares divided by shares outstanding, as a fraction (0.08 = 8%); it is "
            "blank for 13F rows, which carry no percentage. 13F market value is not shown because the "
            "InfoTable unit is unresolved. Yahoo major-holder percentages are a summary block, not holder "
            "rows. When live=false no rows are returned (status needs_input); no synthetic or reference "
            "rows are served."
        ),
        field_dict={
            "rows": FieldDef(description="Ranked holder rows, one source per table, each with shares and holder_type.", source="provider"),
            "sec_13f_top": FieldDef(description="Local SEC 13F per-filer aggregate for the issuer (filer CIK, shares, report date), when the store holds it.", source="provider"),
            "pct_outstanding": FieldDef(unit="fraction", description="Fraction from 0 to 1: holder shares divided by shares outstanding (Yahoo pctHeld); blank for 13F rows.", source="provider"),
            "major_holders_summary": FieldDef(description="Yahoo major-holder summary block (not holder rows).", source="provider"),
            "holder_type_filter": FieldDef(description="The holder_type filter that was applied to rows.", source="input"),
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
