"""DEBT — Sovereign Debt Exposure.

Macro-level sovereign debt table: debt/GDP, share of debt issued in local
currency, and (when portfolio holdings are wired) the operator's actual
portfolio country weight. The bundled baseline pins ``portfolio_weight_pct
= 0`` so the macro table is never misread as real portfolio exposure.
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
    AlertingSpec,
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
def debt() -> FunctionManifest:
    return FunctionManifest(
        code="DEBT",
        name="Sovereign Debt Exposure",
        category=Category.BONDS_RATES,
        intent=(
            "Show sovereign debt-to-GDP, local-currency share, and (when portfolio"
            " holdings are connected) the operator's actual country weight, so a"
            " macro overlay reads next to portfolio exposure."
        ),
        asset_classes=[AssetClass.BOND, AssetClass.RATE],
        inputs=[
            InputSpec(
                name="countries",
                label="Countries",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict the table to a set of ISO-2 country codes; empty = all.",
            ),
            InputSpec(
                name="exposures",
                label="Exposures (manual)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description=(
                    "Optional user-supplied exposures list of"
                    " {country, debt_to_gdp, local_currency_share, portfolio_weight_pct}"
                    " used when no macro feed is connected."
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
            primary="worldbank",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
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
                ColumnSpec(key="country", label="Country", kind="text", width_hint=80),
                ColumnSpec(key="debt_to_gdp", label="Debt / GDP", kind="percent", unit="%", format="%.1f"),
                ColumnSpec(key="local_currency_share", label="Local ccy %", kind="percent", unit="%", format="%.1f"),
                ColumnSpec(key="portfolio_weight_pct", label="Portfolio wt", kind="percent", unit="%", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="countries", label="Countries", kind="kpi"),
                CardSlot(key="avg_debt_to_gdp", label="Avg debt/GDP", kind="big_number", unit="%"),
                CardSlot(key="portfolio_linked", label="Portfolio", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DEBT is a sovereign macro exposure table. Debt/GDP is pulled live from the World Bank"
            " general-government debt-to-GDP indicator (annual, keyless), taking the most recent"
            " non-null observation per country; each row reports the observation ``year`` so the data"
            " vintage is distinct from the fetch timestamp. local_currency_share is a published"
            " REFERENCE (a stable, labelled lookup), NOT a live World Bank series. Without a portfolio"
            " link the bundled baseline pins ``portfolio_weight_pct = 0`` for every country so it is"
            " never misread as actual operator exposure; ``summary.portfolio_linked`` reports the"
            " wiring state explicitly. Country rows can be restricted via the ``countries`` filter"
            " (case-insensitive); supplying ``exposures`` directly bypasses the World Bank fetch."
        ),
        formula_dict={},
        field_dict={
            "rows[].country": FieldDef(description="ISO-2 country code.", source="catalog"),
            "rows[].debt_to_gdp": FieldDef(unit="%", description="General government debt as percent of GDP (World Bank, latest annual).", source="worldbank"),
            "rows[].local_currency_share": FieldDef(unit="%", description="Published REFERENCE share of sovereign debt issued in local currency (not a live World Bank series).", source="worldbank_reference"),
            "rows[].year": FieldDef(description="Year of the World Bank debt-to-GDP observation.", source="worldbank"),
            "rows[].portfolio_weight_pct": FieldDef(unit="%", description="Portfolio country weight; zero when no portfolio link.", source="portfolio_state"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["debt_to_gdp_above", "local_ccy_share_below"],
            delivery=["log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="debt_baseline_portfolio_weight_is_zero",
                description=(
                    "Without a portfolio link, every row's portfolio_weight_pct is exactly 0 and"
                    " summary.portfolio_linked is false — the macro table never advertises hidden"
                    " portfolio exposure."
                ),
                inputs={},
                assertions=[
                    "every_row_portfolio_weight_pct_equals_zero",
                    "summary_portfolio_linked_is_false",
                ],
            ),
            SemanticTest(
                name="debt_country_filter_is_case_insensitive",
                description="countries=['us'] returns the US row even when the catalog stores 'US'.",
                inputs={"countries": ["us"]},
                assertions=[
                    "rows_length_equals_1",
                    "single_row_country_equals_US",
                ],
            ),
            SemanticTest(
                name="debt_user_supplied_exposures_pass_through",
                description="Supplying ``exposures`` directly bypasses the macro baseline.",
                inputs={"exposures": [{"country": "ZZ", "debt_to_gdp": 99.0, "local_currency_share": 50.0, "portfolio_weight_pct": 0.0}]},
                assertions=[
                    "rows_length_equals_1",
                    "single_row_country_equals_ZZ",
                ],
            ),
            SemanticTest(
                name="debt_summary_counts_visible_rows",
                description="summary.countries equals the visible row count after filtering.",
                inputs={"countries": ["US", "DE"]},
                assertions=["summary_countries_equals_2"],
            ),
        ],
    )


__all__ = ["debt"]
