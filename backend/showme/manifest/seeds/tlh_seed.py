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
            "Scan tax lots for harvest candidates: lots currently at a "
            "loss that are NOT inside a wash-sale window. Produces a "
            "ranked candidate list with harvestable loss, replacement-"
            "symbol suggestion, and explicit wash-sale-rule compliance flag."
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
                ColumnSpec(key="lot_id", label="Lot", kind="text"),
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="qty", label="Qty", kind="number", format="%.6g"),
                ColumnSpec(key="acquired_at", label="Acquired", kind="date"),
                ColumnSpec(key="harvestable_loss", label="Loss", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="term", label="Term", kind="tag"),
                ColumnSpec(key="wash_sale_safe", label="Wash-safe?", kind="tag"),
                ColumnSpec(key="wash_sale_reason", label="Reason", kind="text"),
                ColumnSpec(key="suggested_replacement", label="Replace w/", kind="text"),
                ColumnSpec(key="rank", label="Rank", kind="number", format="%d"),
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
            "TLH reads the LOTS inventory for the chosen credential, then "
            "for each open lot whose unrealized < -min_loss_threshold, "
            "applies the wash-sale check: scan the broker transaction "
            "history for a buy of the same (or substantially identical) "
            "symbol within ±wash_sale_window_days of today. If any such "
            "buy exists, wash_sale_safe=false and a wash_sale_reason "
            "names the blocking transaction. The lot is still listed so "
            "the user understands the constraint. For wash-safe lots, "
            "harvestable_loss is reported and (optional) "
            "suggested_replacement names a non-substantially-identical "
            "ETF/symbol to preserve exposure. The "
            "wash_sale_rule_respected top-level boolean MUST be true on "
            "every response — the manifest semantic test pins this. TLH "
            "is research-only; it never submits trades. The user must "
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
            "candidates[]": FieldDef(description="Ranked candidate lots with wash-sale check applied.", source="computed"),
            "total_harvestable_loss": FieldDef(unit="ccy", description="Σ harvestable_loss across wash-safe candidates.", source="computed"),
            "wash_sale_rule_respected": FieldDef(description="Always true — semantic-test enforced.", source="invariant"),
            "candidates[].wash_sale_safe": FieldDef(description="False when a buy inside the window blocks the harvest.", source="computed"),
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
                name="tlh_wash_sale_rule_respected",
                description="Every response must carry wash_sale_rule_respected=true.",
                inputs={},
                assertions=["wash_sale_rule_respected == True"],
            ),
            SemanticTest(
                name="tlh_paper_mode_defaults_true",
                description="TLH ships paper-safe.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="tlh_wash_sale_window_buy_blocks_candidate",
                description="Lot with a buy of same symbol 15d ago has wash_sale_safe=false.",
                inputs={"wash_sale_window_days": 30},
                assertions=[
                    "candidate.wash_sale_safe == False",
                    "wash_sale_reason names blocking buy",
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
                description="total_harvestable_loss is the sum across wash-safe candidates.",
                inputs={},
                assertions=["total_harvestable_loss == sum(safe_candidate_losses)"],
            ),
        ],
    )


__all__ = ["tlh"]
