"""CRPR — Credit Rating Profile (model-implied credit profile).

For a corporate issuer the engine derives a MODEL-IMPLIED rating bucket from
SEC EDGAR companyfacts (leverage and interest coverage) and emits one
``model_implied`` row. It is not a paid S&P / Moody's / Fitch rating. Sovereign
issuers get an empty payload. A pinned ``rating`` override is echoed as three
agency rows with ``source_mode=user_input``.
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
            "Show a model-implied credit profile for a corporate issuer, built from SEC"
            " financials (leverage and interest coverage), with its rationale so a desk"
            " can read a transparent credit bucket next to portfolio holdings. Not an"
            " agency rating."
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
            "For a corporate issuer CRPR derives a MODEL-IMPLIED credit profile from the latest SEC"
            " EDGAR companyfacts (XBRL): gross debt = LongTermDebt (+ current) + ShortTermBorrowings;"
            " EBITDA proxy = OperatingIncomeLoss + DepreciationDepletionAndAmortization; interest"
            " coverage = EBITDA / InterestExpense. Leverage and coverage map to a coarse, transparent"
            " bucket (AA to CCC). It emits one row with agency=model_implied and"
            " source_mode=model_implied_from_financials. It is not a paid S&P / Moody's / Fitch"
            " rating, and a warning says so. A pinned ``rating`` dict is echoed verbatim as three"
            " agency rows with source_mode=user_input. A sovereign issuer (no SEC CIK) gets"
            " status=empty and no rating row, because no keyless sovereign rating feed is wired."
            " The agency scale ladder (AAA to CCC) is returned so the renderer can plot the bucket."
        ),
        formula_dict={},
        field_dict={
            "rows[].agency": FieldDef(description="Row source: model_implied, or the pinned override label.", source="adapter"),
            "rows[].rating": FieldDef(description="Model-implied rating bucket, or the pinned override rating.", source="derived from SEC financials or user_input"),
            "rows[].outlook": FieldDef(description="Stable / positive / negative, derived with the bucket or pinned.", source="derived from SEC financials or user_input"),
            "rows[].watch": FieldDef(description="Watchlist state; 'none' unless pinned.", source="user_input or default"),
            "rows[].rating_date": FieldDef(unit="date", description="As-of date of the underlying SEC financials or the override.", source="SEC EDGAR or user_input"),
            "rows[].rationale": FieldDef(description="Leverage and coverage inputs, or the override note.", source="adapter"),
            "summary.implied_bucket": FieldDef(description="Coarse credit bucket label inferred from leverage and coverage.", source="adapter"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="crpr_corporate_emits_one_model_implied_row",
                description=(
                    "A corporate issuer with SEC companyfacts returns exactly one row with"
                    " agency=model_implied and source_mode=model_implied_from_financials, plus a"
                    " warning that the rating is not a paid agency rating."
                ),
                inputs={"issuer": "AAPL"},
                assertions=[
                    "rows_length_equals_1",
                    "agency_equals_model_implied",
                    "source_mode_equals_model_implied_from_financials",
                    "warning_mentions_model_implied_not_agency",
                ],
            ),
            SemanticTest(
                name="crpr_sovereign_returns_no_rating_row",
                description=(
                    "A sovereign issuer with no SEC CIK returns status=empty, no rating row and a"
                    " reason, and never a constant rating."
                ),
                inputs={"issuer": "US Treasury"},
                assertions=[
                    "status_equals_empty",
                    "rows_empty",
                    "reason_present",
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
                name="crpr_override_emits_three_agency_rows",
                description="A pinned rating override carries exactly three rows (S&P, Moody's, Fitch).",
                inputs={"issuer": "GENERIC", "rating": {"sp": "BB", "moodys": "Ba2", "fitch": "BB", "outlook": "negative"}},
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
