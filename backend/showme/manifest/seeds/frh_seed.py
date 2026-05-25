"""FRH — Funding Rate Heatmap (crypto perpetuals).

Cross-symbol funding-rate snapshot for Binance USDT-margined
perpetuals. Surfaces the funding rate over the last 8h window for the
top-N perpetuals by open interest as a heatmap (symbols on y-axis, time
buckets on x-axis, color = annualized funding rate). The wave2 contract
pins ``chart_grammar.kind=HEATMAP`` and the semantic test
``frh_chart_grammar_is_heatmap`` enforces it.
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
            "Surface the funding rate over the last 8h window for the top-N Binance USDT-margined "
            "perpetuals as a heatmap (symbols on y, time buckets on x, color = annualized funding "
            "rate) so an operator can spot positioning skew across the perp tape."
        ),
        asset_classes=[AssetClass.CRYPTO, AssetClass.FUTURE],
        inputs=[
            InputSpec(
                name="quote_currency",
                label="Quote",
                control=ControlKind.SELECT,
                required=True,
                description="Restrict to perpetuals quoted in this currency.",
                options=["USDT", "USDC", "BUSD"],
            ),
            InputSpec(
                name="top_n",
                label="Top N",
                control=ControlKind.NUMBER,
                required=True,
                description="Number of symbols on the heatmap (ranked by open interest).",
                min=5,
                max=100,
                step=5,
            ),
            InputSpec(
                name="window",
                label="Window",
                control=ControlKind.SELECT,
                required=True,
                description="Time window covered by the heatmap.",
                options=["8h", "24h", "3d", "7d", "30d"],
            ),
            InputSpec(
                name="bucket_minutes",
                label="Bucket (min)",
                control=ControlKind.NUMBER,
                required=False,
                description="Time-axis bucket width.",
                min=15,
                max=1440,
                step=15,
                unit="min",
            ),
            InputSpec(
                name="symbol_filter",
                label="Symbols",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to these explicit symbols (overrides top_n).",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; provider may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "quote_currency": "USDT",
            "top_n": 30,
            "window": "24h",
            "bucket_minutes": 60,
            "symbol_filter": [],
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            primary="binance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "symbols", "buckets", "matrix", "quote_currency", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        # Wave2 mandate: FRH chart grammar is HEATMAP, NOT row-index/series.
        # See semantic_test `frh_chart_grammar_is_heatmap`.
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="time", unit="", label="Bucket"),
            y_axis=AxisSpec(type="category", unit="", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="last_funding_rate", label="Last FR", kind="percent", format="%.4f"),
                ColumnSpec(key="annualized_rate", label="Annualized", kind="percent", format="%.2f"),
                ColumnSpec(key="mark_price", label="Mark", kind="currency", format="%.4f"),
                ColumnSpec(key="open_interest_usd", label="OI", kind="currency", format="si"),
                ColumnSpec(key="next_funding_time", label="Next", kind="datetime", format="rel-time"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbols_count", label="Symbols", kind="kpi"),
                CardSlot(key="buckets_count", label="Buckets", kind="kpi"),
                CardSlot(key="median_annualized_rate", label="Median Annual.", kind="kpi", unit="%"),
                CardSlot(key="most_positive", label="Most Positive", kind="badge"),
                CardSlot(key="most_negative", label="Most Negative", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FRH pulls Binance futures fundingRate (GET /fapi/v1/fundingRate) for the chosen `window` "
            "for each symbol in the top-N by open_interest_usd (from /fapi/v1/openInterest joined "
            "with /fapi/v1/premiumIndex for the USD notional). Funding events occur every 8h on "
            "Binance; rates are bucketed into `bucket_minutes` cells by averaging events that fall "
            "in the bucket. annualized_rate = funding_rate * (3 * 365) since there are 3 funding "
            "events per day. The output matrix is shape (n_symbols, n_buckets) with cell = "
            "annualized rate; missing cells stay null (no synthetic 0). Rendered as a HEATMAP with "
            "a diverging color scale anchored at 0 (cool blue = negative funding, warm red = "
            "positive). Sort heatmap symbols by mean(annualized_rate) desc. Next actions: "
            "open_perp_chart, save_screen, export_csv."
        ),
        formula_dict={
            "annualized_rate": Formula(
                expression=r"r_{ann} = r_{8h} \times 3 \times 365",
                variables={"r_{8h}": "8h funding rate from /fapi/v1/fundingRate"},
                notes="Binance perpetuals fund every 8h, so three events per day, 365 days per year.",
            ),
        },
        field_dict={
            "symbols": FieldDef(description="Ordered list of N perpetual symbols (heatmap row labels).", source="binance"),
            "buckets": FieldDef(unit="iso8601[]", description="Time-bucket boundaries (heatmap column labels).", source="derived"),
            "matrix": FieldDef(unit="%", description="N×T heatmap matrix of annualized funding rate per (symbol, bucket).", source="computed"),
            "rows[].symbol": FieldDef(description="Canonical perpetual symbol (e.g. BTCUSDT).", source="binance"),
            "rows[].last_funding_rate": FieldDef(unit="ratio", description="Most recent 8h funding rate.", source="binance"),
            "rows[].annualized_rate": FieldDef(unit="%", description="last_funding_rate * 1095.", source="computed"),
            "rows[].mark_price": FieldDef(unit="quote_ccy", description="Current mark price.", source="binance"),
            "rows[].open_interest_usd": FieldDef(unit="USD", description="USD-equivalent open interest.", source="computed"),
            "rows[].next_funding_time": FieldDef(unit="iso8601", description="Timestamp of next funding event.", source="binance"),
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
                name="frh_matrix_shape_matches_symbols_x_buckets",
                description="matrix has shape (len(symbols), len(buckets)) and every row aligns to the symbols list.",
                inputs={"top_n": 30, "window": "24h"},
                assertions=[
                    "matrix_row_count_equals_symbols_length",
                    "matrix_col_count_equals_buckets_length",
                ],
            ),
            SemanticTest(
                name="frh_annualized_rate_matches_formula",
                description="annualized_rate = last_funding_rate * 3 * 365 within float tolerance.",
                inputs={},
                assertions=["annualized_rate_matches_formula_within_tolerance"],
            ),
            SemanticTest(
                name="frh_missing_bucket_is_null_not_synthetic_zero",
                description="A symbol that lacks funding data for a bucket has matrix[i][j]=null, not 0.",
                inputs={},
                assertions=[
                    "missing_cell_is_null_not_zero",
                    "no_synthetic_fields",
                ],
            ),
            SemanticTest(
                name="frh_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="frh_provider_unavailable_returns_empty_matrix_not_synthetic",
                description="When Binance futures is unreachable matrix=[] symbols=[] and data_mode=provider_unavailable.",
                inputs={},
                assertions=[
                    "matrix_is_empty_on_provider_failure",
                    "symbols_is_empty_on_provider_failure",
                    "data_mode_equals_provider_unavailable",
                ],
            ),
        ],
    )


__all__ = ["frh"]
