/**
 * FunctionManifest — TypeScript port of the canonical Pydantic v2 contract
 * at `backend/showme/manifest/spec.py`. The string enum values MUST match
 * the Python `str, Enum` members verbatim — they cross the wire as JSON.
 *
 * Anything optional on the Python side (`field: X | None = None`) is
 * represented here as `field?: X | null` so a `null` from the wire and an
 * absent field both round-trip cleanly.
 *
 * Strict mode — never reach for `any` here. `unknown` is the correct
 * exit hatch for free-form `defaults` / `inputs` payloads.
 */

// ---------------------------------------------------------------------------
// Enums (string unions — mirror Python's str-Enum members)
// ---------------------------------------------------------------------------

export type Category =
  | "portfolio"
  | "trade_execution"
  | "api_dev"
  | "bonds_rates"
  | "charts_tech"
  | "comms_people"
  | "commodities"
  | "derivatives"
  | "equities"
  | "fx"
  | "macro"
  | "news_intel"
  | "screening"
  | "misc";

export const CATEGORY_VALUES: readonly Category[] = [
  "portfolio",
  "trade_execution",
  "api_dev",
  "bonds_rates",
  "charts_tech",
  "comms_people",
  "commodities",
  "derivatives",
  "equities",
  "fx",
  "macro",
  "news_intel",
  "screening",
  "misc",
] as const;

export type AssetClass =
  | "equity"
  | "etf"
  | "crypto"
  | "fx"
  | "commodity"
  | "bond"
  | "rate"
  | "index"
  | "option"
  | "future";

export const ASSET_CLASS_VALUES: readonly AssetClass[] = [
  "equity",
  "etf",
  "crypto",
  "fx",
  "commodity",
  "bond",
  "rate",
  "index",
  "option",
  "future",
] as const;

export type DataMode =
  | "live_official"
  | "live_exchange"
  | "delayed_reference"
  | "modeled"
  | "cached_snapshot"
  | "provider_unavailable"
  | "not_configured";

export const DATA_MODE_VALUES: readonly DataMode[] = [
  "live_official",
  "live_exchange",
  "delayed_reference",
  "modeled",
  "cached_snapshot",
  "provider_unavailable",
  "not_configured",
] as const;

export type ControlKind =
  | "symbol_picker"
  | "benchmark_picker"
  | "date_range"
  | "horizon"
  | "scenario"
  | "provider_mode"
  | "number"
  | "text"
  | "select"
  | "multiselect"
  | "boolean"
  | "model_assumption"
  | "constraint_set";

export const CONTROL_KIND_VALUES: readonly ControlKind[] = [
  "symbol_picker",
  "benchmark_picker",
  "date_range",
  "horizon",
  "scenario",
  "provider_mode",
  "number",
  "text",
  "select",
  "multiselect",
  "boolean",
  "model_assumption",
  "constraint_set",
] as const;

export type ChartKind =
  | "time_series_line"
  | "time_series_candles"
  | "ohlcv"
  | "heatmap"
  | "surface"
  | "frontier"
  | "tenor_curve"
  | "depth_ladder"
  | "payoff"
  | "risk_contribution_bar"
  | "attribution_bar"
  | "bar_ladder"
  | "scatter"
  | "distribution";

export const CHART_KIND_VALUES: readonly ChartKind[] = [
  "time_series_line",
  "time_series_candles",
  "ohlcv",
  "heatmap",
  "surface",
  "frontier",
  "tenor_curve",
  "depth_ladder",
  "payoff",
  "risk_contribution_bar",
  "attribution_bar",
  "bar_ladder",
  "scatter",
  "distribution",
] as const;

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

export interface InputSpec {
  /** snake_case input id */
  name: string;
  /** Human label (TR or EN, default EN) */
  label: string;
  control: ControlKind;
  required: boolean;
  description: string;
  options?: unknown[] | null;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  unit?: string | null;
  /** Other input `name`s this control's visibility/enable depends on. */
  depends_on: string[];
}

export interface ProviderChain {
  primary: string;
  fallbacks: string[];
  acceptable_modes: DataMode[];
}

export interface CachingPolicy {
  /** TTL in seconds; 0 disables caching. */
  ttl_seconds: number;
  scope: "per_input" | "global";
  /** true = duckdb-backed, false = in-process. */
  persist: boolean;
}

export interface OutputContract {
  /** Fields that MUST be present and non-empty for status=ok. */
  must_have: string[];
  rows: boolean;
  series: boolean;
  cards: boolean;
  warnings: boolean;
  next_actions: boolean;
}

