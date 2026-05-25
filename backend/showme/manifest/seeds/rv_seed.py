"""RV — Relative Valuation vs peer set.

Compares an issuer to a peer group on the standard valuation ratios
(P/E, EV/EBITDA, P/S, P/B, dividend yield, FCF yield). Peers can be
operator-supplied or auto-resolved via finnhub peers. Renders KPIs (own
vs median) and a per-peer table.
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
def rv() -> FunctionManifest:
    return FunctionManifest(
        code="RV",
        name="Relative Valuation",
        category=Category.EQUITIES,
        intent=(
            "Compare an issuer to a peer set on the standard valuation ratios (P/E, EV/EBITDA, "
            "P/S, P/B, dividend yield, FCF yield) — own vs peer median."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Issuer ticker.",
            ),
            InputSpec(
                name="peers",
                label="Peers",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Peer tickers; auto-resolved via finnhub when empty.",
            ),
            InputSpec(
                name="ratios",
                label="Ratios",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict the table to a ratio subset.",
                options=["pe_ttm", "ev_ebitda", "ps_ttm", "pb", "dividend_yield", "fcf_yield"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={"provider_mode": DataMode.DELAYED_REFERENCE.value},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["finnhub", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "peers", "metrics", "median"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="pe_ttm", label="P/E", kind="number", format="%.2f"),
                ColumnSpec(key="ev_ebitda", label="EV/EBITDA", kind="number", format="%.2f"),
                ColumnSpec(key="ps_ttm", label="P/S", kind="number", format="%.2f"),
                ColumnSpec(key="pb", label="P/B", kind="number", format="%.2f"),
                ColumnSpec(key="dividend_yield", label="Div yield", kind="percent", format="%.2f"),
                ColumnSpec(key="fcf_yield", label="FCF yield", kind="percent", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="own_pe_ttm", label="Own P/E", kind="big_number"),
                CardSlot(key="peer_median_pe_ttm", label="Peer median P/E", kind="kpi"),
                CardSlot(key="pe_vs_peer_pct", label="P/E vs peers", kind="trend_pill", unit="%"),
                CardSlot(key="peer_count", label="Peers", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "RV resolves the peer set (operator-supplied or finnhub peers), pulls trailing-12-month "
            "fundamentals and the latest snapshot price for each, and computes the six standard "
            "ratios per row. Peer median is the row-wise median (NaN-safe). 'P/E vs peers' is the "
            "percentage premium / discount of own P/E to peer median. Ratios filter is applied "
            "server-side. When fewer than three peers resolve, the function still returns own "
            "ratios with a warning that the peer median is unreliable."
        ),
        formula_dict={
            "PE_TTM": Formula(
                expression=r"P/E_{TTM} = \frac{Price}{EPS_{TTM}}",
                variables={"Price": "Last close", "EPS_TTM": "Trailing 12-month EPS"},
            ),
            "EV_EBITDA": Formula(
                expression=r"EV/EBITDA = \frac{MarketCap + Debt - Cash}{EBITDA_{TTM}}",
                variables={"EBITDA_TTM": "Trailing 12-month EBITDA"},
            ),
            "FCFYield": Formula(
                expression=r"FCF\_yield = \frac{FCF_{TTM}}{MarketCap}",
                variables={"FCF_TTM": "CFO − |Capex| trailing 12 months"},
            ),
            "PeerMedian": Formula(
                expression=r"median(ratio_{peers})",
                variables={},
                notes="NaN-safe row-wise median across the peer set.",
            ),
        },
        field_dict={
            "symbol": FieldDef(description="Issuer ticker.", source="instrument"),
            "peers": FieldDef(description="Resolved peer ticker list.", source="provider"),
            "metrics": FieldDef(description="Per-symbol ratio rows (issuer + peers).", source="computed"),
            "median": FieldDef(description="Peer-only median for each ratio.", source="computed"),
            "pe_vs_peer_pct": FieldDef(unit="%", description="Premium / discount of own P/E vs peer median.", source="computed"),
            "peer_count": FieldDef(description="Number of resolved peers.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="rv_aapl_default_peers_returns_metrics",
                description="RV for AAPL with auto-resolved peers returns metrics + median rows.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_ok_set",
                    "metrics_non_empty",
                    "median_non_empty",
                ],
            ),
            SemanticTest(
                name="rv_low_peer_count_warns",
                description="When fewer than 3 peers resolve, the response includes a warning.",
                inputs={"symbol": "AAPL", "peers": ["MSFT"]},
                assertions=[
                    "warnings_non_empty",
                ],
            ),
            SemanticTest(
                name="rv_provider_outage_returns_unavailable",
                description="When yfinance + finnhub both fail, status=provider_unavailable; no fake ratios.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "metrics_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["rv"]
