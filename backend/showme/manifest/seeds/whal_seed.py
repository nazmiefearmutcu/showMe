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
                description=(
                    "Window in hours. Equity/ETF/FX: Yahoo bars inside the window. Crypto: Binance "
                    "returns only the latest 1000 aggregate trades per venue, so the window holds "
                    "whatever those trades cover; the covered span is reported next to the lookback."
                ),
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
            fallbacks=["binance_spot", "binance_usd_m_futures", "yahoo_chart", "sec_edgar"],
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
            "WHAL is a public-data proxy for whale activity, routed by market. CRYPTO reads Binance "
            "public aggTrades (spot first, then USD-M futures): the latest 1000 trades per venue, "
            "kept when they fall inside lookback_hours. Those 1000 trades can cover only minutes, so "
            "the covered span is reported and a warning names any shortfall. With a USD threshold, "
            "rows are crypto_large_trade or are not listed; with a threshold of 0 they are crypto_trade "
            "and nothing is tested. EQUITY/ETF/REIT/FUND read Yahoo chart bars: large_volume_proxy rows "
            "carry a USD notional (volume x close) and are tested against threshold_usd; "
            "liquidity_impulse_proxy and top_impulse_window rows have no USD value, so they are rated "
            "from the move versus the recent median and are never tested against the threshold. "
            "top_volume_window is the largest-notional bar when nothing else qualifies. US tickers also "
            "list SEC EDGAR ownership filings (sec_ownership_filing) for Forms 3, 4, 5, 13D and 13G; "
            "these have no USD value and are not threshold-tested. FX and INDEX use Yahoo "
            "price-impulse proxies only. A true native wallet-transfer feed (Etherscan, Whale Alert) "
            "is opt-in: without a key the `native_transfer_feed` card reads 'not_configured'. The proxy "
            "notice in the pane spells out that these are market-flow proxies, not licensed tape prints. "
            "If no public source returns rows, status is provider_unavailable with a warning per failed provider."
        ),
        field_dict={
            "rows[].timestamp": FieldDef(unit="iso8601", description="Event time.", source="provider"),
            "rows[].alert_type": FieldDef(
                description=(
                    "crypto_large_trade | crypto_top_trade | crypto_trade | large_volume_proxy | "
                    "liquidity_impulse_proxy | top_volume_window | top_impulse_window | sec_ownership_filing."
                ),
                source="classifier",
            ),
            "rows[].usd_value": FieldDef(
                unit="USD",
                description="USD notional where the source supports it; null for SEC filings and price-impulse rows.",
                source="computed",
            ),
            "rows[].threshold_crossed": FieldDef(
                description="True/False only when usd_value and a positive threshold both exist; null when nothing was tested.",
                source="computed",
            ),
            "rows[].severity": FieldDef(
                description=(
                    "USD rows: low | medium | high | critical against the threshold, unrated at threshold 0. "
                    "No-USD price-impulse rows: low | medium | high from the move versus the recent median, or unrated."
                ),
                source="heuristic",
            ),
            "rows[].source_mode": FieldDef(
                description=(
                    "binance_spot_aggtrades | binance_usd_m_futures_aggtrades | yahoo_volume_notional_proxy | "
                    "yahoo_price_impulse_proxy | yahoo_chart_top_window | sec_edgar_submissions."
                ),
                source="provider",
            ),
            "window": FieldDef(
                description="lookback_hours requested next to covered_hours, the span the returned data really covers.",
                source="computed",
            ),
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
