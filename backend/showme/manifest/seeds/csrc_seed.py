"""CSRC — Crypto screener.

Crypto analogue of EQS. Filter USDT-quoted (or per-quote) crypto
universe by 24h volume, market cap rank, distance from ATH/ATL,
funding rate, open interest, and category. Backend handler is
``engine/functions/screening/csrc.py`` which uses Binance for live
quotes/volume and CoinGecko for reference metadata (market cap, ATH,
algo, genesis).
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
def csrc() -> FunctionManifest:
    return FunctionManifest(
        code="CSRC",
        name="Crypto Screener",
        category=Category.SCREENING,
        intent=(
            "Filter the live crypto universe by 24h volume, market-cap rank, distance from ATH/ATL, "
            "and category so an operator can rank tradable coins instead of staring at the full 5,000+ "
            "list. Routes live volume to Binance and reference metadata to CoinGecko."
        ),
        asset_classes=[AssetClass.CRYPTO],
        inputs=[
            InputSpec(
                name="quote_currency",
                label="Quote",
                control=ControlKind.SELECT,
                required=True,
                description="Restrict to one quote currency (USDT-only is the default to skip stablecoins).",
                options=["USDT", "USDC", "BUSD", "BTC", "ETH"],
            ),
            InputSpec(
                name="min_volume_usd_24h",
                label="Min 24h vol",
                control=ControlKind.NUMBER,
                required=True,
                description="Floor on USD-equivalent 24h trading volume.",
                min=0,
                max=1_000_000_000,
                step=100_000,
                unit="USD",
            ),
            InputSpec(
                name="max_market_cap_rank",
                label="Max rank",
                control=ControlKind.NUMBER,
                required=False,
                description="Restrict to coins ranked at or above this market-cap rank.",
                min=1,
                max=5000,
                step=1,
            ),
            InputSpec(
                name="ath_distance_min_pct",
                label="ATH dist ≥",
                control=ControlKind.NUMBER,
                required=False,
                description="Only include coins whose drawdown from ATH is at least this percent.",
                min=0,
                max=100,
                step=1,
                unit="%",
            ),
            InputSpec(
                name="categories",
                label="Categories",
                control=ControlKind.MULTISELECT,
                required=False,
                description="CoinGecko categories (l1, defi, l2, gaming, meme, …) to restrict to.",
                options=["l1", "l2", "defi", "gaming", "ai", "meme", "infrastructure", "rwa", "depin"],
            ),
            InputSpec(
                name="saved_screen",
                label="Saved screen",
                control=ControlKind.SELECT,
                required=False,
                description="Load a previously saved crypto screen.",
                options=["TOP100-VOL", "L1-MAJORS", "ATH-DRAWDOWN", "MEME-SCAN"],
            ),
            InputSpec(
                name="limit",
                label="Row limit",
                control=ControlKind.SELECT,
                required=True,
                description="Cap on matched-row results.",
                options=[25, 50, 100, 250, 500],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "quote_currency": "USDT",
            "min_volume_usd_24h": 1_000_000,
            "max_market_cap_rank": 500,
            "ath_distance_min_pct": 0,
            "categories": [],
            "limit": 100,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            primary="binance",
            fallbacks=["coingecko", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "rows", "matched", "scanned", "quote_currency", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="rank", label="#", kind="number", format="%d"),
                ColumnSpec(key="last", label="Last", kind="currency", format="%.4f"),
                ColumnSpec(key="change_pct_24h", label="Δ 24h", kind="percent", format="%.2f"),
                ColumnSpec(key="volume_usd_24h", label="Vol 24h", kind="currency", format="si"),
                ColumnSpec(key="market_cap_usd", label="Mkt Cap", kind="currency", format="si"),
                ColumnSpec(key="ath_distance_pct", label="From ATH", kind="percent", format="%.2f"),
                ColumnSpec(key="category", label="Category", kind="tag"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="matched", label="Matched", kind="kpi"),
                CardSlot(key="scanned", label="Scanned", kind="kpi"),
                CardSlot(key="median_change_pct", label="Median Δ 24h", kind="trend_pill", unit="%"),
                CardSlot(key="top_category", label="Top Cat.", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "CSRC enumerates the Binance spot universe filtered by quote_currency (USDT default) and "
            "strips stablecoin bases via STABLECOIN_BASES. For each surviving symbol the live 24h "
            "ticker (last, change_pct_24h, volume) comes from Binance and the reference metadata "
            "(market_cap_usd, market_cap_rank, ath, atl, category) from CoinGecko's coin endpoint, "
            "cached in DuckDB for 5 minutes. Predicates min_volume_usd_24h, max_market_cap_rank, "
            "ath_distance_min_pct, and categories are applied; matches are sorted by volume_usd_24h "
            "desc by default. ath_distance_pct = (ath - last)/ath * 100. Saved screens are presets "
            "of (filters, sort). Next actions: save_screen, export_csv, open_in_gp."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Canonical Binance symbol (e.g. BTCUSDT).", source="binance"),
            "rows[].rank": FieldDef(unit="rank", description="CoinGecko market-cap rank.", source="coingecko"),
            "rows[].last": FieldDef(unit="quote_ccy", description="Last trade price in quote currency.", source="binance"),
            "rows[].change_pct_24h": FieldDef(unit="%", description="24h rolling change in percent.", source="binance"),
            "rows[].volume_usd_24h": FieldDef(unit="USD", description="USD-equivalent 24h volume.", source="binance"),
            "rows[].market_cap_usd": FieldDef(unit="USD", description="Circulating-supply market cap in USD.", source="coingecko"),
            "rows[].ath_distance_pct": FieldDef(unit="%", description="Percent below ATH (ATH - last)/ATH.", source="computed"),
            "rows[].category": FieldDef(description="CoinGecko category tag.", source="coingecko"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="csrc_quote_currency_usdt_filters_pairs",
                description="quote_currency=USDT yields only XYZUSDT pairs, never any *BTC quote.",
                inputs={"quote_currency": "USDT"},
                assertions=[
                    "every_symbol_ends_with_usdt",
                    "no_btc_quote_symbols",
                ],
            ),
            SemanticTest(
                name="csrc_stablecoin_bases_excluded",
                description="USDC, BUSD, DAI base symbols are not returned even when paired against USDT.",
                inputs={"quote_currency": "USDT"},
                assertions=[
                    "no_stablecoin_base_in_rows",
                ],
            ),
            SemanticTest(
                name="csrc_min_volume_filter_respected",
                description="Every returned row has volume_usd_24h >= min_volume_usd_24h.",
                inputs={"min_volume_usd_24h": 5_000_000},
                assertions=["all_rows_above_volume_floor"],
            ),
            SemanticTest(
                name="csrc_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="csrc_provider_unavailable_returns_empty_rows_not_synthetic",
                description="When Binance is unreachable, rows=[] and data_mode=provider_unavailable, no fabricated quotes.",
                inputs={},
                assertions=[
                    "rows_is_empty_array_on_provider_failure",
                    "data_mode_equals_provider_unavailable",
                    "no_synthetic_fields",
                ],
            ),
        ],
    )


__all__ = ["csrc"]
