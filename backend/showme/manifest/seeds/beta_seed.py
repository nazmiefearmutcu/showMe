"""BETA — CAPM Beta vs benchmark.

Daily-return regression of target vs benchmark over multiple lookback
windows. Beta uses the textbook CAPM formula β = Cov(R_i, R_m) / Var(R_m);
both inputs come from yfinance bulk-history pulls so the function is purely
computed at the handler.
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
def beta() -> FunctionManifest:
    return FunctionManifest(
        code="BETA",
        name="CAPM Beta",
        category=Category.EQUITIES,
        intent=(
            "Estimate CAPM beta of one instrument versus a benchmark, across one or more "
            "lookback windows, using daily-return regression."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF, AssetClass.INDEX],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Target instrument.",
            ),
            InputSpec(
                name="benchmark",
                label="Benchmark",
                control=ControlKind.BENCHMARK_PICKER,
                required=True,
                description="Market proxy (default ^GSPC).",
            ),
            InputSpec(
                name="beta_window",
                label="Lookback window",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Days of daily returns used to estimate β.",
                options=["60d", "126d", "252d", "504d", "756d"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "benchmark": "^GSPC",
            "beta_window": "252d",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "benchmark", "beta", "window", "n_observations", "assumptions"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="window", label="Window", kind="text"),
                ColumnSpec(key="beta", label="β", kind="number", format="%.4f"),
                ColumnSpec(key="alpha", label="α (daily)", kind="number", format="%.4f"),
                ColumnSpec(key="r_squared", label="R²", kind="percent", format="%.2f"),
                ColumnSpec(key="n", label="N", kind="number"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="beta", label="β", kind="big_number"),
                CardSlot(key="benchmark", label="Benchmark", kind="badge"),
                CardSlot(key="r_squared", label="R²", kind="kpi", unit="%"),
                CardSlot(key="n_observations", label="N", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BETA pulls aligned daily-close series for target + benchmark from yfinance over the "
            "requested window, drops NaN rows, computes log returns, and runs OLS R_i = α + β R_m "
            "+ ε. β = Cov(R_i, R_m) / Var(R_m); alpha is the daily intercept and R² the regression "
            "fit. The handler runs the regression independently for each requested window so the "
            "frame shows beta term structure. Assumptions (benchmark, window) are echoed in the "
            "payload so the consumer can audit which β it is reading."
        ),
        formula_dict={
            "Beta": Formula(
                expression=r"\beta = \frac{Cov(R_i, R_m)}{Var(R_m)}",
                variables={
                    "R_i": "Target asset daily returns",
                    "R_m": "Benchmark daily returns",
                },
                notes="CAPM textbook beta from daily log returns.",
            ),
            "RSquared": Formula(
                expression=r"R^2 = 1 - \frac{SS_{res}}{SS_{tot}}",
                variables={"SS_res": "Residual sum of squares", "SS_tot": "Total sum of squares"},
            ),
        },
        field_dict={
            "symbol": FieldDef(description="Target ticker.", source="instrument"),
            "benchmark": FieldDef(description="Benchmark ticker.", source="input"),
            "beta": FieldDef(description="OLS regression slope.", source="computed"),
            "alpha": FieldDef(description="OLS regression intercept (daily).", source="computed"),
            "r_squared": FieldDef(unit="decimal", description="Regression goodness-of-fit.", source="computed"),
            "n_observations": FieldDef(description="Aligned daily-return observations.", source="computed"),
            "assumptions": FieldDef(description="Inputs echoed back (benchmark, beta_window).", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="beta_aapl_vs_gspc_returns_finite_beta",
                description="BETA for AAPL vs ^GSPC over 252d returns a finite β plus R² > 0.",
                inputs={"symbol": "AAPL", "benchmark": "^GSPC", "beta_window": "252d"},
                assertions=[
                    "beta_is_finite_number",
                    "r_squared_between_0_and_1",
                    "n_observations_at_least_200",
                ],
            ),
            SemanticTest(
                name="beta_assumptions_visible_in_output",
                description="The output echoes the benchmark + window inputs so the consumer can audit which β it read.",
                inputs={"symbol": "MSFT", "benchmark": "^GSPC", "beta_window": "126d"},
                assertions=[
                    "assumptions_visible_in_output",
                    "assumptions_benchmark_equals_input",
                    "assumptions_window_equals_input",
                ],
            ),
            SemanticTest(
                name="beta_provider_outage_does_not_fabricate_beta",
                description="When the upstream history fails, status=provider_unavailable; beta is null not stubbed.",
                inputs={"symbol": "ZZZZZZ", "benchmark": "^GSPC", "beta_window": "252d"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "beta_is_null",
                    "next_actions_non_empty",
                ],
            ),
        ],
    )


__all__ = ["beta"]
