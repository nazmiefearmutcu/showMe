"""TAUC — Treasury Auction Calendar.

Upcoming and recently completed US Treasury auctions (Bills, Notes,
Bonds, TIPS, FRNs) pulled from TreasuryDirect when ``live_auctions=true``;
otherwise a labelled template is returned. The chart grammar is ``none``
because the deliverable is a calendar table rather than a plot.
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
def tauc() -> FunctionManifest:
    return FunctionManifest(
        code="TAUC",
        name="Treasury Auction Calendar",
        category=Category.BONDS_RATES,
        intent=(
            "Show upcoming and recently completed US Treasury auctions (Bills,"
            " Notes, Bonds, TIPS, FRNs) so a desk can plan participation, allocation,"
            " and post-auction reactions."
        ),
        asset_classes=[AssetClass.BOND],
        inputs=[
            InputSpec(
                name="action",
                label="View",
                control=ControlKind.SELECT,
                required=True,
                description="Show upcoming auctions or recently completed ones.",
                options=["upcoming", "recent"],
            ),
            InputSpec(
                name="horizon_days",
                label="Horizon",
                control=ControlKind.NUMBER,
                required=False,
                description="Days forward (upcoming) or backward (recent) to include.",
                min=1,
                max=365,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="security_type",
                label="Security type",
                control=ControlKind.SELECT,
                required=False,
                description="Filter by security class.",
                options=["", "Bill", "Note", "Bond", "TIPS", "FRN"],
            ),
            InputSpec(
                name="limit",
                label="Limit",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum rows to return.",
                min=1,
                max=500,
                step=1,
            ),
            InputSpec(
                name="live_auctions",
                label="Live TreasuryDirect",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true, pull live from TreasuryDirect; otherwise return a labelled template.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.MODELED.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "action": "upcoming",
            "horizon_days": 30,
            "security_type": "",
            "limit": 50,
            "live_auctions": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="treasury_direct",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["items", "summary", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="security_type", label="Type", kind="tag", width_hint=72),
                ColumnSpec(key="cusip", label="CUSIP", kind="text", width_hint=120),
                ColumnSpec(key="security_term", label="Term", kind="text", width_hint=84),
                ColumnSpec(key="auction_date", label="Auction date", kind="date"),
                ColumnSpec(key="issue_date", label="Issue date", kind="date"),
                ColumnSpec(key="maturity_date", label="Maturity", kind="date"),
                ColumnSpec(key="high_yield", label="High yield", kind="percent", unit="%", format="%.3f"),
                ColumnSpec(key="offering_amount", label="Offering", kind="currency", unit="USD bn", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_auctions", label="Auctions", kind="kpi"),
                CardSlot(key="total_offering_usd_bn", label="Total offering", kind="big_number", unit="USD bn"),
                CardSlot(key="next_auction_date", label="Next auction", kind="timestamp"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TAUC fetches the US Treasury auction calendar from TreasuryDirect when ``live_auctions=true``."
            " For ``action=upcoming`` the engine asks for ``horizon_days`` forward; for ``action=recent``"
            " it asks for the same window backward. The chain wraps the call with a configurable"
            " ``auction_timeout`` (default 6 s) and falls back to a labelled template on adapter timeout"
            " or unavailability so the pane never returns a blank list. With live off the response is"
            " an explicit template marked ``source_mode=treasury_auction_model``. Rows are grouped"
            " ``by_type`` in the summary so the operator can read the offering mix at a glance."
        ),
        formula_dict={},
        field_dict={
            "items[].security_type": FieldDef(description="Bill / Note / Bond / TIPS / FRN.", source="treasury_direct"),
            "items[].cusip": FieldDef(description="Auction CUSIP.", source="treasury_direct"),
            "items[].security_term": FieldDef(description="Tenor label (e.g. '10-Year').", source="treasury_direct"),
            "items[].auction_date": FieldDef(unit="date", description="Auction settlement date.", source="treasury_direct"),
            "items[].issue_date": FieldDef(unit="date", description="Date the security is issued.", source="treasury_direct"),
            "items[].maturity_date": FieldDef(unit="date", description="Stated maturity date.", source="treasury_direct"),
            "items[].high_yield": FieldDef(unit="%", description="High yield awarded (only for completed auctions).", source="treasury_direct"),
            "items[].offering_amount": FieldDef(unit="USD bn", description="Offering size in USD billions.", source="treasury_direct"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="tauc_live_routes_to_treasury_direct",
                description="With live_auctions=true the provider chain hits treasury_direct.",
                inputs={"action": "upcoming", "live_auctions": True},
                assertions=["provider_chain_used_treasury_direct"],
            ),
            SemanticTest(
                name="tauc_template_mode_is_labelled",
                description=(
                    "With live off the response carries source_mode=treasury_auction_model so the"
                    " calendar never sells template rows as live data."
                ),
                inputs={"action": "upcoming", "live_auctions": False},
                assertions=["source_mode_equals_treasury_auction_model"],
            ),
            SemanticTest(
                name="tauc_security_type_filter_isolates",
                description="security_type=Bill returns only Bill rows in the items array.",
                inputs={"security_type": "Bill"},
                assertions=["every_item_security_type_equals_bill"],
            ),
            SemanticTest(
                name="tauc_timeout_falls_back_with_warning",
                description=(
                    "Adapter timeout triggers the treasury_auction_fallback path with a warning that"
                    " includes the upstream error class — the pane never returns an empty list silently."
                ),
                inputs={"action": "upcoming", "live_auctions": True, "_mock": "treasury_direct_timeout"},
                assertions=[
                    "source_mode_equals_treasury_auction_fallback",
                    "warning_present_with_provider_error",
                ],
            ),
        ],
    )


__all__ = ["tauc"]
