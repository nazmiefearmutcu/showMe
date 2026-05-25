"""DDIS — Debt Distribution by Maturity (issuer debt ladder).

Buckets an issuer's outstanding debt principal by remaining maturity and
renders it as a bar ladder (0-1Y / 1-3Y / 3-5Y / 5Y+) with the share of
total visible debt. Without a filings/debt-schedule adapter the rows are
explicitly labelled as an ``illustrative_model`` so the pane never sells
template data as live issuer numbers.
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
def ddis() -> FunctionManifest:
    return FunctionManifest(
        code="DDIS",
        name="Debt Distribution by Maturity",
        category=Category.BONDS_RATES,
        intent=(
            "Bucket an issuer's outstanding debt principal by remaining maturity"
            " (0-1Y / 1-3Y / 3-5Y / 5Y+) and surface the share of total visible"
            " debt so the operator can see refinancing concentration."
        ),
        asset_classes=[AssetClass.BOND, AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="issuer",
                label="Issuer",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Issuer symbol or company name; defaults to the active instrument.",
            ),
            InputSpec(
                name="currency",
                label="Reporting currency",
                control=ControlKind.SELECT,
                required=False,
                description="Currency used to express principal amounts.",
                options=["USD", "EUR", "GBP", "JPY", "TRY"],
            ),
            InputSpec(
                name="maturities",
                label="Maturities (manual)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description=(
                    "Optional user-supplied debt schedule (list of"
                    " {bucket, tenor_years, amount_usd_bn, currency, pct}) used when"
                    " a live filings feed is not connected."
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
            "currency": "USD",
            "provider_mode": DataMode.MODELED.value,
        },
        provider_chain=ProviderChain(
            primary="sec_edgar",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
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
            x_axis=AxisSpec(type="category", label="Maturity bucket"),
            y_axis=AxisSpec(type="numeric", unit="USD bn", label="Principal"),
            panes=[
                PaneGrammar(name="ladder", series_kind="bar", height_pct=100),
            ],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="bucket", label="Bucket", kind="tag", width_hint=84),
                ColumnSpec(key="tenor_years", label="Tenor", kind="number", format="%.2f", unit="years"),
                ColumnSpec(key="amount_usd_bn", label="Amount", kind="currency", unit="USD bn", format="%.2f"),
                ColumnSpec(key="currency", label="Ccy", kind="tag", width_hint=64),
                ColumnSpec(key="pct", label="Share", kind="percent", unit="%", format="%.1f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_debt_usd_bn", label="Total", kind="big_number", unit="USD bn"),
                CardSlot(key="near_term_share", label="0-1Y %", kind="kpi", unit="%"),
                CardSlot(key="long_term_share", label="5Y+ %", kind="kpi", unit="%"),
                CardSlot(key="bucket_count", label="Buckets", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DDIS buckets the issuer's outstanding debt principal by remaining maturity. When the"
            " caller supplies an explicit ``maturities`` schedule the pane returns it verbatim and"
            " marks the response ``source_mode=user_input``. With no schedule and no live filings"
            " adapter the pane returns a four-bucket illustrative model (0-1Y / 1-3Y / 3-5Y / 5Y+)"
            " marked ``source_mode=illustrative_model`` — labelled, never disguised as a live read."
            " Share % is computed client-side as amount_usd_bn / total × 100 so the ladder bars stay"
            " consistent with the table even when filters trim rows."
        ),
        formula_dict={
            "bucket_share": Formula(
                expression=r"share_i = \frac{amount_i}{\sum_j amount_j} \times 100",
                variables={"amount_i": "Principal in bucket i", "amount_j": "Principal in bucket j"},
                notes="Share of total visible debt; recomputed on filter changes.",
            ),
        },
        field_dict={
            "rows[].bucket": FieldDef(description="Remaining-maturity bucket label.", source="catalog"),
            "rows[].tenor_years": FieldDef(unit="years", description="Representative tenor for chart ordering.", source="catalog"),
            "rows[].amount_usd_bn": FieldDef(unit="USD bn", description="Principal amount in USD billions.", source="filings_or_user"),
            "rows[].currency": FieldDef(description="Currency of the underlying issuance.", source="filings_or_user"),
            "rows[].pct": FieldDef(unit="%", description="Share of total visible debt schedule.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["near_term_share_above", "long_term_share_below"],
            delivery=["log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="ddis_share_pct_sums_to_one_hundred",
                description="Per-row pct values must sum to 100 ± 0.5 across the visible rows.",
                inputs={"issuer": "AAPL"},
                assertions=["sum_pct_within_99_5_and_100_5"],
            ),
            SemanticTest(
                name="ddis_illustrative_model_is_labelled",
                description=(
                    "With no live adapter and no user-supplied maturities, rows are returned with"
                    " source_mode=illustrative_model and a warning flagging the model fallback."
                ),
                inputs={"issuer": "GENERIC_ISSUER"},
                assertions=[
                    "source_mode_equals_illustrative_model",
                    "warning_mentions_illustrative_or_model",
                ],
            ),
            SemanticTest(
                name="ddis_user_supplied_maturities_pass_through",
                description="When ``maturities`` is supplied the rows pass through verbatim and source_mode=user_input.",
                inputs={"issuer": "AAPL", "maturities": [{"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": 1.0, "currency": "USD", "pct": 100.0}]},
                assertions=[
                    "rows_length_equals_supplied",
                    "source_mode_equals_user_input",
                ],
            ),
            SemanticTest(
                name="ddis_chart_grammar_is_bar_ladder",
                description="chart_grammar.kind is bar_ladder so the renderer draws an ordered bucket ladder.",
                inputs={},
                assertions=["chart_grammar_kind_is_bar_ladder"],
            ),
        ],
    )


__all__ = ["ddis"]
