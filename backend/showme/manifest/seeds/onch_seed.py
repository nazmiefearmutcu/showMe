"""ONCH — On-Chain Metrics (Bitcoin network vitals, keyless).

ONCH serves a live Bitcoin network snapshot from keyless public APIs only:
mempool.space (recommended fees, projected mempool blocks, mempool backlog,
difficulty adjustment, 3-day hashrate, chain tip) and CoinGecko global market
context. Optional keyless companion tiers (DefiLlama chain TVL, Blockscout
Ethereum gas and ETH spot) add rows only when they answer. No API key is
needed and nothing is fabricated: an upstream outage is reported as
``provider_unavailable`` and a chain other than Bitcoin is an input error.
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
        name="On-Chain Metrics",
        category=Category.MISC,
        intent=(
            "Bitcoin network vitals (fees, mempool backlog, hashrate, difficulty, chain tip) "
            "with CoinGecko market context, from keyless public APIs; an outage is reported "
            "honestly as provider_unavailable."
        ),
        asset_classes=[AssetClass.CRYPTO],
        inputs=[
            InputSpec(
                name="chain",
                label="Chain",
                control=ControlKind.SELECT,
                required=False,
                description="Chain served by the keyless vitals. Only Bitcoin is served.",
                options=["BTC"],
            ),
        ],
        defaults={"chain": "BTC"},
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["mempool", "coingecko", "defillama", "blockscout"],
            acceptable_modes=[
                DataMode.PROVIDER_UNAVAILABLE,
                # Listed for the optional-provider rule. The keyless path never
                # emits it: no key is required, so "not configured" cannot occur.
                DataMode.NOT_CONFIGURED,
            ],
        ),
        # The handler keeps no cache; the pane polls on its own interval.
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=False),
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
                ColumnSpec(key="metric", label="Metric", kind="tag"),
                ColumnSpec(key="value", label="Value", kind="text"),
                ColumnSpec(key="unit", label="Unit", kind="tag"),
                ColumnSpec(key="source", label="Source", kind="tag"),
                ColumnSpec(key="context", label="Context", kind="text"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="chain", label="Chain", kind="badge"),
                CardSlot(key="mempool", label="Mempool", kind="big_number"),
                CardSlot(key="fastest_fee", label="Fastest fee", kind="kpi"),
                CardSlot(key="hashrate", label="Hashrate", kind="kpi"),
                CardSlot(key="difficulty", label="Difficulty", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ONCH fetches Bitcoin on-chain network vitals live from mempool.space: recommended "
            "fees, the mempool-wide unconfirmed transaction count (/api/mempool), the projected "
            "next blocks (reported as their own transaction sum), difficulty adjustment, 3-day "
            "hashrate and the chain tip. CoinGecko global data adds BTC dominance, total market "
            "capitalisation and 24h volume. Optional keyless tiers add DefiLlama Ethereum TVL and "
            "Blockscout Ethereum gas and ETH spot. Each row carries its own source; a tier that "
            "does not answer adds no row. No API key is used and no value is estimated or "
            "carried forward. On an upstream outage the response is status and data_mode "
            "provider_unavailable with empty rows and a warning. A chain other than BTC returns "
            "status input_error. The keyless path never returns data_mode not_configured."
        ),
        field_dict={
            "status": FieldDef(description="ok | provider_unavailable | input_error.", source="envelope"),
            "data_mode": FieldDef(description="live (rows fetched in this call) | provider_unavailable | explicit_unavailable.", source="envelope"),
            "as_of": FieldDef(unit="UTC", description="Time the request was sent; the vitals were read at or after this time.", source="envelope"),
            "rows[].metric": FieldDef(description="Metric name.", source="provider"),
            "rows[].value": FieldDef(description="Formatted live value; em dash when the provider omitted it.", source="provider"),
            "rows[].unit": FieldDef(description="Unit of the value (sat/vB, EH/s, T, tx, %, USD, gwei).", source="provider"),
            "rows[].source": FieldDef(description="Provider the row came from (mempool / coingecko / defillama / blockscout).", source="provider"),
            "rows[].context": FieldDef(description="Short interpretation or provenance for the value.", source="provider"),
            "series[].bucket": FieldDef(description="Projected block index (Block +N).", source="provider"),
            "series[].count": FieldDef(unit="tx", description="Transaction count projected into that block.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="onch_explicit_provider_unavailable_on_upstream_outage",
                description="When mempool.space cannot be reached, ONCH returns status and data_mode provider_unavailable with rows=[] and a warning naming the failed fetch — never a synthetic vitals row.",
                inputs={"_mock": "upstream_outage"},
                assertions=[
                    "data_mode_equals_provider_unavailable",
                    "rows_is_empty_array",
                    "warning_describes_fetch_failure",
                    "no_synthetic_placeholder_values",
                ],
            ),
            SemanticTest(
                name="onch_mempool_backlog_is_mempool_wide_count",
                description="Mempool Backlog equals the unconfirmed count reported by /api/mempool; the projected-block transaction sum is a separate row labelled as the projected window.",
                inputs={"_mock": "mempool_count"},
                assertions=[
                    "mempool_backlog_equals_api_mempool_count",
                    "projected_block_sum_labelled_separately",
                ],
            ),
            SemanticTest(
                name="onch_live_rows_carry_source_and_mode",
                description="A successful call returns data_mode live and every row names a keyless provider that actually answered.",
                inputs={"chain": "BTC"},
                assertions=[
                    "data_mode_equals_live",
                    "every_row_source_in_keyless_provider_set",
                    "payload_has_as_of",
                ],
            ),
            SemanticTest(
                name="onch_unsupported_chain_is_input_error",
                description="A chain other than BTC returns status input_error with rows=[] and makes no upstream call.",
                inputs={"chain": "ETH"},
                assertions=[
                    "status_equals_input_error",
                    "rows_is_empty_array",
                    "no_upstream_call",
                ],
            ),
        ],
    )


__all__ = ["onch"]
