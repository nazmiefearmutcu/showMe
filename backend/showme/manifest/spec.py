"""Pydantic v2 models for the FunctionManifest contract.

This is the single source of truth driving backend handlers, frontend
controls, tests, and docs. The shape mirrors the canonical schema spec
verbatim — a parallel TypeScript port lives alongside the frontend.

All models use strict mode (``extra="forbid"``) so a typo at registration
time is caught loudly instead of silently dropped.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


class InputSpec(BaseModel):
    """One ordered control spec for the function panel."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="snake_case input id")
    label: str = Field(..., description="Human label (TR or EN, default EN)")
    control: ControlKind
    required: bool
    description: str
    options: list[Any] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class ProviderChain(BaseModel):
    """Primary + ordered fallback adapters for data resolution."""

    model_config = ConfigDict(extra="forbid")

    primary: str = Field(..., description="provider key in providers/registry.py")
    fallbacks: list[str] = Field(default_factory=list)
    acceptable_modes: list[DataMode]


class CachingPolicy(BaseModel):
    """TTL + scope + persistence policy for cached payloads."""

    model_config = ConfigDict(extra="forbid")

    ttl_seconds: int = Field(..., ge=0, description="0 disables caching")
    scope: Literal["per_input", "global"]
    persist: bool = Field(..., description="true = duckdb-backed, false = in-process")


class OutputContract(BaseModel):
    """Promise about which payload arrays/fields the handler will populate."""

    model_config = ConfigDict(extra="forbid")

    must_have: list[str] = Field(
        default_factory=list,
        description="Fields that MUST be present and non-empty for status=ok",
    )
    rows: bool = False
    series: bool = False
    cards: bool = False
    warnings: bool = True
    next_actions: bool = False


class AxisSpec(BaseModel):
    """One axis description on a chart."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["time", "category", "numeric"]
    unit: str | None = None
    label: str | None = None


class PaneGrammar(BaseModel):
    """One pane in a multi-pane chart (e.g. price + volume + indicator)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    series_kind: Literal["candle", "line", "bar", "area", "histogram"]
    height_pct: int = Field(..., ge=1, le=100)


class ChartGrammar(BaseModel):
    """How a function should render its chart, if any."""

    model_config = ConfigDict(extra="forbid")

    kind: ChartKind
    x_axis: AxisSpec
    y_axis: AxisSpec | list[AxisSpec]
    panes: list[PaneGrammar] = Field(default_factory=list)
    overlay_support: bool = False
    compare_support: bool = False


class ColumnSpec(BaseModel):
    """One column in a `TableSchema`."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    kind: Literal[
        "text",
        "number",
        "percent",
        "currency",
        "date",
        "datetime",
        "duration",
        "tag",
        "action",
    ]
    unit: str | None = None
    format: str | None = None
    width_hint: int | None = None


class TableSchema(BaseModel):
    """How tabular payload rows are presented."""

    model_config = ConfigDict(extra="forbid")

    columns: list[ColumnSpec]
    sortable: bool = True
    filterable: bool = True


class CardSlot(BaseModel):
    """One slot on a `CardSchema`."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    kind: Literal[
        "kpi",
        "big_number",
        "trend_pill",
        "mode_pill",
        "timestamp",
        "badge",
    ]
    unit: str | None = None


class CardSchema(BaseModel):
    """How summary cards are structured."""

    model_config = ConfigDict(extra="forbid")

    slots: list[CardSlot]


class Formula(BaseModel):
    """One named formula with its expression and variable glossary."""

    model_config = ConfigDict(extra="forbid")

    expression: str = Field(..., description="LaTeX or plain math")
    variables: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None


class FieldDef(BaseModel):
    """One named field with its unit, description, and source adapter."""

    model_config = ConfigDict(extra="forbid")

    unit: str | None = None
    description: str
    source: str | None = None


class ProvenanceSpec(BaseModel):
    """Required source-labeling for the function's output payload."""

    model_config = ConfigDict(extra="forbid")

    require_source_list: bool = True
    require_as_of: bool = True
    require_latency_ms: bool = True


class AlertingSpec(BaseModel):
    """Supported alerting conditions and their delivery channels."""

    model_config = ConfigDict(extra="forbid")

    conditions: list[str] = Field(default_factory=list)
    delivery: list[Literal["tray", "notification", "log"]] = Field(default_factory=list)


class SemanticTest(BaseModel):
    """Named semantic test — proves the function does its labelled job."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    assertions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level manifest
# ---------------------------------------------------------------------------


class FunctionManifest(BaseModel):
    """Canonical contract for one showMe function code."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        ...,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        description="uppercase function code, e.g. GP or PORT_OPT",
    )
    name: str
    category: Category
    intent: str = Field(..., description="one-sentence professional intent")
    asset_classes: list[AssetClass] = Field(default_factory=list)
    inputs: list[InputSpec] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    provider_chain: ProviderChain
    caching: CachingPolicy
    output_contract: OutputContract
    chart_grammar: ChartGrammar | None = None
    table_schema: TableSchema | None = None
    card_schema: CardSchema | None = None
    methodology: str
    formula_dict: dict[str, Formula] = Field(default_factory=dict)
    field_dict: dict[str, FieldDef] = Field(default_factory=dict)
    provenance: ProvenanceSpec
    alerting: AlertingSpec | None = None
    semantic_tests: list[SemanticTest] = Field(default_factory=list, min_length=1)


__all__ = [
    "AlertingSpec",
    "AxisSpec",
    "CachingPolicy",
    "CardSchema",
    "CardSlot",
    "ChartGrammar",
    "ColumnSpec",
    "FieldDef",
    "Formula",
    "FunctionManifest",
    "InputSpec",
    "OutputContract",
    "PaneGrammar",
    "ProvenanceSpec",
    "ProviderChain",
    "SemanticTest",
    "TableSchema",
]
