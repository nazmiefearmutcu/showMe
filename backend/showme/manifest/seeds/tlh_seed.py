"""TLH — Tax-Loss Harvesting Candidates.

Scans LOTS for lots currently at a loss that are NOT inside a wash-sale
window (US default 30 days). Produces a candidate list with harvestable
loss, replacement-symbol suggestion, and an explicit wash-sale check
flag. Paper-safe by default — TLH never fires trades on its own.
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
def tlh() -> FunctionManifest:
    return FunctionManifest(
        code="TLH",
        name="Tax-Loss Harvesting",
        category=Category.PORTFOLIO,
        intent=(
            "Scan the local portfolio's positions for harvest candidates: "
            "positions currently at a loss. Produces a ranked candidate "
            "list with the gross estimated tax saving (netted against "
            "supplied realized gains when given), replacement-symbol "
            "suggestion, and a wash-sale status that is blocked only when "
            "the open date falls inside the window; otherwise it is "
            "reported as not checked."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
        ],
        inputs=[
            InputSpec(
                name="credential_id",
                label="Account",
                control=ControlKind.SELECT,
                required=True,
                description="Broker account whose lots to scan.",
            ),
            InputSpec(
                name="min_loss_threshold",
                label="Min harvestable loss",
                control=ControlKind.NUMBER,
                required=False,
                description="Don't list lots with smaller losses than this.",
                min=0,
                max=100000,
                step=10,
                unit="ccy",
            ),
            InputSpec(
                name="wash_sale_window_days",
                label="Wash-sale window",
                control=ControlKind.NUMBER,
                required=True,
                description=(
                    "Days before/after sale during which a substantially-"
                    "identical buy disqualifies the loss (US IRS default 30)."
                ),
                min=0,
                max=90,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="suggest_replacement",
                label="Suggest replacement",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Suggest a not-substantially-identical replacement to maintain exposure.",
            ),
            InputSpec(
                name="realized_st_gain",
                label="Realized short-term gain",
                control=ControlKind.NUMBER,
                required=False,
                description=(
                    "Realized short-term gain (native currency) to net harvested "
                    "losses against. Give both gain inputs to get a netted total; "
                    "otherwise savings are gross."
                ),
                unit="ccy",
            ),
            InputSpec(
                name="realized_lt_gain",
                label="Realized long-term gain",
                control=ControlKind.NUMBER,
                required=False,
                description=(
                    "Realized long-term gain (native currency) to net harvested "
                    "losses against. Give both gain inputs to get a netted total; "
                    "otherwise savings are gross."
                ),
                unit="ccy",
            ),
            InputSpec(
                name="ccy",
                label="Display currency",
                control=ControlKind.SELECT,
                required=False,
                description="Currency for harvestable-loss totals.",
                options=["native", "USD", "EUR", "GBP", "TRY", "JPY"],
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description=(
                    "Research-only by default. TLH never fires trades; "
                    "candidate list is preview-only. Hand-off to EMSX is "
                    "an explicit user action."
                ),
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; falls back to last broker snapshot.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "min_loss_threshold": 100,
            "wash_sale_window_days": 30,
            "suggest_replacement": True,
            "ccy": "native",
            "paper_mode": True,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["ccxt_broker", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "credential_id",
                "candidates",
                "total_harvestable_loss",
                "wash_sale_rule_respected",
                "data_mode",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="quantity", label="Qty", kind="number", format="%.6g"),
                ColumnSpec(key="opened_at", label="Opened", kind="date"),
                ColumnSpec(key="unrealized_pnl", label="Unrealized", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="estimated_tax_savings", label="Gross saving", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="wash_sale_status", label="Wash status", kind="tag"),
                ColumnSpec(key="wash_sale_reason", label="Reason", kind="text"),
                ColumnSpec(key="replacement_etf", label="Replace w/", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_harvestable_loss", label="Harvestable", kind="big_number", unit="ccy"),
                CardSlot(key="candidate_count", label="Candidates", kind="kpi"),
                CardSlot(key="st_loss", label="ST loss", kind="kpi", unit="ccy"),
                CardSlot(key="lt_loss", label="LT loss", kind="kpi", unit="ccy"),
                CardSlot(key="wash_blocked_count", label="Wash-blocked", kind="kpi"),
                CardSlot(key="paper_mode", label="Mode", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TLH reads the local portfolio positions (position-level, not "
            "tax lots; no broker account is used). For each position whose "
            "unrealized loss is at least min_loss_threshold (default 100, "
            "native currency), it reports the gross estimated saving "
            "(loss times the short- or long-term rate). When realized_st_gain "
            "and realized_lt_gain are both given, the total nets the "
            "non-blocked losses against those gains and applies the $3,000 "
            "ordinary-income offset; otherwise savings_basis says the total is "
            "a gross upper bound. Wash-sale: a position whose open date is "
            "inside ±wash_sale_window_days of today is blocked "
            "(wash_sale_safe=false, with wash_sale_reason naming that open "
            "date) and excluded from the total. Any other position is reported "
            "as not checked (wash_sale_safe=null): broker buy history is NOT "
            "read, so the absence of a block is not proof of safety. Because "
            "that check is not run, wash_sale_checked is false and "
            "wash_sale_rule_respected is null on every response. The "
            "suggested replacement_etf is a non-substantially-identical sector "
            "ETF. TLH is research-only; it never submits trades. The user must "
            "explicitly hand candidates off to EMSX with paper_mode=false."
        ),
        formula_dict={
            "HarvestableLoss": Formula(
                expression=r"loss = \max(0, basis - mv)",
                variables={"basis": "Cost basis", "mv": "Current market value"},
            ),
            "WashSaleWindow": Formula(
                expression=r"\text{disqualifies if } \exists buy_t : |t - sale| \leq W",
                variables={"W": "Wash-sale window in days"},
            ),
            "ShortTermFlag": Formula(
                expression=r"ST = holding\_days < threshold",
                variables={},
            ),
        },
        field_dict={
            "candidates[]": FieldDef(description="Ranked loss positions (position-level) with the wash-sale status applied.", source="computed"),
            "total_harvestable_loss": FieldDef(unit="ccy", description="Σ loss over non-blocked candidates (native currency).", source="computed"),
            "total_estimated_tax_savings": FieldDef(unit="ccy", description="Netted against supplied realized gains when savings_basis says so; otherwise a gross upper bound.", source="computed"),
            "wash_sale_rule_respected": FieldDef(description="Null: the buy-history wash-sale check is not run. Only blocked positions are reported.", source="computed"),
            "candidates[].wash_sale_safe": FieldDef(description="False when the open date is inside the window; null when not checked.", source="computed"),
            "candidates[].wash_sale_reason": FieldDef(description="Human-readable explanation of the wash-sale block.", source="computed"),
            "candidates[].suggested_replacement": FieldDef(description="Optional not-substantially-identical replacement.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="tlh_wash_sale_rule_not_claimed_unchecked",
                description="Without a buy-history check, the response must not claim the wash-sale rule was respected.",
                inputs={},
                assertions=["wash_sale_checked == False", "wash_sale_rule_respected is None"],
            ),
            SemanticTest(
                name="tlh_paper_mode_defaults_true",
                description="TLH ships paper-safe.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="tlh_wash_sale_window_buy_blocks_candidate",
                description="Position opened 15d ago (inside the 30d window) has wash_sale_safe=false and is excluded from the total.",
                inputs={"wash_sale_window_days": 30},
                assertions=[
                    "candidate.wash_sale_safe == False",
                    "wash_sale_reason names the open date inside the window",
                ],
            ),
            SemanticTest(
                name="tlh_below_threshold_excluded",
                description="Lot with loss < min_loss_threshold not in candidates.",
                inputs={"min_loss_threshold": 500},
                assertions=["no candidate with harvestable_loss < 500"],
            ),
            SemanticTest(
                name="tlh_total_equals_sum_safe_candidates",
                description="total_harvestable_loss is the sum across non-blocked candidates.",
                inputs={},
                assertions=["total_harvestable_loss == sum(non_blocked_candidate_losses)"],
            ),
        ],
    )


__all__ = ["tlh"]
