"""ONCH — On-chain analytics (general).

ONCH summarises on-chain activity (active addresses, fees, gas, large
transfers) for a target chain or token. The pane is intentionally
auth-free by default: without an Etherscan / Glassnode / Dune API key
configured, the chain runs in NOT_CONFIGURED mode and renders an
explicit unavailable card — it never fabricates address counts or fee
trends.
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
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def onch() -> FunctionManifest:
    return FunctionManifest(
        code="ONCH",
        name="On-Chain Analytics",
        category=Category.MISC,
        intent=(
            "Summarise on-chain activity (active addresses, fees, gas, large transfers) for a "
            "target chain or token; honestly declares unavailable when no provider key is configured."
        ),
        asset_classes=[AssetClass.CRYPTO],
        inputs=[
            InputSpec(
                name="chain",
                label="Chain",
                control=ControlKind.SELECT,
                required=True,
                description="Target chain.",
                options=["ethereum", "bitcoin", "solana", "polygon", "arbitrum", "base"],
            ),
            InputSpec(
                name="metric",
                label="Metric",
                control=ControlKind.SELECT,
                required=True,
                description="Primary on-chain metric to focus on.",
                options=["active_addresses", "transactions", "fees_usd", "gas_gwei", "large_transfers"],
            ),
            InputSpec(
                name="window",
                label="Window",
                control=ControlKind.SELECT,
                required=True,
                description="Lookback window.",
                options=["1h", "24h", "7d", "30d"],
            ),
        ],
        defaults={
            "chain": "ethereum",
            "metric": "active_addresses",
            "window": "24h",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.NOT_CONFIGURED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="time_utc", label="Time", kind="datetime", format="yyyy-MM-dd HH:mm"),
                ColumnSpec(key="metric", label="Metric", kind="tag"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.4f"),
                ColumnSpec(key="unit", label="Unit", kind="tag"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="chain", label="Chain", kind="badge"),
                CardSlot(key="metric", label="Metric", kind="badge"),
                CardSlot(key="latest", label="Latest", kind="big_number"),
                CardSlot(key="change_pct", label="Δ window", kind="trend_pill", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ONCH expects an explicit on-chain provider key (etherscan / glassnode / dune) in "
            "the keyring before any chain is queried. With no key configured the handler returns "
            "data_mode='not_configured' with rows=[] and a card-level 'Provider not configured' "
            "notice — no fabricated address counts, no fake fee curves, no synthetic gas trend. "
            "When a key is present, the chain runs in delayed-reference mode (TTL 5 min) and the "
            "rows array carries one observation per bucket inside the requested window."
        ),
        field_dict={
            "data_mode": FieldDef(description="not_configured | cached_snapshot | delayed_reference.", source="envelope"),
            "rows[].time_utc": FieldDef(unit="UTC", description="Bucket timestamp.", source="provider"),
            "rows[].metric": FieldDef(description="Metric name echoed back.", source="provider"),
            "rows[].value": FieldDef(description="Numeric metric value.", source="provider"),
            "rows[].unit": FieldDef(description="Metric unit (addresses / txns / usd / gwei).", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="onch_explicit_unavailable_when_no_onchain_provider",
                description="With no etherscan / glassnode / dune key in the keyring, ONCH returns data_mode='not_configured' with rows=[] and a 'provider not configured' warning — never a synthetic series.",
                inputs={"_env": "no_onchain_keys"},
                assertions=[
                    "data_mode_equals_not_configured",
                    "rows_is_empty_array",
                    "warning_mentions_not_configured",
                    "no_synthetic_placeholder_values",
                ],
            ),
            SemanticTest(
                name="onch_ethereum_active_addresses_24h_basic_shape",
                description="With a configured provider, eth/active_addresses/24h returns rows where every entry has time_utc, value, unit='addresses'.",
                inputs={"chain": "ethereum", "metric": "active_addresses", "window": "24h"},
                assertions=[
                    "every_row_has_time_utc",
                    "every_row_value_is_numeric",
                    "every_row_unit_equals_addresses",
                ],
            ),
            SemanticTest(
                name="onch_no_synthetic_fill_on_provider_error",
                description="If the configured provider errors mid-fetch, rows truncate to the successful range and the warning explains the failure — no zero-padding, no last-value carry-forward.",
                inputs={"_mock": "provider_error_partial"},
                assertions=[
                    "no_zero_padded_rows",
                    "warning_describes_provider_error",
                ],
            ),
        ],
    )


__all__ = ["onch"]
