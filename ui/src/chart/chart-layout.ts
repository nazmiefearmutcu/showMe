/**
 * showMe chart engine — layout persistence (milestone 3).
 *
 * Persists the chart's last-used state per symbol inside ONE localStorage
 * map (`showme.chart.layout.v1`). Read path is defensive: a corrupt JSON
 * blob, a non-object entry, or invalid per-field values are dropped
 * silently and the caller falls back to defaults — "restore only what was
 * saved", never a half-invented state.
 */
import type { Drawing } from "./drawings";
import { TIMEFRAMES } from "./timeframes";
import type { ChartType, IndicatorInstance, PriceMode } from "./types";

export const LAYOUT_STORE_KEY = "showme.chart.layout.v1";

export interface ChartLayout {
  interval: string;
  chartType: ChartType;
  priceMode: PriceMode;
  showVolume: boolean;
  indicators: IndicatorInstance[];
  drawings: Drawing[];
  compareSymbols: string[];
}

const CHART_TYPES: ChartType[] = ["candles", "line", "area", "bars", "heikin"];
const PRICE_MODES: PriceMode[] = ["linear", "log", "percent"];

function safeStorage(storage?: Storage | null): Storage | null {
  if (storage !== undefined) return storage;
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

function readMap(storage: Storage | null): Record<string, unknown> {
  if (!storage) return {};
  try {
    const raw = storage.getItem(LAYOUT_STORE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return {};
    return parsed as Record<string, unknown>;
  } catch {
    return {};
  }
}

function isPoint(v: unknown): v is { index: number; price: number } {
  if (typeof v !== "object" || v === null) return false;
  const p = v as Record<string, unknown>;
  return (
    typeof p.index === "number" &&
    Number.isFinite(p.index) &&
    typeof p.price === "number" &&
    Number.isFinite(p.price)
  );
}

function sanitizeDrawing(v: unknown): Drawing | null {
  if (typeof v !== "object" || v === null) return null;
  const d = v as Record<string, unknown>;
  if (typeof d.id !== "string") return null;
  if (d.kind === "hline") {
    return typeof d.price === "number" && Number.isFinite(d.price)
      ? { id: d.id, kind: "hline", price: d.price }
      : null;
  }
  if (d.kind === "trend" || d.kind === "fib") {
    return isPoint(d.p1) && isPoint(d.p2)
      ? { id: d.id, kind: d.kind, p1: { ...d.p1 }, p2: { ...d.p2 } }
      : null;
  }
  return null;
}

function sanitizeInstance(v: unknown): IndicatorInstance | null {
  if (typeof v !== "object" || v === null) return null;
  const i = v as Record<string, unknown>;
  if (
    typeof i.id !== "string" ||
    typeof i.indicator !== "string" ||
    typeof i.visible !== "boolean" ||
    (i.pane !== "overlay" && i.pane !== "separate")
  ) {
    return null;
  }
  if (typeof i.params !== "object" || i.params === null || Array.isArray(i.params)) return null;
  const params: Record<string, number | string> = {};
  for (const [key, value] of Object.entries(i.params as Record<string, unknown>)) {
    if (typeof value === "number" && Number.isFinite(value)) params[key] = value;
    else if (typeof value === "string") params[key] = value;
  }
  return { id: i.id, indicator: i.indicator, params, visible: i.visible, pane: i.pane };
}

/**
 * Load the saved layout for one symbol. Returns a partial layout holding
 * only the fields that were saved AND passed validation; null when the
 * store is missing/corrupt or the entry is not an object.
 */
/**
 * Layout store key. ``scope`` namespaces the entry by consuming surface
 * (e.g. "CHGS" vs "GP") so a timeframe picked in an intraday pane can never
 * leak into a daily-studies pane for the same symbol — the reported case: a
 * stale 1s layout restored into CHGS made the daily chart look dead.
 * Scope-less callers keep the historical symbol-only key.
 */
function storeKey(symbol: string, scope?: string): string {
  return scope ? `${scope}:${symbol}` : symbol;
}

export function loadLayout(
  symbol: string,
  storage?: Storage | null,
  scope?: string,
): Partial<ChartLayout> | null {
  const store = readMap(safeStorage(storage));
  const entry = store[storeKey(symbol, scope)];
  if (typeof entry !== "object" || entry === null || Array.isArray(entry)) return null;
  const raw = entry as Record<string, unknown>;
  const out: Partial<ChartLayout> = {};
  if (typeof raw.interval === "string" && TIMEFRAMES.some((t) => t.id === raw.interval)) {
    out.interval = raw.interval;
  }
  if (typeof raw.chartType === "string" && CHART_TYPES.includes(raw.chartType as ChartType)) {
    out.chartType = raw.chartType as ChartType;
  }
  if (typeof raw.priceMode === "string" && PRICE_MODES.includes(raw.priceMode as PriceMode)) {
    out.priceMode = raw.priceMode as PriceMode;
  }
  if (typeof raw.showVolume === "boolean") out.showVolume = raw.showVolume;
  if (Array.isArray(raw.indicators)) {
    out.indicators = raw.indicators
      .map(sanitizeInstance)
      .filter((v): v is IndicatorInstance => v !== null);
  }
  if (Array.isArray(raw.drawings)) {
    out.drawings = raw.drawings
      .map(sanitizeDrawing)
      .filter((v): v is Drawing => v !== null);
  }
  if (Array.isArray(raw.compareSymbols)) {
    const seen = new Set<string>();
    const syms: string[] = [];
    for (const v of raw.compareSymbols) {
      if (typeof v !== "string") continue;
      const s = v.trim();
      if (!s || seen.has(s)) continue;
      seen.add(s);
      syms.push(s);
    }
    out.compareSymbols = syms;
  }
  return Object.keys(out).length > 0 ? out : null;
}

/** Persist the layout for one symbol; storage failures are ignored. */
export function saveLayout(
  symbol: string,
  layout: ChartLayout,
  storage?: Storage | null,
  scope?: string,
): void {
  const s = safeStorage(storage);
  if (!s) return;
  try {
    const map = readMap(s);
    map[storeKey(symbol, scope)] = layout;
    s.setItem(LAYOUT_STORE_KEY, JSON.stringify(map));
  } catch {
    /* private mode / quota — the chart keeps working without persistence */
  }
}

/** Drop the saved layout for one symbol (Reset). Empty map removes the key. */
export function clearLayout(
  symbol: string,
  storage?: Storage | null,
  scope?: string,
): void {
  const s = safeStorage(storage);
  if (!s) return;
  try {
    const map = readMap(s);
    delete map[storeKey(symbol, scope)];
    if (Object.keys(map).length === 0) s.removeItem(LAYOUT_STORE_KEY);
    else s.setItem(LAYOUT_STORE_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}
