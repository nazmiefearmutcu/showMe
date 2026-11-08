"""FRH — Funding Rate Heatmap (crypto perpetuals).

Current funding-rate snapshot for USDT-margined perpetuals on Binance, Bybit
and OKX. One row per symbol with each venue's rate and the cross-venue average,
in fraction per funding interval (not annualised). The handler does not yet
compute a historical window, time buckets or a symbol-by-time matrix; the
manifest describes only what is returned. The wave2 contract still pins
``chart_grammar.kind=HEATMAP`` (semantic test ``frh_chart_grammar_is_heatmap``).
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
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def frh() -> FunctionManifest:
    return FunctionManifest(
        code="FRH",
        name="Funding Rate Heatmap",
        category=Category.SCREENING,
        intent=(
            "Snapshot the current perpetual funding rate for a set of USDT-margined perpetuals on "
            "Binance, Bybit and OKX, one row per symbol, so an operator can see positioning skew "
            "across venues. Rates are fraction per funding interval, not annualised."
        ),
        asset_classes=[AssetClass.CRYPTO, AssetClass.FUTURE],
        inputs=[
            InputSpec(
                name="symbols",
                label="Symbols",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Explicit perpetual symbols (e.g. BTCUSDT). Overrides the universe size.",
            ),
            InputSpec(
                name="limit",
                label="Universe size",
                control=ControlKind.NUMBER,
                required=False,
                description=(
                    "Number of symbols when no explicit list is given: the built-in list of 25 "
                    "majors, or above 25 the Binance 24h quote-volume ranking. If that ranking is "
                    "unavailable the 25 majors are returned and a warning reports the shortfall."
                ),
                min=1,
                max=100,
                step=1,
            ),
        ],
        defaults={
            "symbols": [],
            "limit": 25,
        },
        provider_chain=ProviderChain(
            primary="binance",
            fallbacks=["bybit", "okx"],
            acceptable_modes=[DataMode.LIVE_EXCHANGE],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["rows", "exchanges", "unit"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        # Wave2 mandate (pinned by test_wave2_screening_seeds): HEATMAP grammar.
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="category", unit="", label="Venue"),
            y_axis=AxisSpec(type="category", unit="", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="binance", label="Binance (frac/interval)", kind="number", format="%.6f"),
                ColumnSpec(key="bybit", label="Bybit (frac/interval)", kind="number", format="%.6f"),
                ColumnSpec(key="okx", label="OKX settled (frac/interval)", kind="number", format="%.6f"),
                ColumnSpec(key="avg", label="Venue average (frac)", kind="number", format="%.6f"),
                ColumnSpec(key="provider_count", label="Venues", kind="number", format="%d"),
                ColumnSpec(key="interpretation", label="Signal", kind="text"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbols_count", label="Symbols", kind="kpi"),
                CardSlot(key="most_positive", label="Most Positive", kind="badge"),
                CardSlot(key="most_negative", label="Most Negative", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FRH fetches the current perpetual funding rate for each symbol from Binance "
            "(/fapi/v1/premiumIndex lastFundingRate, last settled), Bybit (/v5/market/funding/history "
            "fundingRate, last settled; the tickers fundingRate is the pending estimate and is not used) "
            "and OKX (/api/v5/public/funding-rate settFundingRate, last settled; "
            "OKX fundingRate is the current-period estimate and is not used). Each value is a "
            "fraction per funding interval; venues do not share one interval, so rates are not "
            "annualised. avg is the mean of the venues that returned a rate. A row with fewer "
            "than two venues carries no cross-venue signal (signal_suppressed=true). Universe: "
            "explicit symbols, else the built-in list of 25 majors, else (above 25) Binance 24h "
            "quote-volume ranking; universe_basis reports which. If that ranking is unavailable the "
            "25 majors are returned with a warning that reports the shortfall (universe_requested vs "
            "universe_returned). Missing venues are null, never 0."
        ),
        formula_dict={
            "avg": Formula(
                expression=r"\bar{r} = \frac{1}{n} \sum_{v} r_v",
                variables={
                    "r_v": "last settled funding rate on venue v (fraction per funding interval)",
                    "n": "number of venues that returned a rate for the symbol",
                },
                notes="Equal-weight mean across venues; not a single timestamp across exchanges.",
            ),
        },
        field_dict={
            "rows[].symbol": FieldDef(description="Perpetual symbol (e.g. BTCUSDT).", source="binance"),
            "rows[].binance": FieldDef(unit="fraction_per_interval", description="Binance last settled funding rate.", source="binance"),
            "rows[].bybit": FieldDef(unit="fraction_per_interval", description="Bybit last settled funding rate (funding history, not the pending tickers estimate).", source="bybit"),
            "rows[].okx": FieldDef(unit="fraction_per_interval", description="OKX last settled funding rate (settFundingRate).", source="okx"),
            "rows[].avg": FieldDef(unit="fraction_per_interval", description="Mean of the venue rates that were returned.", source="computed"),
            "rows[].provider_count": FieldDef(unit="count", description="Number of venues that returned a rate.", source="computed"),
            "rows[].signal_suppressed": FieldDef(description="True when fewer than two venues returned a rate.", source="computed"),
            "universe_basis": FieldDef(description="default_list | binance_24h_quote_volume | explicit_symbols.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="frh_chart_grammar_is_heatmap",
                description="FRH manifest pins chart_grammar.kind to heatmap — wave2 contract forbids row-index series here.",
                inputs={},
                assertions=["manifest.chart_grammar.kind == 'heatmap'"],
            ),
            SemanticTest(
                name="frh_rate_is_fraction_not_annualised",
                description="Rates are fraction per funding interval; no annualisation is applied.",
                inputs={"symbols": "BTCUSDT"},
                assertions=["rate_unit_is_fraction_per_interval"],
            ),
            SemanticTest(
                name="frh_missing_venue_is_null_and_single_venue_suppressed",
                description="A venue without a rate is null, not 0; a row with fewer than two venues has signal_suppressed=true.",
                inputs={},
                assertions=[
                    "missing_venue_is_null_not_zero",
                    "single_venue_row_signal_suppressed",
                ],
            ),
            SemanticTest(
                name="frh_provider_unavailable_returns_empty_rows_not_synthetic",
                description="When no venue returns a usable rate, rows=[] and data_mode=provider_unavailable.",
                inputs={},
                assertions=[
                    "rows_is_empty_on_provider_failure",
                    "data_mode_equals_provider_unavailable",
                ],
            ),
        ],
    )


__all__ = ["frh"]
