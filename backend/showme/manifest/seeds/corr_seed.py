"""CORR — Correlation Heatmap (real heatmap, not row-index plot).

Encodes ``docs/rebuild/manifests/wave1/CORR.md`` verbatim. The
heatmap-vs-row-index distinction is enforced by the test suite — see
``corr_chart_grammar_is_heatmap_not_row_index``.
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
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def corr() -> FunctionManifest:
    return FunctionManifest(
        code="CORR",
        name="Correlation Heatmap",
        category=Category.PORTFOLIO,
        intent=(
            "Show pairwise return correlations across a chosen universe over "
            "a chosen window with method controls (Pearson/Spearman/Kendall, "
            "return type, frequency, horizon) — visualized as an actual "
            "heatmap with an exportable correlation matrix."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Set of instruments to correlate (from WATCH, PORT, or custom).",
            ),
            InputSpec(
                name="method",
                label="Method",
                control=ControlKind.SELECT,
                required=True,
                description="Correlation kernel.",
                options=["pearson", "spearman", "kendall"],
            ),
            InputSpec(
                name="return_type",
                label="Returns",
                control=ControlKind.SELECT,
                required=True,
                description="Return definition.",
                options=["log", "simple"],
            ),
            InputSpec(
                name="frequency",
                label="Frequency",
                control=ControlKind.SELECT,
                required=True,
                description="Return sampling cadence.",
                options=["1h", "1d", "1wk", "1mo"],
            ),
            InputSpec(
                name="window",
                label="Window",
                control=ControlKind.SELECT,
                required=True,
                description="Lookback for the correlation computation.",
                options=["30d", "60d", "90d", "180d", "1Y", "2Y", "5Y"],
            ),
            InputSpec(
                name="min_overlap",
                label="Min observations",
                control=ControlKind.NUMBER,
                required=True,
                description="Reject pairs with fewer overlapping bars.",
                min=10,
                max=500,
                step=1,
                depends_on=["frequency"],
            ),
            InputSpec(
                name="as_of",
                label="As of",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Anchor date for the lookback window.",
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
            "universe": [],
            "method": "pearson",
            "return_type": "log",
            "frequency": "1d",
            "window": "90d",
            "min_overlap": 30,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="binance",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "symbols", "matrix", "method", "frequency", "window", "data_mode"],
            rows=False,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="category", unit="", label="Symbol"),
            y_axis=AxisSpec(type="category", unit="", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=None,
        card_schema=CardSchema(
            slots=[
                CardSlot(key="universe_size", label="N", kind="kpi"),
                CardSlot(key="highest_pair", label="Highest", kind="big_number", unit="ρ"),
                CardSlot(key="highest_pair_label", label="", kind="badge"),
                CardSlot(key="lowest_pair", label="Lowest", kind="big_number", unit="ρ"),
                CardSlot(key="lowest_pair_label", label="", kind="badge"),
                CardSlot(key="avg_abs_corr", label="Avg |ρ|", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "For each instrument in `universe`, CORR fetches close prices at "
            "`frequency` for the `window` ending at `as_of`. Returns are "
            "computed per `return_type`: log → r_t = ln(p_t / p_{t-1}); "
            "simple → r_t = (p_t - p_{t-1}) / p_{t-1}. The returns matrix is "
            "asof-aligned to a common time index. Pairs with fewer than "
            "`min_overlap` observations after alignment are rejected and "
            "surfaced as warnings. The correlation matrix is computed with "
            "the chosen `method` (Pearson product-moment; Spearman rank; "
            "Kendall τ). The output matrix is symmetric with 1.0 on the "
            "diagonal. Heatmap visualization uses a diverging color scale "
            "anchored at 0, deep red at -1 and deep blue at +1. This is "
            "explicitly NOT a row-index scatter — axes are universe symbols "
            "(categorical), not bar indices of the return series."
        ),
        formula_dict={
            "Pearson": Formula(
                expression=r"\rho(X,Y) = cov(X,Y) / (\sigma_X \sigma_Y)",
                variables={},
            ),
            "Spearman": Formula(
                expression=r"\rho_s = 1 - 6 \sum d^2_i / (n(n^2 - 1))",
                variables={"d_i": "Rank difference per observation"},
                notes="Rank correlation.",
            ),
            "Kendall_tau": Formula(
                expression=r"\tau = (n_c - n_d) / (n(n-1)/2)",
                variables={"n_c": "Concordant pairs", "n_d": "Discordant pairs"},
            ),
            "LogReturn": Formula(
                expression=r"r_t = \ln(p_t) - \ln(p_{t-1})",
                variables={},
            ),
            "AvgAbsRho": Formula(
                expression=r"(1 / (N(N-1))) \sum_{i \neq j} |\rho_{ij}|",
                variables={},
                notes="Exclude the diagonal.",
            ),
        },
        field_dict={
            "symbols": FieldDef(unit="", description="Ordered list of N symbols (matrix row/column labels).", source="input"),
            "matrix": FieldDef(unit="", description="N×N float; cell[i][j] = ρ(symbols[i], symbols[j]).", source="computed"),
            "pair_overlap[i][j]": FieldDef(unit="bars", description="Number of observations used for that pair.", source="derived"),
            "rejected_pairs": FieldDef(unit="", description="List of (i, j, reason).", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="corr_chart_grammar_is_heatmap_not_row_index",
                description="Manifest chart_grammar.kind == 'heatmap'; handler response includes a matrix field, not a row-index series.",
                inputs={},
                assertions=[
                    "manifest.chart_grammar.kind == 'heatmap'",
                    "response.matrix_present",
                    "response.no_row_index_series",
                ],
            ),
            SemanticTest(
                name="corr_diagonal_is_one",
                description="Any universe → matrix[i][i] == 1.0 ± 1e-12.",
                inputs={},
                assertions=["matrix_diagonal_is_one_within_tolerance"],
            ),
            SemanticTest(
                name="corr_symmetric",
                description="matrix[i][j] == matrix[j][i] for all i, j.",
                inputs={},
                assertions=["matrix_is_symmetric"],
            ),
            SemanticTest(
                name="corr_two_perfectly_correlated_returns_pearson_one",
                description="Mock universe [A, B] with B's returns == A's returns.",
                inputs={"universe": ["A", "B"], "method": "pearson"},
                assertions=["rho_A_B == 1.0 within 1e-9"],
            ),
            SemanticTest(
                name="corr_insufficient_overlap_rejected_with_warning",
                description="One symbol has only 5 observations and min_overlap=30.",
                inputs={"min_overlap": 30},
                assertions=[
                    "pair_in_rejected_pairs",
                    "warning_present",
                ],
            ),
            SemanticTest(
                name="corr_method_changes_result",
                description="Non-linear monotonic relationship → Pearson and Spearman yield materially different values.",
                inputs={},
                assertions=["abs(pearson - spearman) > tolerance"],
            ),
        ],
    )


__all__ = ["corr"]
