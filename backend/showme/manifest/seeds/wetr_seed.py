"""WETR — Weather → Commodity Sensitivity.

Surfaces daily weather observations + forecasts for commodity-
relevant regions (US northeast for heating, US Gulf for hurricanes,
EU NW / Asia East for cooling demand) with HDD/CDD and a curated
commodity-impact label. When no OpenWeather key is configured the
handler returns ``provider_unavailable`` with a labelled seasonal-
model fallback — never a fabricated live forecast.
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
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def wetr() -> FunctionManifest:
    return FunctionManifest(
        code="WETR",
        name="Weather → Commodity Sensitivity",
        category=Category.COMMODITIES,
        intent=(
            "Daily weather (temp / precip / HDD / CDD) for commodity-"
            "relevant regions with curated commodity-impact labels. "
            "Provider-unavailable path is labelled — never a fake forecast."
        ),
        asset_classes=[AssetClass.COMMODITY],
        inputs=[
            InputSpec(
                name="location",
                label="Region",
                control=ControlKind.SELECT,
                required=True,
                description="Curated weather region with a commodity context.",
                options=[
                    "US_NORTHEAST",
                    "US_GULF",
                    "US_MIDWEST",
                    "EU_NW",
                    "ASIA_EAST",
                    "BRAZIL_SE",
                ],
            ),
            InputSpec(
                name="days",
                label="Forecast days",
                control=ControlKind.SELECT,
                required=True,
                description="Forecast horizon in days.",
                options=["3", "5", "10", "14"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade to seasonal model.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.MODELED.value,
                ],
            ),
        ],
        defaults={
            "location": "US_NORTHEAST",
            "days": "10",
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        # NOTE: openweathermap is the canonical adapter; when no API key is
        # configured the chain downgrades to the in-process seasonal model.
        provider_chain=ProviderChain(
            primary="openweathermap",
            fallbacks=["seasonal_weather_model", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.PROVIDER_UNAVAILABLE,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=1800, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "location",
                "rows",
                "source_mode",
                "as_of",
                "commodity_context",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="date", label="Date", kind="date"),
                ColumnSpec(key="day", label="Day", kind="text"),
                ColumnSpec(key="temp_c", label="Temp °C", kind="number", format="%.1f"),
                ColumnSpec(key="precip_mm", label="Precip mm", kind="number", format="%.1f"),
                ColumnSpec(key="hdd", label="HDD", kind="number", format="%.1f"),
                ColumnSpec(key="cdd", label="CDD", kind="number", format="%.1f"),
                ColumnSpec(key="risk_flag", label="Risk", kind="tag"),
                ColumnSpec(key="commodity_impact", label="Commodity impact", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="avg_temp", label="Avg temp", kind="big_number", unit="°C"),
                CardSlot(key="total_hdd", label="HDD (Σ)", kind="kpi"),
                CardSlot(key="total_cdd", label="CDD (Σ)", kind="kpi"),
                CardSlot(key="risk_days", label="Risk days", kind="kpi"),
                CardSlot(key="commodity_context", label="Commodity", kind="badge"),
                CardSlot(key="source_mode", label="Source", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "WETR pulls a daily forecast (temp, precip) for the chosen "
            "region from OpenWeather One Call when an API key is "
            "configured. HDD = max(0, 18°C - temp) and CDD = max(0, "
            "temp - 18°C) per UK Met Office convention. Each region carries "
            "a curated commodity_context (US_NORTHEAST → NatGas heating, "
            "US_GULF → refined-product hurricane risk, BRAZIL_SE → coffee/"
            "sugar). If no key is set the chain downgrades to "
            "seasonal_weather_model — a labelled climatological average — "
            "and source_mode flips so consumers can render the seasonal-"
            "model banner. There is no synthesized 'live' forecast: the "
            "handler refuses to fake openweathermap output."
        ),
        formula_dict={
            "hdd": Formula(
                expression=r"HDD = \max(0, 18 - T_{avg})",
                variables={"T_avg": "Daily mean temperature (°C)"},
                notes="Heating degree days, 18°C base.",
            ),
            "cdd": Formula(
                expression=r"CDD = \max(0, T_{avg} - 18)",
                variables={"T_avg": "Daily mean temperature (°C)"},
                notes="Cooling degree days, 18°C base.",
            ),
        },
        field_dict={
            "location": FieldDef(description="Curated region code.", source="input"),
            "commodity_context": FieldDef(description="Commodity sector this region drives.", source="curated"),
            "rows[].temp_c": FieldDef(unit="°C", description="Daily mean temperature.", source="provider"),
            "rows[].precip_mm": FieldDef(unit="mm", description="Daily total precipitation.", source="provider"),
            "rows[].hdd": FieldDef(description="Heating degree days (18°C base).", source="computed"),
            "rows[].cdd": FieldDef(description="Cooling degree days (18°C base).", source="computed"),
            "rows[].risk_flag": FieldDef(description="severe | hot | cold | normal.", source="rules"),
            "rows[].commodity_impact": FieldDef(description="Human-readable impact note (e.g. 'bullish NatGas').", source="rules"),
            "source_mode": FieldDef(description="live_openweathermap | seasonal_model | cached.", source="envelope"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="wetr_returns_daily_rows_with_hdd_cdd",
                description="WETR returns daily rows with HDD + CDD per region.",
                inputs={"location": "US_NORTHEAST", "days": "10"},
                assertions=[
                    "rows_non_empty",
                    "every_row_has_hdd_and_cdd",
                    "commodity_context_present",
                ],
            ),
            SemanticTest(
                name="explicit_provider_unavailable_when_no_weather_key",
                description=(
                    "Without an OpenWeather API key configured, WETR returns "
                    "status=provider_unavailable (or downgrades to labelled "
                    "source_mode=seasonal_model) — never a fabricated "
                    "openweathermap response."
                ),
                inputs={"location": "US_NORTHEAST", "_mock": "no_openweather_key"},
                assertions=[
                    "status_is_provider_unavailable_or_source_mode_is_seasonal_model",
                    "no_synthetic_live_forecast",
                    "next_actions_mention_api_key",
                ],
            ),
            SemanticTest(
                name="wetr_no_fake_live_label_on_seasonal_model",
                description="source_mode=seasonal_model must never be reported as live_openweathermap.",
                inputs={"location": "US_NORTHEAST", "_mock": "no_openweather_key"},
                assertions=["source_mode_not_equal_live_openweathermap_when_no_key"],
            ),
        ],
    )


__all__ = ["wetr"]
