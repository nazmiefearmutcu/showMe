"""WIRP — World Interest Rate Probabilities (Cut/Hold/Hike).

Encodes the wave1 WIRP spec verbatim: for each major central bank, the
market-implied probability distribution of the next rate decision plus
the path-implied terminal rate over the next 4 meetings, with formula
and inputs visible so an analyst can sanity-check or disagree.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    PaneGrammar,
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
            "For each major central bank, show the market-implied probability "
            "distribution of the next rate decision (cut/hold/hike) and the "
            "path-implied terminal rate over the next 4 meetings — with the "
            "formula and inputs visible so an analyst can sanity-check or disagree."
        ),
        asset_classes=[AssetClass.RATE, AssetClass.BOND, AssetClass.FX],
        inputs=[
            InputSpec(
                name="central_banks",
                label="Central banks",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Which central banks to show in the matrix.",
                options=["Fed", "ECB", "BoE", "BoJ", "SNB", "BoC", "RBA"],
            ),
            InputSpec(
                name="meeting_horizon",
                label="Horizon",
                control=ControlKind.SELECT,
                required=True,
                description="How many forward meetings to render per bank.",
                options=["next_1", "next_2", "next_4", "next_6", "full_curve"],
            ),
            InputSpec(
                name="source",
                label="Source",
                control=ControlKind.SELECT,
                required=True,
                description="Probability inference source.",
                options=["sofr_futures", "ois", "stir_futures", "modeled"],
            ),
            InputSpec(
                name="as_of",
                label="As of",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Anchor date for the implied curve (defaults to last close).",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; the chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "central_banks": ["Fed", "ECB", "BoE", "BoJ", "SNB", "BoC", "RBA"],
            "meeting_horizon": "next_4",
            "source": "sofr_futures",
            "as_of": "last_close",
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["cached_snapshot", "modeled"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.MODELED,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=300,
            scope="per_input",
            persist=True,
        ),
        output_contract=OutputContract(
            must_have=["as_of", "banks", "data_mode"],
            rows=False,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="category", label="Meeting"),
            y_axis=[
                AxisSpec(type="numeric", unit="%", label="Probability"),
                AxisSpec(type="numeric", unit="%", label="Implied policy rate"),
            ],
            panes=[
                PaneGrammar(name="stacked_probs", series_kind="bar", height_pct=60),
                PaneGrammar(name="implied_path", series_kind="line", height_pct=40),
            ],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=None,
        card_schema=CardSchema(
            slots=[
                CardSlot(key="current_rate", label="Current Rate", kind="big_number", unit="%"),
                CardSlot(key="next_meeting_date", label="Next Meeting", kind="timestamp"),
                CardSlot(key="p_cut", label="P(Cut)", kind="kpi", unit="%"),
                CardSlot(key="p_hold", label="P(Hold)", kind="kpi", unit="%"),
                CardSlot(key="p_hike", label="P(Hike)", kind="kpi", unit="%"),
                CardSlot(key="expected_move_bps", label="Expected Δ", kind="trend_pill", unit="bps"),
                CardSlot(key="terminal_rate", label="Terminal (4 mtg)", kind="big_number", unit="%"),
            ],
        ),
        methodology=(
            "For each central bank: (1) get the current policy rate from FRED (Fed Funds for US, "
            "etc.) and the dated forward meeting schedule from a curated central_bank_calendar.yml "
            "(committed in repo, manually maintained ~quarterly). (2) From the futures-implied "
            "curve at as_of, compute the implied policy rate at each forward meeting — for Fed, "
            "the average daily SOFR over the meeting period implied by the corresponding SOFR "
            "future; for other banks, the corresponding OIS / STIR futures. (3) Compute the "
            "implied change vs current rate at each meeting → expected_move_bps. (4) Probabilities: "
            "discretize the implied move into 25 bps buckets centered on integer multiples "
            "(standard market convention). For a meeting where the implied move is m bps, with "
            "assumed std σ of the implied path (default 5 bps, configurable in advanced): "
            "P(hike of n×25 bps) = Φ((n + 0.5)/σ ratio) − Φ((n − 0.5)/σ ratio); Cut = sum of "
            "negative-n probabilities; hold = P(|m| < 12.5); hike = sum of positive-n. (5) Terminal "
            "rate at 4 meetings out is taken directly from the implied curve. If primary source is "
            "unavailable, the system falls back to a published 'modeled' path (e.g. last-good curve "
            "+ small drift) and marks data_mode = 'modeled' with a prominent warning."
        ),
        formula_dict={
            "implied_policy_rate_fed": Formula(
                expression=r"r_{implied} = 100 - P_{future} + adjustment_{avg vs eom}",
                variables={
                    "P_future": "SOFR future price",
                    "r_implied": "Implied policy rate (%)",
                },
                notes="Implied from the SOFR future price (Fed).",
            ),
            "expected_move": Formula(
                expression=r"\Delta_{bps} = (r_{implied} - r_{current}) \times 100",
                variables={
                    "r_implied": "Implied policy rate at meeting (%)",
                    "r_current": "Current policy rate (%)",
                },
                notes="Expected move in basis points.",
            ),
            "bucket_probability": Formula(
                expression=r"P(n) = \Phi((n + 0.5)/\sigma) - \Phi((n - 0.5)/\sigma)",
                variables={
                    "n": "Bucket index (integer multiples of 25 bps)",
                    "sigma": "Std of implied path (default 5 bps)",
                    "Phi": "Standard normal CDF",
                },
                notes="Normal CDF on quantized move buckets at 25 bps spacing.",
            ),
            "cut_hold_hike": Formula(
                expression=r"P_{cut} = \sum_{n<0} P(n); P_{hold} = P(|m| < 12.5); P_{hike} = \sum_{n>0} P(n)",
                variables={
                    "P(n)": "Bucket probability at index n",
                    "m": "Implied move in bps",
                },
                notes="Sum of bucket probabilities by sign.",
            ),
        },
        field_dict={
            "banks[].name": FieldDef(description="Display name (e.g. 'Federal Reserve').", source="calendar"),
            "banks[].code": FieldDef(description="Short code (Fed/ECB/BoE/...).", source="calendar"),
            "banks[].current_rate": FieldDef(unit="%", description="Current policy rate.", source="FRED / official"),
            "banks[].next_meeting_date": FieldDef(unit="UTC", description="Scheduled date.", source="calendar"),
            "banks[].implied_path[].meeting_date": FieldDef(
                unit="UTC",
                description="Forward meeting date.",
                source="calendar + futures",
            ),
            "banks[].implied_path[].implied_rate": FieldDef(
                unit="%",
                description="Implied policy rate at meeting.",
                source="futures",
            ),
            "banks[].implied_path[].p_cut": FieldDef(unit="[0,1]", description="Probability of cut.", source="derived"),
            "banks[].implied_path[].p_hold": FieldDef(unit="[0,1]", description="Probability of hold.", source="derived"),
            "banks[].implied_path[].p_hike": FieldDef(unit="[0,1]", description="Probability of hike.", source="derived"),
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
                    "For every meeting in every bank's implied_path, assert "
                    "p_cut + p_hold + p_hike ≈ 1.0 ± 1e-6."
                ),
                inputs={},
                assertions=[
                    "for_every_meeting_p_cut_plus_p_hold_plus_p_hike_within_1e-6_of_1",
                ],
            ),
            SemanticTest(
                name="wirp_current_rate_from_fred_for_fed",
                description="Mock FRED returning current Fed Funds rate. Assert banks[Fed].current_rate matches.",
                inputs={"_mock": "fred_fed_funds_rate"},
                assertions=["banks_fed_current_rate_matches_fred_mock"],
            ),
            SemanticTest(
                name="wirp_modeled_mode_warns_explicitly",
                description=(
                    "Mock SOFR futures provider down. Assert data_mode == 'modeled', warning "
                    "present mentioning 'live futures unavailable'."
                ),
                inputs={"_mock": "sofr_futures_down"},
                assertions=[
                    "data_mode_equals_modeled",
                    "warning_mentions_live_futures_unavailable",
                ],
            ),
            SemanticTest(
                name="wirp_no_provider_returns_unavailable_not_synthetic",
                description=(
                    "Mock all providers down. Assert data_mode == 'provider_unavailable', NO "
                    "synthetic probabilities. Banks array may still have name, code, "
                    "current_rate from cache but implied_path == []."
                ),
                inputs={"_mock": "all_providers_down"},
                assertions=[
                    "data_mode_equals_provider_unavailable",
                    "no_synthetic_probabilities",
                    "implied_path_empty_when_unavailable",
                ],
            ),
            SemanticTest(
                name="wirp_implied_path_monotonic_in_time",
                description="Assert implied_path is sorted ascending by meeting_date.",
                inputs={},
                assertions=["implied_path_sorted_ascending_by_meeting_date"],
            ),
            SemanticTest(
                name="wirp_terminal_rate_matches_4th_implied",
                description=(
                    "Assert reported terminal_rate equals implied_path[3].implied_rate "
                    "(or last entry if horizon < next_4)."
                ),
                inputs={"meeting_horizon": "next_4"},
                assertions=["terminal_rate_equals_implied_path_index_3_or_last"],
            ),
        ],
    )


__all__ = ["wirp"]
