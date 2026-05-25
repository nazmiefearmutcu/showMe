"""EXEC — Live VWAP/TWAP execution monitor.

Slice-by-slice fill-quality + pace tracker for parent orders. Handler is
``engine/functions/trade/exec.py:EXECFunction`` which exposes actions
{open, slice, close, get, list} against the ``exec_monitor`` service.
EXEC consumes live broker fills (``LIVE_EXCHANGE``) and supplements with
cached snapshots when the venue's market-data feed lags.
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
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
    ChartKind,
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
def exec_() -> FunctionManifest:
    return FunctionManifest(
        code="EXEC",
        name="Execution Monitor",
        category=Category.TRADE_EXECUTION,
        intent=(
            "Track parent-order execution slice-by-slice: pace vs schedule, slippage vs benchmark, "
            "implementation shortfall, and venue fill quality for VWAP/TWAP/POV algos."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.FUTURE,
        ],
        inputs=[
            InputSpec(
                name="action",
                label="Action",
                control=ControlKind.SELECT,
                required=True,
                description="open = create parent; slice = record fill; close = finalize; get/list = read.",
                options=["list", "open", "slice", "close", "get"],
            ),
            InputSpec(
                name="parent_id",
                label="Parent ID",
                control=ControlKind.TEXT,
                required=False,
                description="Caller-assigned parent-order identifier; required for open/slice/close/get.",
                depends_on=["action"],
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Symbol traded by the parent; required when action=open.",
                depends_on=["action"],
            ),
            InputSpec(
                name="side",
                label="Side",
                control=ControlKind.SELECT,
                required=False,
                description="BUY or SELL; required when action=open.",
                options=["BUY", "SELL"],
                depends_on=["action"],
            ),
            InputSpec(
                name="target_qty",
                label="Target qty",
                control=ControlKind.NUMBER,
                required=False,
                description="Total quantity to execute; required when action=open.",
                min=0.0,
                step=0.001,
                depends_on=["action"],
            ),
            InputSpec(
                name="arrival_price",
                label="Arrival price",
                control=ControlKind.NUMBER,
                required=False,
                description="Mid at parent-order arrival; reference for implementation-shortfall calc.",
                min=0.0,
                step=0.0001,
            ),
            InputSpec(
                name="algo",
                label="Algo",
                control=ControlKind.SELECT,
                required=False,
                description="Execution algo tag for the parent.",
                options=["VWAP", "TWAP", "POV", "ARRIVAL", "MARKET"],
            ),
            InputSpec(
                name="horizon_seconds",
                label="Horizon",
                control=ControlKind.NUMBER,
                required=False,
                description="Schedule horizon in seconds for TWAP/VWAP pacing.",
                min=1.0,
                step=1.0,
                unit="s",
            ),
            InputSpec(
                name="slice_idx",
                label="Slice #",
                control=ControlKind.NUMBER,
                required=False,
                description="Index of the slice being recorded (action=slice).",
                min=0.0,
                step=1.0,
                depends_on=["action"],
            ),
            InputSpec(
                name="qty",
                label="Slice qty",
                control=ControlKind.NUMBER,
                required=False,
                description="Quantity filled by this slice; required when action=slice.",
                min=0.0,
                step=0.001,
                depends_on=["action"],
            ),
            InputSpec(
                name="avg_px",
                label="Slice avg price",
                control=ControlKind.NUMBER,
                required=False,
                description="Volume-weighted average price of this slice; required when action=slice.",
                min=0.0,
                step=0.0001,
                depends_on=["action"],
            ),
            InputSpec(
                name="benchmark_px",
                label="Benchmark price",
                control=ControlKind.NUMBER,
                required=False,
                description="Per-slice benchmark price (e.g. interval VWAP) for slippage compute.",
                min=0.0,
                step=0.0001,
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "action": "list",
            "algo": "TWAP",
            "horizon_seconds": 600,
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
        caching=CachingPolicy(ttl_seconds=2, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["status", "orders", "n"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_LINE,
            x_axis=AxisSpec(type="time", unit="ms", label=""),
            y_axis=[
                AxisSpec(type="numeric", unit="quote", label="Price"),
                AxisSpec(type="numeric", unit="bps", label="Slippage"),
            ],
            panes=[
                PaneGrammar(name="price", series_kind="line", height_pct=50),
                PaneGrammar(name="slippage", series_kind="bar", height_pct=25),
                PaneGrammar(name="pace", series_kind="area", height_pct=25),
            ],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="parent_id", label="Parent", kind="text"),
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="side", label="Side", kind="tag"),
                ColumnSpec(key="algo", label="Algo", kind="tag"),
                ColumnSpec(key="target_qty", label="Target", kind="number", format="%.4f"),
                ColumnSpec(key="filled_qty", label="Filled", kind="number", format="%.4f"),
                ColumnSpec(key="avg_fill_px", label="Avg Fill", kind="currency", unit="quote", format="%.4f"),
                ColumnSpec(key="arrival_price", label="Arrival", kind="currency", unit="quote", format="%.4f"),
                ColumnSpec(key="is_bps", label="IS bps", kind="number", format="%.1f"),
                ColumnSpec(key="pace_pct", label="Pace %", kind="percent", unit="%", format="%.1f"),
                ColumnSpec(key="status", label="Status", kind="tag"),
                ColumnSpec(key="opened_at", label="Opened", kind="datetime"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="open_parents", label="Open", kind="kpi"),
                CardSlot(key="needs_close", label="Needs Close", kind="kpi"),
                CardSlot(key="avg_is_bps", label="Avg IS bps", kind="kpi", unit="bps"),
                CardSlot(key="worst_slippage_bps", label="Worst Slip bps", kind="kpi", unit="bps"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "EXEC is the slice-by-slice execution monitor for parent orders. action=open creates a "
            "parent row with target_qty + arrival_price + algo + horizon; action=slice appends fill "
            "events with qty, avg_px, and an optional per-slice benchmark; action=close finalises. "
            "Per-slice slippage is computed as (avg_px − benchmark_px)/benchmark_px × 10_000 in bps; "
            "implementation shortfall against arrival is (avg_fill − arrival)/arrival × 10_000 × side_sign. "
            "Pace = filled_qty / scheduled_qty where scheduled_qty for TWAP is target × elapsed_s/horizon_s "
            "(and target × cumulative_volume_fraction for VWAP). Orphan slices against unknown parent_ids "
            "are refused (HTTP-style unknown_parent status) — recording them would corrupt every joined "
            "metric. The persisted exec_monitor store survives sidecar restarts so live parents are not lost."
        ),
        formula_dict={
            "ImplementationShortfall": Formula(
                expression=r"IS_{bps} = \frac{avg\_fill - arrival}{arrival} \times 10000 \times sign(side)",
                variables={
                    "avg_fill": "Quantity-weighted average fill price of the parent",
                    "arrival": "Mid at arrival",
                    "sign(side)": "+1 for BUY, -1 for SELL",
                },
            ),
            "Slippage": Formula(
                expression=r"slip_{bps} = \frac{avg\_px - benchmark\_px}{benchmark\_px} \times 10000",
                variables={"benchmark_px": "Per-slice interval VWAP or arrival"},
            ),
            "Pace": Formula(
                expression=r"pace_{pct} = \frac{filled\_qty}{scheduled\_qty}",
                variables={"scheduled_qty": "TWAP/VWAP target by current time"},
            ),
        },
        field_dict={
            "orders[].parent_id": FieldDef(description="Caller-assigned parent identifier.", source="exec_monitor"),
            "orders[].algo": FieldDef(description="Algo tag (TWAP/VWAP/POV/ARRIVAL/MARKET).", source="exec_monitor"),
            "orders[].target_qty": FieldDef(unit="base", description="Total quantity to execute.", source="exec_monitor"),
            "orders[].filled_qty": FieldDef(unit="base", description="Cumulative quantity filled.", source="exec_monitor"),
            "orders[].avg_fill_px": FieldDef(unit="quote", description="VWAP of fills.", source="computed"),
            "orders[].arrival_price": FieldDef(unit="quote", description="Mid at parent arrival.", source="exec_monitor"),
            "orders[].is_bps": FieldDef(unit="bps", description="Implementation shortfall vs arrival.", source="computed"),
            "orders[].pace_pct": FieldDef(unit="%", description="Filled vs schedule.", source="computed"),
            "orders[].status": FieldDef(description="live / filled_not_closed / complete.", source="exec_monitor"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[
                "pace_below_schedule",
                "slippage_bps_above",
                "is_bps_above",
                "parent_filled_not_closed",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="exec_list_empty_returns_empty_status",
                description="EXEC with no parents in the store returns status=empty and orders=[].",
                inputs={"action": "list"},
                assertions=[
                    "status == 'empty'",
                    "orders == []",
                    "n == 0",
                ],
            ),
            SemanticTest(
                name="exec_orphan_slice_refused",
                description="action=slice against an unknown parent_id returns status=unknown_parent without writing.",
                inputs={"action": "slice", "parent_id": "ghost", "slice_idx": 0, "qty": 1, "avg_px": 100},
                assertions=[
                    "status == 'unknown_parent'",
                    "no_slice_persisted",
                ],
            ),
            SemanticTest(
                name="exec_open_missing_fields_returns_invalid_request",
                description="action=open without parent_id/symbol/side/target_qty returns invalid_request with missing_fields.",
                inputs={"action": "open"},
                assertions=[
                    "status == 'invalid_request'",
                    "missing_fields_non_empty",
                ],
            ),
            SemanticTest(
                name="exec_filled_not_closed_flagged_for_close",
                description="A parent whose cumulative slice qty reaches target_qty but was never closed reports status=needs_close.",
                inputs={"action": "list"},
                assertions=["status == 'needs_close' when any parent is filled_not_closed"],
            ),
        ],
    )


__all__ = ["exec_"]
