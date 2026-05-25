"""HFS — Holder Search (13F reverse lookup).

For an issuer / CUSIP, list which 13F filers held the security in the most
recent quarter, ranked by notional. Backed by the duckdb-persisted SEC 13F
store (`data_sources/equity/sec_13f_adapter.py`); the ingest script must
have run for the lookup to populate.
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
def hfs() -> FunctionManifest:
    return FunctionManifest(
        code="HFS",
        name="Holder Search (13F)",
        category=Category.EQUITIES,
        intent=(
            "For an issuer ticker or CUSIP, list 13F filers holding the security in the most "
            "recent quarter ranked by notional, with share count and quarter-over-quarter delta."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Issuer ticker; resolves to CUSIP via reference data.",
            ),
            InputSpec(
                name="cusip",
                label="CUSIP",
                control=ControlKind.TEXT,
                required=False,
                description="9-character CUSIP; takes precedence over symbol.",
            ),
            InputSpec(
                name="quarter",
                label="Quarter",
                control=ControlKind.SELECT,
                required=False,
                description="Quarter end (YYYY-Q#); defaults to most-recent ingested quarter.",
            ),
            InputSpec(
                name="filer_type",
                label="Filer type",
                control=ControlKind.SELECT,
                required=False,
                description="Optional filer subset.",
                options=["all", "hedge_fund", "long_only", "pension", "sovereign"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={"filer_type": "all", "provider_mode": DataMode.DELAYED_REFERENCE.value},
        provider_chain=ProviderChain(
            primary="sec_edgar",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=86400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["status", "issuer", "quarter", "filers"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="filer", label="Filer", kind="text"),
                ColumnSpec(key="filer_type", label="Type", kind="tag"),
                ColumnSpec(key="shares", label="Shares", kind="number", format="%.0f"),
                ColumnSpec(key="value", label="Notional", kind="currency", format="%.0f"),
                ColumnSpec(key="pct_of_portfolio", label="% portfolio", kind="percent", format="%.2f"),
                ColumnSpec(key="qoq_change", label="QoQ Δ shares", kind="number", format="%.0f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="filer_count", label="Filers", kind="big_number"),
                CardSlot(key="total_notional", label="Total notional", kind="kpi", unit="quote_ccy"),
                CardSlot(key="quarter", label="Quarter", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "HFS resolves the issuer to a CUSIP, then queries the local duckdb 13F store for all "
            "filers reporting the security in the chosen (or most-recent ingested) quarter. Each "
            "row carries shares + notional + percent-of-portfolio + quarter-over-quarter share "
            "delta. The duckdb store is populated by `scripts/ingest_13f.py`; if the store is "
            "empty the response is status=provider_unavailable / mode=not_configured with a "
            "next_actions pointer telling the operator to run the ingest job."
        ),
        field_dict={
            "issuer": FieldDef(description="Resolved issuer ticker.", source="provider"),
            "cusip": FieldDef(description="9-character CUSIP used for the lookup.", source="provider"),
            "quarter": FieldDef(description="Reporting quarter (YYYY-Q#).", source="provider"),
            "filers": FieldDef(description="Per-filer holding rows.", source="sec_13f"),
            "filer_count": FieldDef(description="Distinct filers in the result.", source="computed"),
            "total_notional": FieldDef(unit="quote_ccy", description="Sum of notional across filers.", source="computed"),
            "qoq_change": FieldDef(description="Share count delta vs prior quarter (null if filer is new).", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="hfs_aapl_returns_filer_list",
                description="HFS for AAPL returns at least one filer row when the duckdb store is populated.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_ok_or_unavailable_set",
                    "filers_is_array",
                ],
            ),
            SemanticTest(
                name="hfs_filer_type_filter_applies",
                description="filer_type=hedge_fund restricts the result to hedge_fund rows.",
                inputs={"symbol": "AAPL", "filer_type": "hedge_fund"},
                assertions=["all_filers_have_filer_type_hedge_fund_when_populated"],
            ),
            SemanticTest(
                name="hfs_empty_store_returns_not_configured",
                description="When the duckdb store is empty, status=provider_unavailable / mode=not_configured with next_actions pointing at ingest_13f.py.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_in_unavailable_set",
                    "next_actions_mentions_ingest_13f",
                ],
            ),
        ],
    )


__all__ = ["hfs"]
