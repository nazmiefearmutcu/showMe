"""GMM — Global Macro Movers.

Ranked surprise ladder across cross-country macro releases — the biggest
standardized beats and misses surfaced as a diverging bar ladder so an
analyst can see at a glance which release moved the most in σ-units
across the lookback window.
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
            "Ranked ladder of the largest standardized macro surprises across countries "
            "and release categories over a configurable window — diverging bar chart so "
            "an analyst can see at a glance which prints have moved the tape in σ-units."
        ),
        asset_classes=[
            AssetClass.RATE,
            AssetClass.FX,
            AssetClass.EQUITY,
            AssetClass.COMMODITY,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="window",
                label="Window",
                control=ControlKind.SELECT,
                required=True,
                description="Lookback window for ranking macro surprises.",
                options=["24h", "1w", "1m", "3m"],
            ),
            InputSpec(
                name="countries",
                label="Countries",
                control=ControlKind.MULTISELECT,
                required=False,
                description="ISO 3166-1 alpha-2 list; empty = all G20.",
                options=["US", "EZ", "GB", "JP", "CN", "TR", "BR", "IN", "CA", "AU", "CH", "MX", "KR"],
            ),
            InputSpec(
                name="categories",
                label="Categories",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Release type filter; empty = all categories.",
                options=["cpi", "gdp", "employment", "central_bank", "pmi", "retail_sales", "trade_balance"],
            ),
            InputSpec(
                name="top_n",
                label="Top N",
                control=ControlKind.NUMBER,
                required=False,
                description="How many movers to rank (5..50).",
                min=5,
                max=50,
                step=5,
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
            "window": "1w",
            "countries": [],
            "categories": [],
            "top_n": 15,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["economic_calendar_rss", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "movers", "window", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="σ", label="Standardized surprise"),
            y_axis=AxisSpec(type="category", label="Release"),
            panes=[
                PaneGrammar(name="surprise_ladder", series_kind="bar", height_pct=100),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="rank", label="Rank", kind="number", format="%d", width_hint=48),
                ColumnSpec(key="time_utc", label="Released", kind="datetime", format="rel-time"),
                ColumnSpec(key="country", label="Country", kind="tag"),
                ColumnSpec(key="category", label="Cat", kind="tag"),
                ColumnSpec(key="name", label="Release", kind="text"),
                ColumnSpec(key="surprise", label="Surprise", kind="number", format="%.2f", unit="σ"),
                ColumnSpec(key="direction", label="Dir", kind="tag"),
                ColumnSpec(key="actual", label="Actual", kind="number", format="%.2f"),
                ColumnSpec(key="consensus", label="Cons", kind="number", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="biggest_beat", label="Biggest Beat", kind="big_number", unit="σ"),
                CardSlot(key="biggest_miss", label="Biggest Miss", kind="big_number", unit="σ"),
                CardSlot(key="movers_count", label="Movers", kind="kpi"),
                CardSlot(key="window", label="Window", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "GMM pulls released macro events from FRED's series_observations endpoint over the "
            "configured window for the country and category filters. For each release with a "
            "consensus value, the standardized surprise is computed as (actual - consensus) / "
            "stdev_actual_last_24m. Releases with no consensus are excluded from the ranking "
            "(they appear in ECO's calendar but cannot be scored). The top N movers (by absolute "
            "surprise magnitude) are returned in descending order with a direction tag (beat / "
            "miss / inline) derived from the release category's editorial bias — CPI prints "
            "above consensus tag as 'beat' on the inflation-hawk side, while unemployment prints "
            "above consensus tag as 'miss' on the growth side. The bar ladder visualises each "
            "row as a diverging bar centered at zero σ. No mover is ever fabricated: when the "
            "calendar feed yields zero releases in the window, movers is the empty array and a "
            "warning explains the empty window."
        ),
        formula_dict={
            "surprise_sigma": Formula(
                expression=r"surprise = \frac{actual - consensus}{\sigma_{24m}}",
                variables={
                    "actual": "Released value",
                    "consensus": "Survey median",
                    "sigma_{24m}": "Standard deviation of actual over last 24 months",
                },
                notes="Standardized surprise in units of historical σ; consistent with ECO.",
            ),
        },
        field_dict={
            "movers[].rank": FieldDef(description="1-indexed rank by |surprise| descending.", source="computed"),
            "movers[].time_utc": FieldDef(unit="iso8601", description="Release time.", source="calendar"),
            "movers[].country": FieldDef(description="ISO 3166-1 alpha-2 country code.", source="calendar"),
            "movers[].category": FieldDef(description="Release category (cpi / gdp / employment / ...).", source="reference"),
            "movers[].name": FieldDef(description="Release name (e.g. CPI YoY).", source="reference"),
            "movers[].surprise": FieldDef(unit="σ", description="Standardized surprise.", source="computed"),
            "movers[].direction": FieldDef(description="beat / miss / inline classification.", source="computed"),
            "movers[].actual": FieldDef(unit="varies", description="Released value.", source="fred"),
            "movers[].consensus": FieldDef(unit="varies", description="Survey median.", source="economic_calendar_rss"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="gmm_movers_sorted_by_abs_surprise_desc",
                description="Asserts movers array is sorted by |surprise| descending.",
                inputs={"window": "1w"},
                assertions=["movers_sorted_by_abs_surprise_desc"],
            ),
            SemanticTest(
                name="gmm_excludes_releases_without_consensus",
                description="Asserts no mover row has consensus == null (no-consensus releases are dropped from the ranking).",
                inputs={"window": "1w"},
                assertions=["every_mover_has_non_null_consensus"],
            ),
            SemanticTest(
                name="gmm_empty_window_explained",
                description="When the calendar feed has no releases in the window, asserts movers=[] and warning explains the empty window.",
                inputs={"window": "24h", "_mock": "calendar_empty"},
                assertions=["movers_empty_array", "warning_mentions_empty_window"],
            ),
            SemanticTest(
                name="gmm_top_n_caps_ranking",
                description="With top_n=10, asserts len(movers) <= 10.",
                inputs={"top_n": 10},
                assertions=["movers_length_le_top_n"],
            ),
        ],
    )


__all__ = ["gmm"]
