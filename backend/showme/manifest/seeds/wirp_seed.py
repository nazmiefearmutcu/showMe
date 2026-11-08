"""WIRP — World Interest Rate Probabilities (Cut/Hold/Hike).

Describes what the shipped handler does: Fed cut/hold/hike odds come only from
the CME FedWatch adapter when it is wired. Without it the keyless path reports
FRED target-range, EFFR and 13-week T-bill anchors and no hike/cut odds, with
``provider_unavailable``. ECB and BoE are reported as ``provider_unavailable``.
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
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def wirp() -> FunctionManifest:
    return FunctionManifest(
        code="WIRP",
        name="World Interest Rate Probabilities",
        category=Category.MACRO,
        intent=(
            "For the Fed, show the market-implied cut / hold / hike probabilities of the "
            "next policy meetings with the expected move vs the current target anchor. "
            "Probabilities are shown only when a real market-implied source is wired; "
            "otherwise the FRED target range and rate references are shown with no odds."
        ),
        asset_classes=[AssetClass.RATE, AssetClass.BOND, AssetClass.FX],
        inputs=[
            InputSpec(
                name="central_bank",
                label="Central bank",
                control=ControlKind.SELECT,
                required=False,
                description=(
                    "Central bank to show. Only FED has live market-implied probabilities; "
                    "ECB and BOE report provider_unavailable."
                ),
                options=["FED", "ECB", "BOE"],
            ),
            InputSpec(
                name="meetings",
                label="Meetings",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum number of forward meetings to return (1-8).",
            ),
        ],
        defaults={
            "central_bank": "FED",
            "meetings": 4,
        },
        provider_chain=ProviderChain(
            primary="cme_fedwatch",
            fallbacks=["fred"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=300,
            scope="per_input",
            persist=True,
        ),
        output_contract=OutputContract(
            must_have=["status", "rows", "anchor", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        chart_grammar=None,
        table_schema=None,
        card_schema=CardSchema(
            slots=[
                CardSlot(key="central_bank", label="Central bank", kind="badge"),
                CardSlot(key="meetings", label="Meetings", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="target_mid", label="Target mid", kind="big_number", unit="%"),
                CardSlot(key="tbill_13w", label="13w T-bill", kind="kpi", unit="%"),
            ],
        ),
        methodology=(
            "Fed probabilities come only from the CME FedWatch adapter when it is wired. For each "
            "meeting the adapter's target-range distribution is bucketed against the anchor (the "
            "modal range of the first meeting): ranges below the anchor count as cut_25bp, the "
            "anchor range as hold, and ranges above as hike_25bp, renormalised so that cut + hold "
            "+ hike = 1. implied_change_bp = -25 x cut_25bp + 25 x hike_25bp is the expected move "
            "vs the anchor at that meeting, cumulative to that date, so it is not summed across "
            "meetings. Without the adapter the keyless path reports only reference anchors (FRED "
            "DFEDTARU / DFEDTARL target range, EFFR from DFF, and the 13-week T-bill from ^IRX) and "
            "no hike/cut odds, with status provider_unavailable, zero rows and a warning. ECB and BoE "
            "have no keyless market-implied source and report provider_unavailable. The meetings "
            "input limits how many returned rows are shown; it does not change any probability."
        ),
        formula_dict={
            "expected_move": Formula(
                expression=r"\Delta_{bps} = 25 \times (P_{hike} - P_{cut})",
                variables={
                    "P_hike": "Probability of a 25 bp (or deeper) hike vs the anchor at the meeting",
                    "P_cut": "Probability of a 25 bp (or deeper) cut vs the anchor at the meeting",
                },
                notes="Expected move vs the anchor at each meeting, cumulative to that date.",
            ),
        },
        field_dict={
            "rows[].date": FieldDef(unit="UTC", description="Forward policy-meeting decision date.", source="CME FedWatch"),
            "rows[].cut_25bp": FieldDef(unit="[0,1]", description="Probability of a cut vs the anchor.", source="derived from CME FedWatch"),
            "rows[].hold": FieldDef(unit="[0,1]", description="Probability of no change vs the anchor.", source="derived from CME FedWatch"),
            "rows[].hike_25bp": FieldDef(unit="[0,1]", description="Probability of a hike vs the anchor.", source="derived from CME FedWatch"),
            "rows[].implied_change_bp": FieldDef(
                unit="bp",
                description="Expected move vs the anchor at that meeting, cumulative to that date.",
                source="derived from CME FedWatch",
            ),
            "anchor.current_target_lower": FieldDef(unit="%", description="FRED DFEDTARL target lower bound.", source="FRED"),
            "anchor.current_target_upper": FieldDef(unit="%", description="FRED DFEDTARU target upper bound.", source="FRED"),
            "anchor.current_target_mid": FieldDef(unit="%", description="Midpoint of the FRED target range.", source="FRED"),
            "anchor.effr": FieldDef(unit="%", description="Effective fed funds rate (reference only).", source="FRED DFF"),
            "anchor.tbill_13w_pct": FieldDef(unit="%", description="13-week T-bill yield (basis, not a policy-rate expectation).", source="yfinance ^IRX"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="wirp_probs_sum_to_one",
                description=(
                    "For every row returned from the CME FedWatch adapter, assert "
                    "cut_25bp + hold + hike_25bp ≈ 1.0 within 1e-6."
                ),
                inputs={"_mock": "cme_fedwatch_three_meetings"},
                assertions=[
                    "for_every_row_cut_plus_hold_plus_hike_within_1e-6_of_1",
                ],
            ),
            SemanticTest(
                name="wirp_keyless_path_reports_no_odds",
                description=(
                    "Without the CME adapter, FRED and ^IRX answer. Assert status "
                    "provider_unavailable, rows empty, and no hike/cut odds derived from the "
                    "T-bill or EFFR."
                ),
                inputs={"_mock": "fred_and_irx_up_no_adapter"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "rows_empty",
                    "no_hike_cut_odds_from_tbill_or_effr",
                ],
            ),
            SemanticTest(
                name="wirp_non_fed_is_provider_unavailable",
                description="ECB and BOE have no market-implied source. Assert provider_unavailable and no rows.",
                inputs={"central_bank": "ECB"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "rows_empty",
                ],
            ),
        ],
    )


__all__ = ["wirp"]
