/**
 * showMe chart engine — FROZEN shared contract (milestone 1, 2026-09-15).
 *
 * A self-contained professional charting engine (no third-party chart
 * library). Every module in `ui/src/chart/` codes against these types:
 *
 *   timeframes.ts  — interval catalog + resampling
 *   scales.ts      — time/price affine scales with unlimited zoom/pan
 *   indicators.ts  — pure indicator registry (compute over bars)
 *   renderer.ts    — canvas 2D painter (grid, axes, candles, overlays, panes)
 *   Chart.tsx      — React shell (data fetch, TF/type pickers, indicator UX)
 *
 * Theme rule: colors are CSS variable expressions ("var(--accent)") by
 * default; the renderer resolves them against the live element at draw time,
 * so EVERY theme works without per-theme code.
 */

import type { Drawing } from "./drawings";

/** One OHLCV bar. `t` = bar OPEN time in epoch milliseconds. */
export interface Bar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export type ChartType = "candles" | "line" | "area" | "bars" | "heikin";

/**
 * Price-scale mode (milestone 2):
 *   - "linear": raw prices, affine (default);
 *   - "log": log10 mapping when the visible range is strictly positive,
 *     honest linear fallback otherwise;
 *   - "percent": linear mapping with axis/crosshair labels expressed as
 *     % change vs. the first visible bar's close.
 */
export type PriceMode = "linear" | "log" | "percent";

/** Interval catalog entry. `provider` is the /api/bars interval string. */
export interface TimeframeDef {
  /** showMe id used in the UI ("1s", "15m", "1h", "1D"...). */
  id: string;
  /** Label rendered in the picker. */
  label: string;
  /** Duration in seconds (for resampling + axis heuristics). */
  seconds: number;
  /** Provider interval sent to /api/bars (Binance/yahoo mapping handled
   * server-side; identical to `id` for the common set). */
  provider: string;
  /** Optional grouping for the picker (Seconds/Minutes/Hours/Days). */
  group: "seconds" | "minutes" | "hours" | "days" | "weeks" | "months";
}

/** GET /api/bars response. */
export interface BarsResponse {
  symbol: string;
  interval: string;
  bars: Bar[];
  /** Provider that answered ("binance" | "yahoo" | ...). */
  source: string;
  /** ISO served-at stamp. */
  asOf: string;
  /** Honest reason when bars is empty (never a silent blank). */
  reason?: string;
}

/* ── indicators ─────────────────────────────────────────────────────── */

export interface IndicatorParamDef {
  key: string;
  label: string;
  kind: "number" | "select" | "color";
  default: number | string;
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string; label: string }[];
}

export interface IndicatorPlot {
  key: string;
  label: string;
  type: "line" | "histogram" | "band" | "dots";
  /** CSS color expression ("var(--accent)" or literal). */
  color: string;
  /** One entry per bar; null = not defined yet (renderer skips). */
  data: (number | null)[];
  /** Band-only: second line key drawn from the same result. */
  pairKey?: string;
  width?: number;
}

export interface IndicatorResult {
  plots: IndicatorPlot[];
  /** Horizontal reference levels (e.g. 70/30 for RSI). */
  levels?: number[];
  /** Draw a zero line (oscillators). */
  zeroLine?: boolean;
}

export type IndicatorParams = Record<string, number | string>;

export interface IndicatorDef {
  id: string;
  name: string;
  /** Picker category ("Moving averages", "Oscillators", ...). */
  category: string;
  /** True = drawn on the price pane by default; false = own pane below. */
  overlayDefault: boolean;
  params: IndicatorParamDef[];
  compute: (bars: Bar[], params: IndicatorParams) => IndicatorResult;
}

/** One open indicator attached to the chart. */
export interface IndicatorInstance {
  /** Stable instance id (crypto.randomUUID in the UI). */
  id: string;
  /** Registry id. */
  indicator: string;
  params: IndicatorParams;
  visible: boolean;
  /** Where it draws; defaults from IndicatorDef.overlayDefault. */
  pane: "overlay" | "separate";
}

/* ── viewport + scales ──────────────────────────────────────────────── */

export interface Viewport {
  /** Full canvas CSS pixel size. */
  width: number;
  height: number;
  /** Price axis gutter on the right (px). */
  priceAxisWidth: number;
  /** Time axis strip at the bottom (px). */
  timeAxisHeight: number;
}

export interface TimeScale {
  setViewport(vp: Viewport): void;
  /** Bar index <-> x pixel. The scale is index-based; timestamps come from
   * the caller's bar array (uniform for provider data). */
  toX(index: number): number;
  toIndex(x: number): number;
  /** Wheel zoom anchored at a pixel x; factor > 1 zooms in. */
  zoomAt(x: number, factor: number): void;
  panBy(dx: number): void;
  /** Fit [i0..i1] (a trailing window when right-anchored). */
  setRange(i0: number, i1: number): void;
  /** Visible index range (float, unclamped) for the plot area. */
  range(): { from: number; to: number };
  /** Pixels per bar. */
  barWidth(): number;
}

export interface PriceScale {
  setViewport(vp: Viewport): void;
  toY(price: number): number;
  toPrice(y: number): number;
  /** Wheel zoom anchored at pixel y; factor > 1 zooms in. */
  zoomAt(y: number, factor: number): void;
  panBy(dy: number): void;
  fit(min: number, max: number, padFrac?: number): void;
  range(): { min: number; max: number };
}

/** Crosshair position in plot pixel space, or null when outside. */
export interface CrosshairState {
  x: number;
  y: number;
  index: number | null;
}

/* ── renderer ───────────────────────────────────────────────────────── */

export interface ThemePalette {
  background: string;
  grid: string;
  axisText: string;
  textPrimary: string;
  textSecondary: string;
  positive: string;
  negative: string;
  wick: string;
  bodyUp: string;
  bodyDown: string;
  line: string;
  areaTop: string;
  areaBottom: string;
  crosshair: string;
  accent: string;
}

export interface RenderInput {
  ctx: CanvasRenderingContext2D;
  /** Device pixel ratio to scale by. */
  dpr: number;
  viewport: Viewport;
  palette: ThemePalette;
  bars: Bar[];
  chartType: ChartType;
  time: TimeScale;
  price: PriceScale;
  /** Instances + their computed results (already computed by the shell). */
  indicators: { instance: IndicatorInstance; def: IndicatorDef; result: IndicatorResult }[];
  crosshair: CrosshairState | null;
  /** Symbol label for the watermark. */
  symbol: string;
  /** Honest footer note (provider/as-of) drawn top-left. */
  legend?: string;
  /** Price-scale mode; omitted = "linear" (backward compatible). */
  priceMode?: PriceMode;
  /** Draw the volume histogram strip (bottom ~18% of the main pane). */
  showVolume?: boolean;
  /** User drawings; omitted/empty draws nothing. */
  drawings?: Drawing[];
}
