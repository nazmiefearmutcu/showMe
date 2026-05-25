"""WHAL — Whale wallet / large-flow tracker.

WHAL surfaces large trades / large transfers for a symbol or wallet.
The existing backend handler (engine/functions/misc/whal.py) stitches
Binance aggregate trades + Yahoo chart + SEC EDGAR as a market-flow
proxy; a true native wallet-label feed requires an Etherscan / Whale
Alert key. Without that key, the chain runs in NOT_CONFIGURED mode for
the wallet-transfer column and only shows the public proxy rows — never
pretends a transfer feed is live.
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
def whal() -> FunctionManifest:
    return FunctionManifest(
        code="WHAL",
        name="Whale Flow Monitor",
        category=Category.MISC,
        intent=(
            "Cross-market whale / large-flow monitor that stitches public market data as a "
            "proxy (Binance trades, Yahoo chart, SEC EDGAR) and honestly declares the native "
            "wallet-label transfer feed unavailable when no on-chain provider key is configured."
        ),
        asset_classes=[
            AssetClass.CRYPTO,
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.FX,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Instrument or token to monitor.",
            ),
            InputSpec(
                name="market",
                label="Market",
                control=ControlKind.SELECT,
                required=True,
                description="Asset class bucket.",
                options=["CRYPTO", "EQUITY", "ETF", "FX"],
            ),
            InputSpec(
                name="threshold_usd",
                label="Threshold (USD)",
                control=ControlKind.NUMBER,
                required=True,
                description="Minimum USD value for a row to count as a whale event.",
                min=10_000,
                step=10_000,
            ),
            InputSpec(
                name="lookback_hours",
                label="Lookback",
                control=ControlKind.SELECT,
                required=True,
                description="Window in hours.",
                options=["1", "6", "24", "72"],
            ),
        ],
        defaults={
            "market": "CRYPTO",
            "threshold_usd": 1_000_000,
            "lookback_hours": "24",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["binance", "yfinance", "sec_edgar", "cached_snapshot"],
            acceptable_modes=[
                DataMode.NOT_CONFIGURED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.DELAYED_REFERENCE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=30, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["rows", "provider", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="timestamp", label="When", kind="datetime", format="rel"),
                ColumnSpec(key="alert_type", label="Type", kind="tag"),
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="venue", label="Venue", kind="tag"),
                ColumnSpec(key="direction", label="Side", kind="tag"),
                ColumnSpec(key="usd_value", label="USD value", kind="currency", format="%.2f"),
                ColumnSpec(key="threshold_crossed", label="Crossed", kind="tag"),
                ColumnSpec(key="severity", label="Severity", kind="tag"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="provider", label="Provider", kind="badge"),
                CardSlot(key="rows_count", label="Alerts", kind="kpi"),
                CardSlot(key="threshold_hits", label="Crossed", kind="kpi"),
                CardSlot(key="native_transfer_feed", label="Transfer feed", kind="mode_pill"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "WHAL is a public-data proxy for whale activity. The handler routes by market: "
            "CRYPTO buckets call Binance aggTrades for the last lookback_hours and flag rows "
            "where usd_value >= threshold_usd; EQUITY/ETF buckets call Yahoo chart for "
            "volume-impulse rows and SEC EDGAR for 13F/8-K headline mentions. A true native "
            "wallet-transfer feed (Etherscan, Whale Alert) is opt-in: when no key is configured "
            "the `native_transfer_feed` card reads 'not_configured' and the proxy notice in the "
            "pane spells out that these are market-flow proxies, not licensed tape prints. "
            "Without any provider available, rows=[] with an explicit 'provider not configured' warning."
        ),
        field_dict={
            "rows[].timestamp": FieldDef(unit="iso8601", description="Event time.", source="provider"),
            "rows[].alert_type": FieldDef(description="large_trade | large_volume | sec_filing | top_holder.", source="classifier"),
            "rows[].usd_value": FieldDef(unit="USD", description="USD notional of the event.", source="computed"),
            "rows[].threshold_crossed": FieldDef(description="True when usd_value >= threshold_usd.", source="computed"),
            "rows[].severity": FieldDef(description="low | medium | high | critical.", source="heuristic"),
            "rows[].source_mode": FieldDef(description="binance_agg | yahoo_chart | sec_edgar | etherscan.", source="provider"),
            "native_transfer_feed": FieldDef(description="not_configured when no etherscan/whale-alert key.", source="envelope"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["threshold_crossed", "severity_critical", "sec_filing_for_symbol"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="whal_btcusdt_proxy_rows_have_real_timestamps",
                description="WHAL for BTCUSDT returns rows with monotonic timestamps inside the lookback window and usd_value numeric.",
                inputs={"symbol": "BTCUSDT", "market": "CRYPTO", "threshold_usd": 1_000_000, "lookback_hours": "24"},
                assertions=[
                    "every_row_has_timestamp",
                    "every_timestamp_within_lookback",
                    "every_row_usd_value_is_numeric",
                ],
            ),
            SemanticTest(
                name="whal_native_transfer_feed_unavailable_when_not_configured",
                description="With no etherscan / whale-alert key, native_transfer_feed reports 'not_configured' and only the public proxy rows are returned — no fake wallet-label transfer rows.",
                inputs={"_env": "no_etherscan_key"},
                assertions=[
                    "native_transfer_feed_equals_not_configured",
                    "no_rows_with_source_mode_etherscan",
                    "proxy_disclosure_present",
                ],
            ),
            SemanticTest(
                name="whal_threshold_filter_is_honest",
                description="Rows with usd_value < threshold_usd have threshold_crossed=False; rows >= threshold have True. No silent flag flipping.",
                inputs={"symbol": "BTCUSDT", "threshold_usd": 5_000_000},
                assertions=[
                    "below_threshold_rows_crossed_false",
                    "above_threshold_rows_crossed_true",
                ],
            ),
            SemanticTest(
                name="whal_explicit_unavailable_when_all_providers_down",
                description="If every public proxy errors and no native key is configured, rows=[] with data_mode='not_configured' and a warning naming each failed provider — no synthetic placeholders.",
                inputs={"_env": "all_providers_down"},
                assertions=[
                    "rows_is_empty_array",
                    "data_mode_equals_not_configured",
                    "warning_lists_failed_providers",
                    "no_synthetic_rows",
                ],
            ),
        ],
    )


__all__ = ["whal"]
