"""SRSK — Sovereign Risk (CDS-implied PD proxy).

Computes a probability of default per sovereign as PD ≈ spread / (1 − R)
using the published Hull approximation with R = 0.4 (recovery rate). CDS
data is not in the free feed; the engine uses the sovereign yield minus
US Treasury 10Y as a proxy spread when a FRED long-rate series is
available for that country. When DGS10 is unavailable the response is
marked ``provider_unavailable`` rather than silently emitting a flat
identical PD for every sovereign (the S12 BugHunt fix).
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
def srsk() -> FunctionManifest:
    return FunctionManifest(
        code="SRSK",
        name="Sovereign Risk",
        category=Category.BONDS_RATES,
        intent=(
            "Approximate sovereign 1Y probability of default using the published"
            " PD ≈ spread / (1 − R) identity with a yield-based proxy spread,"
            " so the operator can rank sovereigns by tail risk."
        ),
        asset_classes=[AssetClass.BOND, AssetClass.RATE],
        inputs=[
            InputSpec(
                name="countries",
                label="Countries",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Sovereign issuers to score (max 12).",
                options=["US", "DE", "JP", "GB", "FR", "IT", "ES", "AU", "CA", "TR", "BR", "MX", "ZA", "IN", "CN", "RU", "ID"],
            ),
            InputSpec(
                name="recovery",
                label="Recovery rate (R)",
                control=ControlKind.NUMBER,
                required=False,
                description="Assumed recovery rate in default (Hull default 0.4).",
                min=0.0,
                max=0.95,
                step=0.01,
            ),
            InputSpec(
                name="proxy_spread_pct",
                label="Fallback spread",
                control=ControlKind.NUMBER,
                required=False,
                description="Fallback proxy spread (%) used when no FRED mapping is available.",
                min=0.0,
                max=50.0,
                step=0.01,
                unit="%",
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
            "countries": ["TR", "US", "DE", "JP"],
            "recovery": 0.4,
            "proxy_spread_pct": 3.25,
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
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["rows", "summary", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="category", label="Country"),
            y_axis=[
                AxisSpec(type="numeric", unit="%", label="PD 1Y"),
                AxisSpec(type="numeric", unit="bp", label="Proxy spread"),
            ],
            panes=[
                PaneGrammar(name="pd_bars", series_kind="bar", height_pct=60),
                PaneGrammar(name="spread_bars", series_kind="bar", height_pct=40),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="country", label="Country", kind="text", width_hint=80),
                ColumnSpec(key="proxy_spread_pct", label="Spread", kind="percent", unit="%", format="%.3f"),
                ColumnSpec(key="pd_1y_pct", label="PD 1Y", kind="percent", unit="%", format="%.3f"),
                ColumnSpec(key="recovery", label="R", kind="number", format="%.2f"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
                ColumnSpec(key="note", label="Note", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="highest_pd_country", label="Highest PD", kind="kpi"),
                CardSlot(key="highest_pd", label="PD", kind="big_number", unit="%"),
                CardSlot(key="recovery", label="R", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "SRSK reads UST 10Y (FRED ``DGS10``) once per call. For every requested country with a"
            " known FRED long-rate series ID (a curated mapping in ``_SOVEREIGN_FRED_IDS``), the engine"
            " pulls the latest yield, computes ``proxy_spread = country_yield − ust_y`` (US itself is"
            " pinned to spread=0 with a 'self-spread is zero' note), then ``PD_1Y ≈ spread/100 /"
            " (1 − recovery)`` using the Hull approximation. Countries without a FRED mapping use the"
            " ``proxy_spread_pct`` fallback and a warning explaining the gap. When DGS10 is unavailable"
            " the response is marked ``provider_unavailable`` rather than emitting a flat identical PD"
            " for every sovereign (the S12 BugHunt fix)."
        ),
        formula_dict={
            "pd_hull": Formula(
                expression=r"PD_{1Y} \approx \frac{spread}{1 - R}",
                variables={"spread": "Proxy spread (decimal)", "R": "Recovery rate (default 0.4)"},
                notes="Hull approximation; PD is annualized.",
            ),
            "proxy_spread": Formula(
                expression=r"spread_{proxy} = y_{country} - y_{UST10Y}",
                variables={"y_country": "Sovereign 10Y yield (%)", "y_UST10Y": "US 10Y yield (%)"},
                notes="Yield-based proxy used in lieu of live CDS data.",
            ),
        },
        field_dict={
            "rows[].country": FieldDef(description="ISO-2 country code.", source="catalog"),
            "rows[].proxy_spread_pct": FieldDef(unit="%", description="Sovereign yield minus US 10Y, percent.", source="computed"),
            "rows[].pd_1y_proxy": FieldDef(unit="decimal", description="1Y PD proxy as decimal in [0,1].", source="computed"),
            "rows[].pd_1y_pct": FieldDef(unit="%", description="1Y PD proxy as percent.", source="computed"),
            "rows[].recovery": FieldDef(description="Assumed recovery rate.", source="user_or_default"),
            "rows[].source_mode": FieldDef(description="'fred' when the country has a real long-rate mapping, else 'sovereign_risk_model'.", source="adapter"),
            "rows[].note": FieldDef(description="Per-row explanation when the row uses fallback or self-spread.", source="adapter"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["pd_above", "spread_above", "country_downgrade"],
            delivery=["tray", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="srsk_dgs10_unavailable_returns_provider_unavailable",
                description=(
                    "When FRED DGS10 is down the response is marked provider_unavailable instead of"
                    " emitting a flat identical 3.25% PD for every sovereign — the S12 BugHunt fix."
                ),
                inputs={"_mock": "fred_dgs10_down"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "rows_empty_when_unavailable",
                ],
            ),
            SemanticTest(
                name="srsk_us_self_spread_is_zero",
                description="US sovereign self-spread is pinned to zero with an explicit note.",
                inputs={"countries": ["US"]},
                assertions=[
                    "us_proxy_spread_pct_equals_zero",
                    "us_row_note_mentions_self_spread",
                ],
            ),
            SemanticTest(
                name="srsk_unmapped_country_uses_fallback_with_warning",
                description=(
                    "A country without a curated FRED mapping uses proxy_spread_pct and surfaces a"
                    " warning that names the missing mapping so the operator knows the row is fallback."
                ),
                inputs={"countries": ["XX"], "proxy_spread_pct": 5.0},
                assertions=[
                    "xx_row_uses_fallback_spread",
                    "warning_mentions_no_fred_mapping_for_xx",
                ],
            ),
            SemanticTest(
                name="srsk_pd_matches_hull_identity",
                description="For a non-US country with a known mapping, pd_1y_pct = spread / (1 - R) within numerical tolerance.",
                inputs={"countries": ["TR"], "recovery": 0.4},
                assertions=["pd_matches_hull_identity_within_1e-6"],
            ),
        ],
    )


__all__ = ["srsk"]
