"""WCRS — World currency cross rates.

Bloomberg ``WCRS<GO>`` analogue: matrix of cross rates between G10 +
key emerging market currencies. Renders as a heatmap (not a row-index
plot) so users can read the whole currency board at a glance, with
a base-currency tab strip to re-anchor the view.
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
def wcrs() -> FunctionManifest:
    return FunctionManifest(
        code="WCRS",
        name="World Currency Cross Rates",
        category=Category.FX,
        intent=(
            "Matrix of cross rates between G10 + key emerging-market "
            "currencies rendered as a heatmap, with base-currency tabs and "
            "per-pair change-percent intensity coloring."
        ),
        asset_classes=[AssetClass.FX],
        inputs=[
            InputSpec(
                name="bases",
                label="Bases",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Base currencies forming the rows of the matrix.",
                options=["USD", "EUR", "GBP", "JPY", "TRY", "CHF", "AUD", "CAD", "CNH"],
            ),
            InputSpec(
                name="quotes",
                label="Quotes",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Quote currencies forming the columns of the matrix.",
                options=["USD", "EUR", "GBP", "JPY", "TRY", "CHF", "AUD", "CAD", "CNH"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "bases": ["USD", "EUR", "GBP", "JPY", "TRY"],
            "quotes": ["USD", "EUR", "GBP", "JPY", "TRY", "CHF"],
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=30, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["rows", "matrix", "as_of", "source_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="category", unit="ccy", label="Quote"),
            y_axis=AxisSpec(type="category", unit="ccy", label="Base"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="pair", label="Pair", kind="text"),
                ColumnSpec(key="base", label="Base", kind="tag"),
                ColumnSpec(key="quote", label="Quote", kind="tag"),
                ColumnSpec(key="rate", label="Rate", kind="number", format="%.4f"),
                ColumnSpec(key="bid", label="Bid", kind="number", format="%.4f"),
                ColumnSpec(key="ask", label="Ask", kind="number", format="%.4f"),
                ColumnSpec(key="change_pct", label="Δ %", kind="percent", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="pair_count", label="Pairs", kind="kpi"),
                CardSlot(key="leader", label="Leader", kind="big_number"),
                CardSlot(key="laggard", label="Laggard", kind="big_number"),
                CardSlot(key="mean_change", label="Mean Δ", kind="trend_pill", unit="%"),
                CardSlot(key="source_mode", label="Source", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "WCRS resolves each (base, quote) pair to its yfinance "
            "BASEQUOTE=X ticker (e.g. EURUSD=X) and fans out concurrently. "
            "Self-pairs (USD/USD) are skipped. The matrix is rendered as a "
            "heatmap where each cell's background is colored by the pair's "
            "session change percent (positive = positive token, negative = "
            "negative token, intensity scaled to the band's max abs value). "
            "Cells with missing data are rendered muted with a warning "
            "instead of zero values. Source mode is exposed on the card so "
            "users never confuse the cached fallback for a live print."
        ),
        formula_dict={
            "cross_rate": Formula(
                expression=r"X_{B/Q} = \frac{S_{B/USD}}{S_{Q/USD}}",
                variables={"S_B/USD": "Base vs USD spot", "S_Q/USD": "Quote vs USD spot"},
                notes="Triangulated when direct quote is unavailable.",
            ),
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{rate - prev\_close}{prev\_close} \times 100",
                variables={"rate": "Latest cross rate", "prev_close": "Prior session close"},
            ),
        },
        field_dict={
            "rows[].pair": FieldDef(description="Concatenated BASE+QUOTE (e.g. EURUSD).", source="computed"),
            "rows[].rate": FieldDef(description="Spot cross rate.", source="provider"),
            "rows[].bid": FieldDef(description="Best bid (if available).", source="provider"),
            "rows[].ask": FieldDef(description="Best ask (if available).", source="provider"),
            "rows[].change_pct": FieldDef(unit="%", description="Session change percent.", source="computed"),
            "matrix": FieldDef(description="Nested dict {base: {quote: rate}} for direct lookup.", source="computed"),
            "source_mode": FieldDef(description="live | delayed | cached fallback label.", source="envelope"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="wcrs_chart_grammar_is_heatmap",
                description="WCRS must render as a heatmap (NOT a row-index plot).",
                inputs={},
                assertions=["chart_grammar_kind_is_heatmap"],
            ),
            SemanticTest(
                name="wcrs_returns_matrix_for_default_bases",
                description=(
                    "Default base+quote selection returns a non-empty "
                    "matrix with every requested pair represented (or warned)."
                ),
                inputs={
                    "bases": ["USD", "EUR", "GBP"],
                    "quotes": ["USD", "EUR", "GBP", "JPY"],
                },
                assertions=[
                    "rows_non_empty",
                    "matrix_keys_match_bases",
                    "self_pairs_excluded",
                ],
            ),
            SemanticTest(
                name="wcrs_missing_pair_warns_not_zeros",
                description="A pair missing from the provider yields a warning, not rate=0.",
                inputs={"_mock": "one_pair_missing"},
                assertions=[
                    "warning_mentions_missing_pair",
                    "no_synthetic_zero_rate",
                ],
            ),
        ],
    )


__all__ = ["wcrs"]
