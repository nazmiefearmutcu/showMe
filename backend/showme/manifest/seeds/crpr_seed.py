"""CRPR — Credit Rating Profile (agency rating snapshot).

Displays the agency rating record for an issuer (S&P, Moody's, Fitch)
with outlook, watch state, rating date, and rationale per row. Without a
paid ratings feed the engine ships a public/default sovereign profile
explicitly labelled ``manual_or_public_defaults`` so the row source is
never mistaken for a live agency feed.
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
def crpr() -> FunctionManifest:
    return FunctionManifest(
        code="CRPR",
        name="Credit Rating Profile",
        category=Category.BONDS_RATES,
        intent=(
            "Show the per-agency credit rating snapshot (S&P / Moody's / Fitch)"
            " for an issuer with outlook, watch state, and rationale so a desk"
            " can read credit headlines next to portfolio holdings."
        ),
        asset_classes=[AssetClass.BOND, AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="issuer",
                label="Issuer",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Issuer name or symbol whose rating record is fetched.",
            ),
            InputSpec(
                name="rating",
                label="Rating override",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description=(
                    "Optional dict of {sp, moodys, fitch, outlook, watch}"
                    " used when the operator wants to pin specific agency ratings"
                    " rather than the bundled public/default profile."
                ),
            ),
            InputSpec(
                name="bucket",
                label="Implied bucket",
                control=ControlKind.SELECT,
                required=False,
                description="Coarse credit bucket label surfaced in the summary.",
                options=["high_grade", "investment_grade", "crossover", "high_yield", "distressed"],
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
            "bucket": "high_grade",
            "provider_mode": DataMode.MODELED.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["rows", "summary", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="agency", label="Agency", kind="text", width_hint=110),
                ColumnSpec(key="rating", label="Rating", kind="tag", width_hint=90),
                ColumnSpec(key="outlook", label="Outlook", kind="tag", width_hint=90),
                ColumnSpec(key="watch", label="Watch", kind="tag", width_hint=80),
                ColumnSpec(key="rating_date", label="Rating date", kind="date"),
                ColumnSpec(key="rationale", label="Rationale", kind="text"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="issuer", label="Issuer", kind="kpi"),
                CardSlot(key="implied_bucket", label="Bucket", kind="badge"),
                CardSlot(key="agencies", label="Agencies", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "CRPR returns one row per rating agency (S&P / Moody's / Fitch) with the visible rating,"
            " outlook, watch state, rating date, and a rationale string. When the caller pins a"
            " ``rating`` dict the engine echoes it verbatim and marks ``source_mode=user_input``."
            " Without an explicit override the engine returns a bundled public/default sovereign"
            " profile marked ``source_mode=manual_or_public_defaults`` with a warning explaining the"
            " row is not from a paid live agency feed. The agency scale ladder (AAA → CCC) is"
            " surfaced in the response so the renderer can plot the bucket next to the row."
        ),
        formula_dict={},
        field_dict={
            "rows[].agency": FieldDef(description="Rating agency (S&P / Moody's / Fitch).", source="catalog"),
            "rows[].rating": FieldDef(description="Agency long-term credit rating.", source="user_or_default"),
            "rows[].outlook": FieldDef(description="Stable / positive / negative outlook when available.", source="user_or_default"),
            "rows[].watch": FieldDef(description="Watchlist state when available.", source="user_or_default"),
            "rows[].rating_date": FieldDef(unit="date", description="Date attached to the visible rating snapshot.", source="user_or_default"),
            "rows[].rationale": FieldDef(description="Why this row is shown and whether it is fallback data.", source="adapter"),
            "summary.implied_bucket": FieldDef(description="Coarse credit bucket label inferred from the rating set.", source="adapter"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="crpr_default_response_is_labelled",
                description=(
                    "Without a user-supplied rating the response is marked"
                    " source_mode=manual_or_public_defaults and includes a warning that the row is"
                    " not from a paid live agency feed."
                ),
                inputs={"issuer": "US Treasury"},
                assertions=[
                    "source_mode_equals_manual_or_public_defaults",
                    "warning_mentions_public_defaults_or_no_live_feed",
                ],
            ),
            SemanticTest(
                name="crpr_user_supplied_rating_passes_through",
                description="With ``rating`` supplied, rows echo the override and source_mode=user_input.",
                inputs={"issuer": "GENERIC", "rating": {"sp": "BB", "moodys": "Ba2", "fitch": "BB", "outlook": "negative"}},
                assertions=[
                    "source_mode_equals_user_input",
                    "row_for_sp_rating_equals_BB",
                ],
            ),
            SemanticTest(
                name="crpr_emits_three_agency_rows",
                description="Every response carries exactly three rows (S&P, Moody's, Fitch) so the table layout stays stable.",
                inputs={"issuer": "US Treasury"},
                assertions=["rows_length_equals_3"],
            ),
            SemanticTest(
                name="crpr_scale_ladder_present",
                description="Response includes the AAA→CCC scale ladder so the renderer can highlight the bucket position.",
                inputs={},
                assertions=["scale_ladder_present_and_descending"],
            ),
        ],
    )


__all__ = ["crpr"]
