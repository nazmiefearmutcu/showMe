/**
 * Bridges CSS theme tokens into lightweight-charts (and any other library
 * that needs runtime hex strings instead of `var(--*)`). Reads the currently
 * applied tokens from `<html>` and re-publishes them on every theme change.
 *
 * Why: lightweight-charts options accept fixed strings, not CSS variables.
 * Without this bridge the chart palette stays midnight under Papyrus.
 */

export interface ChartPalette {
  positive: string;
  negative: string;
  accent: string;
  warn: string;
  text: string;
  grid: string;
  border: string;
  volNeutral: string;
  volPos: string;
  volNeg: string;
  surface: string;
  bg: string;
}

const FALLBACK: ChartPalette = {
  positive: "#2fd480",
  negative: "#ff5874",
  accent: "#7c7aff",
  warn: "#f0b445",
  text: "rgba(240, 242, 245, 0.85)",
  grid: "rgba(255, 255, 255, 0.04)",
  border: "rgba(255, 255, 255, 0.08)",
  volNeutral: "rgba(160, 164, 171, 0.35)",
  volPos: "rgba(47, 212, 128, 0.40)",
  volNeg: "rgba(255, 88, 116, 0.40)",
  surface: "#0f1115",
  bg: "#07080a",
};

/**
 * Apply an alpha channel to a hex string (`#rgb` or `#rrggbb`). Returns an
 * `rgba(...)` string lightweight-charts will accept. Pass-through for inputs
 * that already contain non-hex notation.
 */
export function alpha(color: string, a: number): string {
  let h = color.trim();
  if (!h.startsWith("#")) return color;
  h = h.slice(1);
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return color;
  return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${a})`;
}

function pick(name: string, fallback: string): string {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return fallback;
  }
  const val = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return val.length > 0 ? val : fallback;
}

export function readChartPalette(): ChartPalette {
  return {
    positive: pick("--positive", FALLBACK.positive),
    negative: pick("--negative", FALLBACK.negative),
    accent: pick("--accent", FALLBACK.accent),
    warn: pick("--warn", FALLBACK.warn),
    text: pick("--text-primary", FALLBACK.text),
    grid: pick("--border-subtle", FALLBACK.grid),
    border: pick("--border-strong", FALLBACK.border),
    volNeutral: pick("--heat-neg-1", FALLBACK.volNeutral),
    volPos: pick("--heat-pos-2", FALLBACK.volPos),
    volNeg: pick("--heat-neg-2", FALLBACK.volNeg),
    surface: pick("--surface", FALLBACK.surface),
    bg: pick("--bg", FALLBACK.bg),
  };
}

type Listener = (palette: ChartPalette) => void;
const listeners = new Set<Listener>();
let observer: MutationObserver | null = null;
let coalesceHandle: number | null = null;

function flushNotify(): void {
  coalesceHandle = null;
  const palette = readChartPalette();
  for (const fn of listeners) fn(palette);
}

function cancelPendingCoalesce(): void {
  if (coalesceHandle == null) return;
  if (typeof cancelAnimationFrame === "function") {
    cancelAnimationFrame(coalesceHandle);
  } else if (typeof window !== "undefined" && typeof window.clearTimeout === "function") {
    window.clearTimeout(coalesceHandle);
  }
  coalesceHandle = null;
}

function ensureObserver(): void {
  if (observer || typeof document === "undefined") return;
  // PERF: a single preset/density change mutates up to 3 watched
  // attributes on <html> (data-preset, data-theme, inline style). Without
  // coalescing we'd fan-out the 9 chart consumers 3×. Collapse all
  // mutations in a single rAF tick into one notify.
  observer = new MutationObserver(() => {
    if (coalesceHandle != null) return;
    coalesceHandle =
      typeof requestAnimationFrame === "function"
        ? requestAnimationFrame(flushNotify)
        : window.setTimeout(flushNotify, 0);
  });
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-preset", "data-density", "data-theme", "style"],
  });
}

function tearDownObserver(): void {
  // REL-04 P9 — when the last subscriber unsubscribes we must disconnect
  // the MutationObserver and cancel any in-flight coalesced rAF id;
  // otherwise the observer keeps a reference to the closure (and the
  // `listeners` Set) for the whole page lifetime even though nothing
  // listens. With React StrictMode mounting/unmounting twice this
  // mattered, plus the test runner needs a clean teardown.
  if (observer) {
    observer.disconnect();
    observer = null;
  }
  cancelPendingCoalesce();
}

/**
 * Subscribe to palette changes. The listener is invoked once immediately
 * and again on every `<html data-preset>` / `<html style="">` mutation.
 * Returns an unsubscribe function.
 */
export function subscribeChartPalette(fn: Listener): () => void {
  ensureObserver();
  listeners.add(fn);
  fn(readChartPalette());
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      tearDownObserver();
    }
  };
}

/** Test hook — returns whether the observer is currently attached. */
export function __isChartPaletteObserverActive(): boolean {
  return observer !== null;
}

import { useEffect, useState } from "react";

/**
 * React hook for components that need a live ChartPalette. Re-renders on
 * theme change.
 */
export function useChartPalette(): ChartPalette {
  const [palette, setPalette] = useState<ChartPalette>(() => readChartPalette());
  useEffect(() => subscribeChartPalette(setPalette), []);
  return palette;
}
