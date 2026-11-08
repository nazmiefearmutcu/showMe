"""GMM — Global Macro Movers (Global Macro Matrix).

Cross-country macro-stress matrix from the keyless World Bank open-data API:
one row per economy with real GDP growth, CPI inflation, unemployment and
central-government debt/GDP, each cell carrying its own observation year, and
a composite stress score ranked so the hottest economies surface first.
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
    ColumnSpec,
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    PaneGrammar,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def gmm() -> FunctionManifest:
    return FunctionManifest(
        code="GMM",
        name="Global Macro Movers",
        category=Category.MACRO,
        intent=(
            "Cross-country macro-stress matrix from World Bank annual indicators — GDP growth, "
            "CPI inflation, unemployment and debt/GDP per economy, ranked by a composite stress "
            "score so the economies running hottest surface first. Each cell shows its own "
            "observation year because the series are lagged."
        ),
        asset_classes=[
            AssetClass.RATE,
            AssetClass.FX,
            AssetClass.EQUITY,
            AssetClass.COMMODITY,
            AssetClass.BOND,
        ],
        inputs=[
            # HNT-10 (2026-09-23 bug hunt): the handler reads only countries and
            # top_n. The former provider_mode input (and the window/categories
            # inputs before it) were never read, so they are not offered here.
            InputSpec(
                name="countries",
                label="Countries",
                control=ControlKind.MULTISELECT,
                required=False,
                description=(
                    "ISO 3166-1 alpha-2 codes; EZ = euro area and EU = European Union aggregates. "
                    "Empty = the major-economy set."
                ),
                options=[
                    "US", "CN", "JP", "DE", "GB", "FR", "IN", "BR", "CA", "IT",
                    "KR", "AU", "MX", "TR", "CH", "EZ", "EU",
                ],
            ),
            InputSpec(
                name="top_n",
                label="Top N",
                control=ControlKind.NUMBER,
                required=False,
                description="How many economies to show (5..50). Empty = all rows.",
                min=5,
                max=50,
                step=5,
            ),
        ],
        defaults={
            "countries": [],
        },
        provider_chain=ProviderChain(
            primary="worldbank",
            fallbacks=[],
            acceptable_modes=[DataMode.LIVE_OFFICIAL],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["rows", "cards", "methodology"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="score", label="Composite macro-stress score"),
            y_axis=AxisSpec(type="category", label="Economy"),
            panes=[
                PaneGrammar(name="stress_ladder", series_kind="bar", height_pct=100),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="country", label="Country", kind="text"),
                ColumnSpec(key="country_code", label="Code", kind="tag"),
                ColumnSpec(key="gdp_growth", label="GDP g/y", kind="number", format="%.1f", unit="%"),
                ColumnSpec(key="inflation", label="CPI", kind="number", format="%.1f", unit="%"),
                ColumnSpec(key="unemployment", label="Unemp.", kind="number", format="%.1f", unit="%"),
                ColumnSpec(key="debt_gdp", label="Debt/GDP", kind="number", format="%.1f", unit="%"),
                ColumnSpec(key="score", label="Score", kind="number", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="economies", label="Economies", kind="kpi"),
                CardSlot(key="hottest_inflation", label="Hottest CPI", kind="kpi"),
                CardSlot(key="fastest_growth", label="Fastest GDP", kind="kpi"),
                CardSlot(key="source", label="Source", kind="badge"),
            ],
        ),
        methodology=(
            "GMM pulls the most recent non-null annual observation of four World Bank indicators "
            "per economy: real GDP growth (NY.GDP.MKTP.KD.ZG), CPI inflation (FP.CPI.TOTL.ZG), "
            "unemployment (SL.UEM.TOTL.ZS) and central-government debt/GDP (GC.DOD.TOTL.GD.ZS). "
            "The composite stress score is inflation + unemployment + 0.05 x debt/GDP - GDP growth. "
            "A row is scored only when all four indicators are present and no observation is more "
            "than five years old; otherwise the score is null and the row lists score_missing or "
            "stale_fields. Missing cells stay null and are never filled in."
        ),
        formula_dict={
            "composite_score": Formula(
                expression=r"score = \mathrm{infl} + \mathrm{unemp} + 0.05\,\mathrm{debt} - \mathrm{growth}",
                variables={
                    "infl": "CPI inflation, annual %",
                    "unemp": "Unemployment, % of labor force",
                    "debt": "Central government debt, % of GDP",
                    "growth": "Real GDP growth, annual %",
                },
                notes="Higher score = more stretched. Unitless composite of percentage indicators.",
            ),
        },
        field_dict={
            "rows[].country": FieldDef(description="Country or aggregate name.", source="reference"),
            "rows[].country_code": FieldDef(description="ISO 3166-1 alpha-2 code (EZ and EU for aggregates).", source="reference"),
            "rows[].gdp_growth": FieldDef(unit="%", description="Real GDP growth, annual %.", source="worldbank"),
            "rows[].inflation": FieldDef(unit="%", description="Headline CPI inflation, annual %.", source="worldbank"),
            "rows[].unemployment": FieldDef(unit="%", description="Unemployment, % of labor force.", source="worldbank"),
            "rows[].debt_gdp": FieldDef(unit="%", description="Central government debt, % of GDP.", source="worldbank"),
            "rows[].score": FieldDef(unit="score", description="Composite stress score; null unless all four are fresh.", source="computed"),
            "rows[].score_missing": FieldDef(description="Indicators that block the score (null or too old).", source="computed"),
            "rows[].stale_fields": FieldDef(description="Indicators older than five years; shown but not scored.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="gmm_rows_sorted_by_score_desc",
                description="Scored rows are ordered by composite score, highest first; unscored rows come last.",
                inputs={},
                assertions=["rows_sorted_by_score_desc", "unscored_rows_last"],
            ),
            SemanticTest(
                name="gmm_score_requires_all_four_components",
                description="A row with any indicator null or stale has a null score and lists it in score_missing.",
                inputs={},
                assertions=["scored_rows_have_all_components", "score_missing_matches_nulls"],
            ),
            SemanticTest(
                name="gmm_stale_observation_not_scored",
                description="An observation older than five years is shown with its year but excluded from the score and the cards.",
                inputs={},
                assertions=["stale_observations_not_scored", "stale_fields_listed"],
            ),
            SemanticTest(
                name="gmm_ez_is_euro_area",
                description="EZ resolves to the World Bank euro-area aggregate, never to Germany.",
                inputs={"countries": ["EZ"]},
                assertions=["ez_label_is_euro_area", "no_germany_row"],
            ),
            SemanticTest(
                name="gmm_top_n_caps_rows",
                description="With top_n=10, the payload holds at most 10 rows.",
                inputs={"top_n": 10},
                assertions=["rows_length_le_top_n"],
            ),
        ],
    )


__all__ = ["gmm"]
