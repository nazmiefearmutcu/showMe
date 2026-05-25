"""ECST — Economic Statistics (FRED series explorer).

Mirrors FRED's series explorer surface: pick a series_id, compare with
a second series_id, choose a frequency normalization, and (optionally)
pin a vintage. Built from the existing ECSTFunction (fred-first), plus
spec-style compare/revisions/vintages on top.
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
def ecst() -> FunctionManifest:
    return FunctionManifest(
        code="ECST",
        name="Economic Statistics",
        category=Category.MACRO,
        intent=(
            "FRED series explorer for a single named macro series, with optional "
            "compare-with overlay, frequency normalization, and vintage selection "
            "for revision tracking."
        ),
        asset_classes=[AssetClass.RATE, AssetClass.BOND, AssetClass.FX],
        inputs=[
            InputSpec(
                name="series_id",
                label="Series",
                control=ControlKind.TEXT,
                required=True,
                description="FRED series id (e.g. CPIAUCSL, GDPC1, UNRATE, DGS10, DGS2).",
                options=["CPIAUCSL", "GDPC1", "UNRATE", "DGS10", "DGS2"],
            ),
            InputSpec(
                name="date_range",
                label="Date Range",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Inclusive start/end window for the observation series.",
                options=["1Y", "3Y", "5Y", "10Y", "20Y", "MAX"],
            ),
            InputSpec(
                name="compare_with",
                label="Compare with",
                control=ControlKind.TEXT,
                required=False,
                description="Second FRED series id to overlay on the same axes.",
            ),
            InputSpec(
                name="frequency",
                label="Frequency",
                control=ControlKind.SELECT,
                required=False,
                description="Resampling frequency for the normalized series.",
                options=["native", "daily", "weekly", "monthly", "quarterly", "annual"],
            ),
            InputSpec(
                name="vintage",
                label="Vintage",
                control=ControlKind.SELECT,
                required=False,
                description=(
                    "Pin a specific FRED ALFRED vintage to see the series as it looked "
                    "on that release date. 'latest' uses the most recent vintage."
                ),
                options=["latest"],
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
            "series_id": "CPIAUCSL",
            "date_range": "10Y",
            "frequency": "native",
            "vintage": "latest",
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=600,
            scope="per_input",
            persist=True,
        ),
        output_contract=OutputContract(
            must_have=["series_id", "rows", "as_of"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_LINE,
            x_axis=AxisSpec(type="time", unit="iso8601", label="Date"),
            y_axis=AxisSpec(type="numeric", unit="value", label="Value"),
            panes=[
                PaneGrammar(name="series", series_kind="line", height_pct=100),
            ],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="date", label="Date", kind="date", format="yyyy-MM-dd"),
                ColumnSpec(key="series_id", label="Series", kind="text"),
                ColumnSpec(key="series_name", label="Name", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.6f"),
                ColumnSpec(key="unit", label="Unit", kind="text"),
                ColumnSpec(key="frequency", label="Freq", kind="tag"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="series", label="Series", kind="big_number"),
                CardSlot(key="latest", label="Latest", kind="big_number", unit="value"),
                CardSlot(key="unit", label="Unit", kind="badge"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
            ],
        ),
        methodology=(
            "ECST shows one named macro series at a time using FRED as the primary provider. "
            "The user supplies a series_id (validated against FRED's catalog); the handler pulls "
            "observations via the FRED series endpoint and normalizes rows into "
            "(date, value, unit, frequency). If `compare_with` is set, a second series is fetched "
            "and rendered on the same chart for visual comparison. Frequency normalization uses "
            "FRED's native resampling; 'native' leaves the series at its publication frequency. "
            "When `vintage` is non-default, ALFRED is consulted for the series as it appeared on "
            "that release date — surfacing revisions. A labelled baseline is only used when no "
            "provider returns data, and that mode is flagged in `source_mode`."
        ),
        formula_dict={
            "frequency_normalization": Formula(
                expression=r"value_{resampled,t} = aggregator(value_{native, t' \in window(t)})",
                variables={
                    "aggregator": "mean for stocks, sum for flows (FRED handles automatically)",
                    "window(t)": "Calendar bucket for target frequency",
                },
                notes="FRED's built-in frequency parameter is preferred over client-side resampling.",
            ),
        },
        field_dict={
            "date": FieldDef(unit="iso8601", description="Observation date.", source="fred"),
            "series_id": FieldDef(description="Provider series code.", source="fred"),
            "series_name": FieldDef(description="Human-readable series label.", source="fred catalog"),
            "value": FieldDef(unit="value", description="Observation value in the displayed unit.", source="fred"),
            "unit": FieldDef(description="Native unit of the series.", source="fred catalog"),
            "frequency": FieldDef(description="Publication frequency (daily/monthly/quarterly).", source="fred catalog"),
            "source_mode": FieldDef(description="Provider or fallback used for the row.", source="handler"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="ecst_returns_rows_for_cpiaucsl",
                description="ECST returns a non-empty observation list for the canonical CPIAUCSL series.",
                inputs={"series_id": "CPIAUCSL"},
                assertions=[
                    "rows_non_empty",
                    "every_row_has_date",
                    "every_row_value_is_number",
                ],
            ),
            SemanticTest(
                name="ecst_compare_with_overlays_second_series",
                description="When compare_with is set, two series are returned for the same time axis.",
                inputs={"series_id": "DGS10", "compare_with": "DGS2"},
                assertions=[
                    "primary_series_present",
                    "compare_series_present",
                    "compare_series_id_matches_input",
                ],
            ),
            SemanticTest(
                name="ecst_fred_is_primary_provider",
                description="Source list must lead with 'fred' when FRED returns data.",
                inputs={"series_id": "UNRATE"},
                assertions=["sources_starts_with_fred"],
            ),
            SemanticTest(
                name="ecst_vintage_pin_returns_pre_revision_values",
                description=(
                    "When vintage is pinned to a historical release date, values for that as-of "
                    "must match the published-at-time value, not the latest revision."
                ),
                inputs={"series_id": "GDPC1", "vintage": "2024-04-25"},
                assertions=["values_match_alfred_vintage"],
            ),
            SemanticTest(
                name="ecst_frequency_normalization_respected",
                description="Asking for monthly normalization on a daily series returns ≤1 row per month.",
                inputs={"series_id": "DGS10", "frequency": "monthly"},
                assertions=["row_dates_at_most_one_per_calendar_month"],
            ),
        ],
    )


__all__ = ["ecst"]
