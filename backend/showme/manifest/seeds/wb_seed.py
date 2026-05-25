"""WB — World Bonds (sovereign 10Y yield grid).

Bloomberg ``WB<GO>`` analogue: a country × 10Y yield grid with a
developed-market / emerging-market tab split, heatmap rank against the
visible distribution, spread vs US Treasury 10Y, and a 30 s poll on the
FRED-backed live path. The sovereign_yield_model fallback ships labelled
template rows so the pane never silently fakes a live read.
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
    AlertingSpec,
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
def wb() -> FunctionManifest:
    return FunctionManifest(
        code="WB",
        name="World Bonds",
        category=Category.BONDS_RATES,
        intent=(
            "Show 10-year sovereign yields by country with a developed /"
            " emerging split, heatmap intensity per yield, and a Δ-vs-US"
            " column so an operator can spot dislocations in a glance."
        ),
        asset_classes=[AssetClass.BOND, AssetClass.RATE],
        inputs=[
            InputSpec(
                name="region",
                label="Region",
                control=ControlKind.SELECT,
                required=False,
                description="Filter the grid by region bucket.",
                options=["all", "dm", "em"],
            ),
            InputSpec(
                name="live_bonds",
                label="Live FRED",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "If true, pull live sovereign yields from FRED. When false the"
                    " pane shows labelled template rows from the sovereign_yield_model."
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
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                    DataMode.MODELED.value,
                ],
            ),
        ],
        defaults={
            "region": "all",
            "live_bonds": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.MODELED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="global", persist=True),
        output_contract=OutputContract(
            must_have=["rows", "as_of", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="category", label="Country"),
            y_axis=AxisSpec(type="numeric", unit="%", label="Yield"),
            panes=[
                PaneGrammar(name="yield_heatmap", series_kind="bar", height_pct=100),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="country", label="Country", kind="text", width_hint=96),
                ColumnSpec(key="tenor", label="Tenor", kind="tag", width_hint=72),
                ColumnSpec(key="yield", label="Yield", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="spread_vs_us", label="Δ vs US", kind="number", unit="bp", format="%.0f"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
                ColumnSpec(key="as_of", label="As of", kind="date"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="avg_yield", label="Avg yield", kind="big_number", unit="%"),
                CardSlot(key="spread_dm_em", label="DM↔EM spread", kind="kpi", unit="pp"),
                CardSlot(key="highest", label="Highest", kind="kpi", unit="%"),
                CardSlot(key="lowest", label="Lowest", kind="kpi", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "WB ships a curated country roster split into developed (US/DE/JP/GB/FR/IT/ES/AU/CA) and"
            " emerging (TR/BR/MX/ZA/IN/CN/RU/ID) buckets. With ``live_bonds=true`` the engine fans out"
            " FRED long-rate series IDs (DGS10, IRLTLT01* family) per country and pins them into the"
            " grid with as_of dates. With ``live_bonds=false`` (default) the response carries labelled"
            " ``source_mode=sovereign_yield_model`` rows so the pane never silently fakes a live read."
            " Δ-vs-US is computed client-side as (country_yield - US_yield) × 100 bp; rank intensity"
            " uses the visible min/max so the heatmap rescales when the region tab is switched."
        ),
        formula_dict={
            "spread_vs_us": Formula(
                expression=r"\Delta_{bp} = (y_{country} - y_{US}) \times 100",
                variables={"y_country": "Sovereign yield (%)", "y_US": "US 10Y yield (%)"},
                notes="Spread in basis points relative to US Treasury 10Y.",
            ),
        },
        field_dict={
            "rows[].country": FieldDef(description="ISO-2 country code.", source="catalog"),
            "rows[].tenor": FieldDef(description="Curve tenor label (10Y).", source="catalog"),
            "rows[].yield": FieldDef(unit="%", description="Annualized sovereign yield.", source="fred"),
            "rows[].source_mode": FieldDef(
                description="'fred' for live rows, 'sovereign_yield_model' for template.",
                source="adapter",
            ),
            "rows[].as_of": FieldDef(unit="date", description="Date of the yield observation.", source="fred"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["yield_above", "yield_below", "spread_above", "spread_below"],
            delivery=["tray", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="wb_template_mode_is_labelled",
                description="With live_bonds=false rows carry source_mode=sovereign_yield_model.",
                inputs={"live_bonds": False},
                assertions=[
                    "rows_non_empty",
                    "every_row_source_mode_equals_sovereign_yield_model",
                ],
            ),
            SemanticTest(
                name="wb_live_mode_routes_to_fred",
                description="With live_bonds=true the chain hits FRED and rows are flagged source_mode=fred.",
                inputs={"live_bonds": True},
                assertions=[
                    "provider_chain_used_fred",
                    "at_least_one_row_source_mode_equals_fred",
                ],
            ),
            SemanticTest(
                name="wb_spread_vs_us_correct_sign",
                description="EM yields > US yields produce positive Δ vs US in basis points.",
                inputs={"region": "em"},
                assertions=["em_rows_have_positive_spread_vs_us"],
            ),
            SemanticTest(
                name="wb_region_filter_isolates_dm_em",
                description="region=dm only returns developed-market codes; region=em only EM codes.",
                inputs={"region": "dm"},
                assertions=["dm_filter_excludes_em_codes"],
            ),
        ],
    )


__all__ = ["wb"]
