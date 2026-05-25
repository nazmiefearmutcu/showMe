"""PORT — Canonical Portfolio Workspace.

Encodes ``docs/rebuild/manifests/wave1/PORT.md`` verbatim. The single
source of truth for what the user owns across every connected account.
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
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def port() -> FunctionManifest:
    return FunctionManifest(
        code="PORT",
        name="Portfolio Workspace",
        category=Category.PORTFOLIO,
        intent=(
            "The single source of truth for what you own across all connected "
            "accounts — positions, cost basis, PnL, cash, exposure, and live "
            "quote overlays that reconcile against the ledger."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.FUTURE,
            AssetClass.OPTION,
        ],
        inputs=[
            InputSpec(
                name="accounts",
                label="Accounts",
                control=ControlKind.MULTISELECT,
                required=False,
                description=(
                    "Filter to specific connected accounts; ALL aggregates "
                    "across the credential vault."
                ),
            ),
            InputSpec(
                name="as_of",
                label="As of",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Snapshot date; default = live.",
            ),
            InputSpec(
                name="group_by",
                label="Group by",
                control=ControlKind.SELECT,
                required=True,
                description="Roll-up dimension for the positions table.",
                options=["account", "asset_class", "sector", "currency", "none"],
            ),
            InputSpec(
                name="show_zero",
                label="Show closed positions",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Include positions with qty=0 (history).",
            ),
            InputSpec(
                name="ccy",
                label="Base currency",
                control=ControlKind.SELECT,
                required=True,
                description="Reporting currency used for totals + conversions.",
                options=["USD", "EUR", "GBP", "TRY", "JPY"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "accounts": ["ALL"],
            "group_by": "asset_class",
            "show_zero": False,
            "ccy": "USD",
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            primary="ccxt_broker",
            fallbacks=["binance", "yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=30,
            scope="per_input",
            persist=True,
        ),
        output_contract=OutputContract(
            must_have=["as_of", "ccy", "totals", "groups", "positions", "data_mode"],
            rows=False,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_LINE,
            x_axis=AxisSpec(type="time", unit="ms", label=""),
            y_axis=AxisSpec(type="numeric", unit="ccy", label="Equity"),
            panes=[],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="account", label="Account", kind="tag"),
                ColumnSpec(key="qty", label="Qty", kind="number", unit="shares/coins", format="%.6g"),
                ColumnSpec(key="avg_cost", label="Avg Cost", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="last", label="Last", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="market_value", label="Mkt Value", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="weight", label="Weight", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="unrealized", label="Unrealized", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="unrealized_pct", label="Unrealized %", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="day_change", label="Day Δ", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="day_change_pct", label="Day Δ%", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="asset_class", label="Class", kind="tag"),
                ColumnSpec(key="as_of", label="As of", kind="datetime"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_equity", label="Total Equity", kind="big_number", unit="ccy"),
                CardSlot(key="cash", label="Cash", kind="kpi", unit="ccy"),
                CardSlot(key="day_pnl", label="Day PnL", kind="trend_pill", unit="ccy"),
                CardSlot(key="unrealized_pnl", label="Unrealized", kind="trend_pill", unit="ccy"),
                CardSlot(key="realized_pnl_ytd", label="Realized YTD", kind="kpi", unit="ccy"),
                CardSlot(key="equity_in_pos", label="In Position", kind="kpi", unit="%"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
            ],
        ),
        methodology=(
            "PORT aggregates positions across all enabled credentials in the "
            "exchange vault. For each credential it fetches live positions via "
            "the broker's account() and positions() calls, joins with live "
            "quotes from the appropriate market data adapter, and computes "
            "market_value = qty * last, unrealized = (last - avg_cost) * qty "
            "(sign-aware for shorts), unrealized_pct = unrealized / "
            "(avg_cost * |qty|) * 100, day_change = (last - prev_close) * qty, "
            "and weight = market_value / total_market_value * 100. Currency "
            "conversion uses the FX adapter (cached intraday). Equity curve is "
            "reconstructed from snapshot history in DuckDB (one snapshot per "
            "minute when the sidecar is running). Realized PnL YTD is summed "
            "from broker transaction history (fetched on first load, cached, "
            "incrementally updated). Reconciliation diffs between broker "
            "equity and computed market_value are surfaced as warnings — never "
            "silently absorbed."
        ),
        formula_dict={
            "MarketValue": Formula(
                expression="mv = qty * last_price",
                variables={"qty": "Position size", "last_price": "Last traded price"},
            ),
            "Unrealized": Formula(
                expression="u = (last - avg_cost) * qty",
                variables={"last": "Last", "avg_cost": "Avg cost", "qty": "Sign-aware for short"},
            ),
            "Weight": Formula(
                expression=r"w = mv / \sum_i mv_i \times 100",
                variables={"mv": "Position market value", "mv_i": "Per-position MV"},
            ),
            "DayChange": Formula(
                expression="dc = (last - prev_close) * qty",
                variables={"prev_close": "Previous session close"},
            ),
            "Exposure": Formula(
                expression=r"exposure = \sum |mv_{position}| / total\_equity",
                variables={"total_equity": "Cash + Σ position MV"},
            ),
        },
        field_dict={
            "positions[].qty": FieldDef(unit="base", description="Position size in base currency.", source="broker"),
            "positions[].avg_cost": FieldDef(unit="quote", description="Volume-weighted average cost.", source="broker"),
            "positions[].last": FieldDef(unit="quote", description="Last traded price.", source="market adapter"),
            "totals.total_equity": FieldDef(unit="ccy", description="Cash + Σ position market values, converted to base ccy.", source="computed"),
            "totals.day_pnl": FieldDef(unit="ccy", description="Σ position day_change, sign-aware.", source="computed"),
            "equity_curve[].t": FieldDef(unit="epoch ms", description="Snapshot time.", source="snapshot store"),
            "equity_curve[].equity": FieldDef(unit="ccy", description="Equity at that snapshot.", source="snapshot store"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[
                "equity_drawdown_pct",
                "position_unrealized_loss_pct",
                "cash_below",
                "concentration_above",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="port_zero_credentials_returns_empty_with_explanation",
                description="No credentials in vault.",
                inputs={"accounts": ["ALL"]},
                assertions=[
                    "totals.total_equity == 0",
                    "positions == []",
                    "warnings includes 'no credentials configured'",
                    "data_mode == 'not_configured'",
                ],
            ),
            SemanticTest(
                name="port_one_credential_aggregates_correctly",
                description="Mock one credential with two positions.",
                inputs={"accounts": ["mock_credential_1"]},
                assertions=[
                    "totals == sum_of_positions",
                    "weights_sum_to_100_pct",
                    "day_pnl == sum_of_position_day_change",
                ],
            ),
            SemanticTest(
                name="port_currency_conversion_round_trip",
                description="Mock EUR-denominated position with USD base ccy.",
                inputs={"ccy": "USD"},
                assertions=[
                    "market_value_usd == qty * last * fx_rate",
                    "fx_rate_provenance_recorded",
                ],
            ),
            SemanticTest(
                name="port_reconciliation_diff_surfaced",
                description="Broker reports equity that disagrees by 0.5% from computed market_value.",
                inputs={},
                assertions=["warnings_contains_reconciliation_diff"],
            ),
            SemanticTest(
                name="port_equity_curve_monotonic_time",
                description="Equity curve timestamps are strictly increasing.",
                inputs={},
                assertions=["equity_curve_timestamps_strictly_increasing"],
            ),
            SemanticTest(
                name="port_no_silent_zero_qty_positions_when_show_zero_false",
                description="No rows with qty==0 unless show_zero is true.",
                inputs={"show_zero": False},
                assertions=["no_zero_qty_rows"],
            ),
        ],
    )


__all__ = ["port"]
