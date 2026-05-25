"""DPF — Delisted / Private Firms reference data.

Surface delisted, private, or otherwise unlisted-but-once-listed companies.
Backed by yfinance (delisting flag + last-traded date) with SEC EDGAR
fallback for the final 10-K / Form 25 filing that documented the delisting.
The pane is a profile + chronological table; no time-series chart.
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
def dpf() -> FunctionManifest:
    return FunctionManifest(
        code="DPF",
        name="Delisted / Private Firms",
        category=Category.EQUITIES,
        intent=(
            "Surface delisted or private-firm reference data: last-traded date, delisting reason, "
            "post-delisting status, and the Form 25 / final 10-K pointer when available."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Historical or current equity ticker.",
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
        defaults={"provider_mode": DataMode.DELAYED_REFERENCE.value},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["sec_edgar", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=86400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "is_delisted", "rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="event_date", label="Date", kind="date"),
                ColumnSpec(key="event", label="Event", kind="tag"),
                ColumnSpec(key="description", label="Description", kind="text"),
                ColumnSpec(key="filing_url", label="Filing", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="is_delisted", label="Delisted", kind="badge"),
                CardSlot(key="delisting_date", label="Delisting date", kind="timestamp"),
                CardSlot(key="delisting_reason", label="Reason", kind="badge"),
                CardSlot(key="successor", label="Successor", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DPF queries yfinance for the symbol's status (delisted / private / current) and "
            "joins it with SEC EDGAR for the Form 25 (delisting), final 10-K, and any "
            "post-delisting filings. The event table is chronological. For tickers that are "
            "still actively trading, status=ok with is_delisted=false and a single row stating "
            "the listing is current. For symbols neither EDGAR nor yfinance recognise, the "
            "response is provider_unavailable rather than a fake delisting record."
        ),
        field_dict={
            "symbol": FieldDef(description="Historical or current equity ticker.", source="instrument"),
            "is_delisted": FieldDef(description="True when the equity is no longer trading.", source="provider"),
            "delisting_date": FieldDef(description="ISO date of delisting.", source="sec_edgar"),
            "delisting_reason": FieldDef(description="Merger / bankruptcy / privatization / regulatory.", source="sec_edgar"),
            "successor": FieldDef(description="Successor entity ticker, when applicable.", source="provider"),
            "rows": FieldDef(description="Chronological event list (delisting, 10-K, Form 25 ...).", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="dpf_known_delisted_returns_delisting_date",
                description="DPF for a known delisted ticker exposes delisting_date + reason.",
                inputs={"symbol": "LEH"},
                assertions=[
                    "is_delisted_is_true",
                    "delisting_date_non_empty",
                ],
            ),
            SemanticTest(
                name="dpf_active_ticker_returns_is_delisted_false",
                description="DPF for AAPL (still active) returns is_delisted=False with a single 'listing current' row.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_ok_set",
                    "is_delisted_is_false",
                ],
            ),
            SemanticTest(
                name="dpf_unknown_ticker_does_not_fabricate_delisting",
                description="When neither EDGAR nor yfinance recognise the symbol, status=provider_unavailable.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "no_synthetic_delisting_date",
                ],
            ),
        ],
    )


__all__ = ["dpf"]
