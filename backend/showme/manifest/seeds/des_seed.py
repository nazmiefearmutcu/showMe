"""DES — Description / company profile.

Equity + ETF + FUND + REIT take the equity refdata path (yfinance ->
finnhub -> sec); CRYPTO takes the CoinGecko refdata path. Fields are
flattened by ``_promote_raw_fields`` in
``engine/functions/equity/des.py`` so the UI gets a stable shape.
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
def des() -> FunctionManifest:
    return FunctionManifest(
        code="DES",
        name="Description",
        category=Category.EQUITIES,
        intent=(
            "Show a one-screen company profile (sector/industry/market-cap/HQ/IPO/summary) "
            "for equities and the equivalent token profile (rank/algo/supply/ATH/ATL) for crypto."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker (AAPL), ETF (SPY), or crypto base (BTC).",
            ),
            InputSpec(
                name="refdata_timeout",
                label="Provider timeout (s)",
                control=ControlKind.NUMBER,
                required=False,
                description="Per-provider latency budget; clamped 1..4 seconds server-side.",
                min=1,
                max=4,
                step=0.5,
                unit="s",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "refdata_timeout": 2.5,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["openfigi", "sec_edgar", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=86400, scope="per_input", persist=True),
        # Reflects the actual DES payload shape (engine/functions/equity/des.py).
        # ``status`` and ``symbol`` are always present; ``name`` is the canonical
        # display label; ``rows`` is the UI-friendly row list built by
        # _build_rows().
        output_contract=OutputContract(
            must_have=["symbol", "status", "rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="label", label="Field", kind="text"),
                ColumnSpec(key="value", label="Value", kind="text"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbol", label="Symbol", kind="big_number"),
                CardSlot(key="name", label="Name", kind="badge"),
                CardSlot(key="sector", label="Sector", kind="badge"),
                CardSlot(key="industry", label="Industry", kind="badge"),
                CardSlot(key="market_cap", label="Market Cap", kind="kpi", unit="quote_ccy"),
                CardSlot(key="employees", label="Employees", kind="kpi"),
                CardSlot(key="exchange_name", label="Exchange", kind="badge"),
                CardSlot(key="ipo_date", label="IPO", kind="timestamp"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DES walks an asset-class-aware provider chain: yfinance then finnhub then sec_edgar for "
            "equity/ETF, coingecko then cryptocompare then yfinance for crypto. The first non-None payload "
            "wins; CoinGecko's nested shape is rewritten to the shared DES wire schema via _coingecko_to_des "
            "so the UI never branches on provider. yfinance ``info`` is flattened by _promote_raw_fields "
            "(50KB+ raw blob stripped) and exchange codes are humanized via EXCHANGE_LEGEND. When every "
            "provider misses the latency budget, DES returns status=provider_unavailable with next_actions "
            "rather than fabricating a profile."
        ),
        field_dict={
            "symbol": FieldDef(description="Canonical ticker or crypto base.", source="instrument"),
            "name": FieldDef(description="Display name.", source="provider"),
            "asset_class": FieldDef(description="EQUITY / ETF / CRYPTO.", source="instrument"),
            "sector": FieldDef(description="GICS sector (equity).", source="provider"),
            "industry": FieldDef(description="GICS industry (equity).", source="provider"),
            "market_cap": FieldDef(unit="quote_ccy", description="Market capitalization.", source="provider"),
            "employees": FieldDef(unit="people", description="Full-time employees.", source="provider"),
            "exchange": FieldDef(description="Listing exchange code.", source="provider"),
            "exchange_name": FieldDef(description="Humanized exchange label.", source="EXCHANGE_LEGEND"),
            "currency": FieldDef(description="Reporting currency.", source="provider"),
            "country": FieldDef(description="HQ country.", source="provider"),
            "ipo_date": FieldDef(description="First-trade date (ISO).", source="provider"),
            "description": FieldDef(description="Business summary or token description.", source="provider"),
            "circulating_supply": FieldDef(unit="tokens", description="Crypto: circulating supply.", source="coingecko"),
            "max_supply": FieldDef(unit="tokens", description="Crypto: max supply.", source="coingecko"),
            "all_time_high": FieldDef(unit="quote_ccy", description="Crypto: ATH price.", source="coingecko"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="des_aapl_returns_real_profile",
                description="DES for AAPL returns sector/industry/market_cap from a refdata provider.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "symbol_equals_aapl",
                    "status_in_ok_set",
                    "sector_is_non_empty_string",
                    "market_cap_is_positive_number",
                    "rows_non_empty",
                ],
            ),
            SemanticTest(
                name="des_btc_routes_to_coingecko",
                description="DES for BTC takes the crypto refdata path and exposes circulating_supply.",
                inputs={"symbol": "BTC"},
                assertions=[
                    "asset_class_equals_crypto",
                    "circulating_supply_is_positive_number",
                    "all_time_high_is_positive_number",
                ],
            ),
            SemanticTest(
                name="des_provider_outage_does_not_fabricate_profile",
                description="When every provider misses the budget, DES returns provider_unavailable with next_actions, not a fake profile.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "next_actions_non_empty",
                    "no_synthetic_sector_or_market_cap",
                ],
            ),
        ],
    )


__all__ = ["des"]
