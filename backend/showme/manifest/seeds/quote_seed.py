"""QUOTE — Live last-price service + minimal display.

Backend service backed by ``showme.quotes.fetch_quote_snapshot`` and
``server_routes/quote.py:/api/quote/{symbol}``. Primarily a service that
WATCH / GP / HP consume via useLiveQuote, but pinnable as a card-only
pane (no chart, no rows) so an operator can park a focused tile on one
symbol.
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
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def quote() -> FunctionManifest:
    return FunctionManifest(
        code="QUOTE",
        name="Live Quote",
        category=Category.CHARTS_TECH,
        intent=(
            "Provide a small, reliable last-price snapshot for one instrument — the canonical "
            "service WATCH/GP/HP consume, and a card-only pane for parking a focused tile."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.FUTURE,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Canonical security identifier; routed to binance for crypto, yfinance otherwise.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            primary="binance",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        # quote_cache_get uses a 5s TTL for crypto and 15s for equity in
        # showme.quotes. We use the equity ceiling as the manifest-level
        # promise so callers know the max staleness window.
        caching=CachingPolicy(ttl_seconds=15, scope="per_input", persist=False),
        # Reflects the envelope from server_routes/quote.py:_build_quote_envelope
        # — ok + data + cache_hit + data_state + transport_state + freshness_ms
        # are the contract fields a consumer can rely on.
        output_contract=OutputContract(
            must_have=[
                "ok",
                "data",
                "cache_hit",
                "data_state",
                "transport_state",
                "freshness_ms",
            ],
            rows=False,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        chart_grammar=None,
        table_schema=None,
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbol", label="Symbol", kind="badge"),
                CardSlot(key="last", label="Last", kind="big_number", unit="quote_ccy"),
                CardSlot(key="change", label="Change", kind="trend_pill", unit="quote_ccy"),
                CardSlot(key="change_pct", label="Change %", kind="trend_pill", unit="%"),
                CardSlot(key="data_state", label="State", kind="mode_pill"),
                CardSlot(key="transport_state", label="Transport", kind="mode_pill"),
                CardSlot(key="freshness_ms", label="Freshness", kind="kpi", unit="ms"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "QUOTE is a deliberately small service. The HTTP route /api/quote/{symbol} is the only "
            "boundary: it consults a process-local TTL cache (5s crypto, 15s equity) so N concurrent "
            "panes share one upstream call, then on miss invokes fetch_quote_snapshot which routes to "
            "binance for crypto symbols and yfinance for everything else. The S07 response envelope "
            "carries truthful UI metadata — cache_hit, data_state (ok/stale/unavailable), "
            "transport_state (snapshot/offline), freshness_ms, source_kind, degraded, synthetic — so "
            "consumers can render live vs cached vs failed state without guessing. The pane form uses "
            "the same /api/quote endpoint and renders a card-only tile (no chart, no rows)."
        ),
        formula_dict={
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{last - prev\_close}{prev\_close} \times 100",
                variables={"last": "Latest price", "prev_close": "Previous close"},
            ),
        },
        field_dict={
            "ok": FieldDef(description="True when the upstream call succeeded.", source="envelope"),
            "data.symbol": FieldDef(description="Canonical symbol echoed back.", source="provider"),
            "data.last": FieldDef(unit="quote_ccy", description="Last trade price.", source="provider"),
            "data.prev_close": FieldDef(unit="quote_ccy", description="Previous close.", source="provider"),
            "data.change": FieldDef(unit="quote_ccy", description="last - prev_close.", source="computed"),
            "data.change_pct": FieldDef(unit="%", description="change / prev_close * 100.", source="computed"),
            "cache_hit": FieldDef(description="True when served from the TTL cache instead of upstream.", source="envelope"),
            "data_state": FieldDef(description="ok | stale | unavailable.", source="envelope"),
            "transport_state": FieldDef(description="snapshot | offline.", source="envelope"),
            "freshness_ms": FieldDef(unit="ms", description="Age of the cached payload; 0 on a fresh upstream call.", source="envelope"),
            "source_kind": FieldDef(description="Which adapter produced the snapshot (binance / yfinance / coingecko).", source="envelope"),
            "degraded": FieldDef(description="True when ok=False or a fallback was used.", source="envelope"),
            "synthetic": FieldDef(description="True only when the payload is a synthesized placeholder.", source="envelope"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["price_above", "price_below", "change_pct_above", "change_pct_below"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="quote_aapl_returns_envelope_with_last",
                description="QUOTE for AAPL returns ok=True with a numeric last and data_state=ok.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "ok_is_true",
                    "data_last_is_positive_number",
                    "data_state_equals_ok",
                    "transport_state_equals_snapshot",
                ],
            ),
            SemanticTest(
                name="quote_btcusdt_routes_to_binance",
                description="QUOTE for BTCUSDT sources from binance and reports source_kind=binance.",
                inputs={"symbol": "BTCUSDT"},
                assertions=[
                    "source_kind_equals_binance",
                    "data_last_is_positive_number",
                ],
            ),
            SemanticTest(
                name="quote_second_call_within_ttl_returns_cache_hit",
                description="Two calls for the same symbol within the TTL window: second carries cache_hit=True and freshness_ms>0.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "second_call_cache_hit_is_true",
                    "second_call_freshness_ms_greater_than_zero",
                ],
            ),
            SemanticTest(
                name="quote_failure_returns_envelope_not_throw",
                description="A failing upstream returns ok=False with data_state=unavailable; UI can render OFFLINE.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "ok_is_false",
                    "data_state_equals_unavailable",
                    "transport_state_equals_offline",
                    "degraded_is_true",
                    "synthetic_is_false",
                ],
            ),
        ],
    )


__all__ = ["quote"]
