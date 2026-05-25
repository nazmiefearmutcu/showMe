"""GC3D — Yield Curve 3D (tenor × time → yield surface).

A date-by-tenor sovereign yield surface so the user can read curve drift
over a look-back window. Chart grammar is ``SURFACE`` (renderer can fall
back to a heatmap); the engine always returns a ``surface`` array of
{date, tenor, tenor_years, yield} points. Live mode fans out 10 FRED DGS*
series; the template fallback ships rolling-anchored dates so it never
advertises stale timestamps.
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
def gc3d() -> FunctionManifest:
    return FunctionManifest(
        code="GC3D",
        name="Yield Curve 3D",
        category=Category.BONDS_RATES,
        intent=(
            "Render a tenor × time yield surface so the analyst can read curve"
            " drift, parallel shifts, and twist over a look-back window without"
            " flipping between historical snapshots."
        ),
        asset_classes=[AssetClass.BOND, AssetClass.RATE],
        inputs=[
            InputSpec(
                name="country",
                label="Country",
                control=ControlKind.SELECT,
                required=True,
                description="Sovereign issuer whose surface is rendered.",
                options=["US"],
            ),
            InputSpec(
                name="days",
                label="Look-back",
                control=ControlKind.NUMBER,
                required=False,
                description="Look-back window in days. Clamped to [7, 3650].",
                min=7,
                max=3650,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="tenors",
                label="Tenors",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Curve points to include along the tenor axis.",
                options=["3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"],
            ),
            InputSpec(
                name="live_curve",
                label="Live FRED",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true, pull DGS* daily series from FRED for every tenor.",
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
            "country": "US",
            "days": 365,
            "tenors": ["3M", "6M", "1Y", "2Y", "5Y", "10Y", "30Y"],
            "live_curve": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["surface", "tenors", "dates", "summary", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.SURFACE,
            x_axis=AxisSpec(type="numeric", unit="years", label="Tenor"),
            y_axis=[
                AxisSpec(type="time", unit="date", label="Date"),
                AxisSpec(type="numeric", unit="%", label="Yield"),
            ],
            panes=[
                PaneGrammar(name="surface", series_kind="area", height_pct=70),
                PaneGrammar(name="atm_term_today", series_kind="line", height_pct=30),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="date", label="Date", kind="date"),
                ColumnSpec(key="tenor", label="Tenor", kind="tag", width_hint=72),
                ColumnSpec(key="tenor_years", label="Years", kind="number", format="%.2f"),
                ColumnSpec(key="yield", label="Yield", kind="percent", unit="%", format="%.3f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="points", label="Points", kind="kpi"),
                CardSlot(key="dates", label="Dates", kind="kpi"),
                CardSlot(key="tenors", label="Tenors", kind="kpi"),
                CardSlot(key="days", label="Look-back", kind="kpi", unit="days"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "GC3D builds a date-by-tenor yield surface for the chosen country. With ``live_curve=true``"
            " the engine fans out a curated list of FRED DGS* series (DGS3MO/DGS6MO/DGS1/DGS2/DGS3/"
            "DGS5/DGS7/DGS10/DGS20/DGS30) over the look-back window, normalizes to business-day dates,"
            " and emits a flat list of {date, tenor, tenor_years, yield} points. With live off the"
            " response carries a labelled template with rolling-anchored dates so it never advertises"
            " stale 2026-04 timestamps weeks after the file was written. ``days`` is clamped to"
            " [7, 3650] to keep the FRED fan-out bounded — a request for ``days=999999`` previously"
            " ballooned the query."
        ),
        formula_dict={},
        field_dict={
            "surface[].date": FieldDef(unit="date", description="Observation date.", source="fred"),
            "surface[].tenor": FieldDef(description="Treasury maturity label.", source="catalog"),
            "surface[].tenor_years": FieldDef(unit="years", description="Numeric maturity for ordering.", source="catalog"),
            "surface[].yield": FieldDef(unit="%", description="FRED Treasury yield percentage.", source="fred"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="gc3d_surface_is_three_dimensional",
                description=(
                    "Surface array contains points across at least 3 distinct dates × all selected tenors"
                    " so the renderer has real 3D structure to draw."
                ),
                inputs={"days": 90},
                assertions=[
                    "surface_distinct_dates_at_least_3",
                    "surface_distinct_tenors_equals_selected",
                    "surface_total_points_equals_dates_times_tenors",
                ],
            ),
            SemanticTest(
                name="gc3d_days_clamped_to_bounds",
                description="A days=999999 request is clamped to 3650 and a days=0 to 7.",
                inputs={"days": 999999},
                assertions=["days_clamped_to_3650"],
            ),
            SemanticTest(
                name="gc3d_template_dates_are_rolling",
                description=(
                    "Template (live off) mode emits rolling-anchored dates relative to today, never"
                    " hard-coded 2026-04 strings from the source file."
                ),
                inputs={"live_curve": False},
                assertions=["template_dates_anchored_to_today_minus_offsets"],
            ),
            SemanticTest(
                name="gc3d_live_routes_to_fred",
                description="Live mode lists FRED in the provenance source list.",
                inputs={"live_curve": True},
                assertions=["provider_chain_used_fred"],
            ),
        ],
    )


__all__ = ["gc3d"]