export interface AxisSpec {
  type: "time" | "category" | "numeric";
  unit: string | null;
  /**
   * Python schema permits None here, mirrored as `string | null`. JSON `null`
   * round-trips; absence (`undefined`) is normalized to `null` by callers
   * that need to read it.
   */
  label: string | null;
}

export type PaneSeriesKind = "candle" | "line" | "bar" | "area" | "histogram";

export interface PaneGrammar {
  name: string;
  series_kind: PaneSeriesKind;
  /** 1..100 */
  height_pct: number;
}

export interface ChartGrammar {
  kind: ChartKind;
  x_axis: AxisSpec;
  /** Either a single y-axis spec or a list of them (price + volume etc.). */
  y_axis: AxisSpec | AxisSpec[];
  panes: PaneGrammar[];
  overlay_support: boolean;
  compare_support: boolean;
}

export type ColumnKind =
  | "text"
  | "number"
  | "percent"
  | "currency"
  | "date"
  | "datetime"
  | "duration"
  | "tag"
  | "action";

export interface ColumnSpec {
  key: string;
  label: string;
  kind: ColumnKind;
  unit: string | null;
  format: string | null;
  width_hint: number | null;
}

export interface TableSchema {
  columns: ColumnSpec[];
  sortable: boolean;
  filterable: boolean;
}

export type CardSlotKind =
  | "kpi"
  | "big_number"
  | "trend_pill"
  | "mode_pill"
  | "timestamp"
  | "badge";

export interface CardSlot {
  key: string;
  label: string;
  kind: CardSlotKind;
  unit: string | null;
}

export interface CardSchema {
  slots: CardSlot[];
}

export interface Formula {
  /** LaTeX or plain math expression. */
  expression: string;
  /** Variable name → human description. */
  variables: Record<string, string>;
  notes: string | null;
}

export interface FieldDef {
  unit: string | null;
  description: string;
  source: string | null;
}

export interface ProvenanceSpec {
  require_source_list: boolean;
  require_as_of: boolean;
  require_latency_ms: boolean;
}

export type AlertDelivery = "tray" | "notification" | "log";

export interface AlertingSpec {
  conditions: string[];
  delivery: AlertDelivery[];
}

export interface SemanticTest {
  name: string;
  description: string;
  inputs: Record<string, unknown>;
  assertions: string[];
}

// ---------------------------------------------------------------------------
// Top-level manifest
// ---------------------------------------------------------------------------

export interface FunctionManifest {
  /** Uppercase code, e.g. "GP" or "PORT_OPT". */
  code: string;
  name: string;
  category: Category;
  /** One-sentence professional intent. */
  intent: string;
  asset_classes: AssetClass[];
  inputs: InputSpec[];
  /** Free-form default values keyed by `InputSpec.name`. */
  defaults: Record<string, unknown>;
  provider_chain: ProviderChain;
  caching: CachingPolicy;
  output_contract: OutputContract;
  chart_grammar: ChartGrammar | null;
  table_schema: TableSchema | null;
  card_schema: CardSchema | null;
  methodology: string;
  formula_dict: Record<string, Formula>;
  field_dict: Record<string, FieldDef>;
  provenance: ProvenanceSpec;
  alerting: AlertingSpec | null;
  /** Python enforces `min_length=1`; we keep that as a runtime expectation. */
  semantic_tests: SemanticTest[];
}

// ---------------------------------------------------------------------------
// Type guards (handy for derive-controls and renderers)
// ---------------------------------------------------------------------------

/** True when `y` is an array of axis specs (multi-axis chart). */
export function isMultiYAxis(y: AxisSpec | AxisSpec[]): y is AxisSpec[] {
  return Array.isArray(y);
}

/** Narrowing helper: returns the manifest only if it carries a chart grammar. */
export function hasChartGrammar(
  m: FunctionManifest,
): m is FunctionManifest & { chart_grammar: ChartGrammar } {
  return m.chart_grammar !== null && m.chart_grammar !== undefined;
}

export function hasTableSchema(
  m: FunctionManifest,
): m is FunctionManifest & { table_schema: TableSchema } {
  return m.table_schema !== null && m.table_schema !== undefined;
}

export function hasCardSchema(
  m: FunctionManifest,
): m is FunctionManifest & { card_schema: CardSchema } {
  return m.card_schema !== null && m.card_schema !== undefined;
}
