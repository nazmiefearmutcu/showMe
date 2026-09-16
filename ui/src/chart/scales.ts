/**
 * showMe chart engine — affine time/price scales with unlimited zoom + pan.
 *
 * The time scale is INDEX-based: it never parses timestamps. The caller's
 * bar array supplies times; the scale only knows "bar index" (float) <-> x
 * pixel. Both scales share the same gesture grammar:
 *
 *   - `zoomAt(pixel, factor)`: factor > 1 zooms IN, and the data value under
 *     the cursor pixel stays exactly under it afterwards.
 *   - `panBy(delta)`: the chart content follows the gesture — a positive `dx`
 *     shifts content right by `dx` px, a positive `dy` shifts it down.
 *   - Both are resilient to `setViewport` at any time (before or after range
 *     setup) and to degenerate/tiny viewports, which are clamped to a 1e-3 px
 *     plot so no division can produce NaN/Infinity.
 *
 * There is no clamping to the dataset: empty space beyond the first/last bar
 * is legal and rendered as grid.
 */

import type { PriceScale, TimeScale, Viewport } from "./types";

const DEFAULT_VIEWPORT: Viewport = {
  width: 800,
  height: 600,
  priceAxisWidth: 64,
  timeAxisHeight: 24,
};

/**
 * Deep zoom-out floor: 1e-7 px per bar makes the visible range effectively
 * unbounded (~10^10 bars in an 800 px plot) — zooming out reveals empty space
 * instead of stopping at a magic span. Extreme zoom-in cap: 1500 px per bar.
 * These are the only zoom limits.
 */
const MIN_BAR_WIDTH = 1e-7;
const MAX_BAR_WIDTH = 1500;

/** Bars visible before the caller calls setRange. */
const DEFAULT_BAR_SPAN = 100;

/** Price-span guards; wide enough for any instrument, narrow enough to stay finite. */
const MIN_PRICE_SPAN = 1e-12;
const MAX_PRICE_SPAN = 1e15;
const DEFAULT_PAD_FRAC = 0.08;

function sanitizeViewport(vp: Viewport): Viewport {
  return {
    width: Number.isFinite(vp.width) ? vp.width : 0,
    height: Number.isFinite(vp.height) ? vp.height : 0,
    priceAxisWidth: Number.isFinite(vp.priceAxisWidth) ? vp.priceAxisWidth : 0,
    timeAxisHeight: Number.isFinite(vp.timeAxisHeight) ? vp.timeAxisHeight : 0,
  };
}

export function createTimeScale(): TimeScale {
  let vp: Viewport = { ...DEFAULT_VIEWPORT };
  let from = 0;
  let to = DEFAULT_BAR_SPAN;

  const plotWidth = (): number => Math.max(1e-3, vp.width - vp.priceAxisWidth);
  const span = (): number => to - from;
  const clampSpan = (raw: number): number => {
    const minSpan = plotWidth() / MAX_BAR_WIDTH;
    const maxSpan = plotWidth() / MIN_BAR_WIDTH;
    return Math.min(maxSpan, Math.max(minSpan, raw));
  };
  // Local defs (not `this.*`): methods stay callable after destructuring.
  const toIndex = (x: number): number => from + (x / plotWidth()) * span();
  const barWidth = (): number => plotWidth() / span();

  return {
    setViewport(next: Viewport): void {
      vp = sanitizeViewport(next);
      // A resize must not leave barWidth outside the legal extremes; clamp
      // symmetrically around the range center so neither edge wins.
      const clamped = clampSpan(span());
      if (clamped !== span()) {
        const center = (from + to) / 2;
        from = center - clamped / 2;
        to = center + clamped / 2;
      }
    },

    toX(index: number): number {
      return ((index - from) / span()) * plotWidth();
    },

    toIndex,

    zoomAt(x: number, factor: number): void {
      if (!Number.isFinite(x) || !Number.isFinite(factor) || factor <= 0) {
        return;
      }
      const anchor = toIndex(x);
      const target = Math.min(
        MAX_BAR_WIDTH,
        Math.max(MIN_BAR_WIDTH, barWidth() * factor),
      );
      const nextSpan = plotWidth() / target;
      const fraction = x / plotWidth();
      from = anchor - fraction * nextSpan;
      to = from + nextSpan;
    },

    panBy(dx: number): void {
      if (!Number.isFinite(dx)) {
        return;
      }
      const shift = dx / barWidth();
      from -= shift;
      to -= shift;
    },

    setRange(i0: number, i1: number): void {
      if (!Number.isFinite(i0) || !Number.isFinite(i1)) {
        return;
      }
      let lo = Math.min(i0, i1);
      let hi = Math.max(i0, i1);
      if (hi - lo < 1e-9) {
        const center = (lo + hi) / 2;
        lo = center - 0.5;
        hi = center + 0.5;
      }
      const nextSpan = clampSpan(hi - lo);
      const center = (lo + hi) / 2;
      from = center - nextSpan / 2;
      to = center + nextSpan / 2;
    },

    range(): { from: number; to: number } {
      return { from, to };
    },

    barWidth(): number {
      return plotWidth() / span();
    },
  };
}

export function createPriceScale(): PriceScale {
  let vp: Viewport = { ...DEFAULT_VIEWPORT };
  let min = 0;
  let max = 1;

  const plotHeight = (): number => Math.max(1e-3, vp.height - vp.timeAxisHeight);
  const span = (): number => max - min;
  const clampSpan = (raw: number): number =>
    Math.min(MAX_PRICE_SPAN, Math.max(MIN_PRICE_SPAN, raw));
  // Local def (not `this.*`): methods stay callable after destructuring.
  const toPrice = (y: number): number =>
    min + ((plotHeight() - y) / plotHeight()) * span();

  return {
    setViewport(next: Viewport): void {
      vp = sanitizeViewport(next);
      // The price range itself is viewport-independent (stretching rescales
      // the mapping, it does not change the visible prices).
    },

    toY(price: number): number {
      const height = plotHeight();
      return height - ((price - min) / span()) * height;
    },

    toPrice,

    zoomAt(y: number, factor: number): void {
      if (!Number.isFinite(y) || !Number.isFinite(factor) || factor <= 0) {
        return;
      }
      const anchor = toPrice(y);
      const nextSpan = clampSpan(span() / factor);
      const fraction = (plotHeight() - y) / plotHeight();
      min = anchor - fraction * nextSpan;
      max = min + nextSpan;
    },

    panBy(dy: number): void {
      if (!Number.isFinite(dy)) {
        return;
      }
      const shift = (dy / plotHeight()) * span();
      min += shift;
      max += shift;
    },

    fit(minIn: number, maxIn: number, padFrac = DEFAULT_PAD_FRAC): void {
      let lo = minIn;
      let hi = maxIn;
      if (!Number.isFinite(lo) && !Number.isFinite(hi)) {
        lo = 0;
        hi = 1;
      } else if (!Number.isFinite(lo)) {
        lo = hi;
      } else if (!Number.isFinite(hi)) {
        hi = lo;
      }
      if (hi < lo) {
        const swap = lo;
        lo = hi;
        hi = swap;
      }
      if (hi === lo) {
        // Degenerate: expand by 1% of the value, or ±1 when the value is 0.
        const delta = Math.abs(lo) * 0.01 || 1;
        lo -= delta;
        hi += delta;
      }
      const pad = Number.isFinite(padFrac)
        ? Math.min(0.5, Math.max(0, padFrac))
        : DEFAULT_PAD_FRAC;
      const padding = (hi - lo) * pad;
      let nextMin = lo - padding;
      let nextMax = hi + padding;
      if (!Number.isFinite(nextMin) || !Number.isFinite(nextMax)) {
        nextMin = 0;
        nextMax = 1;
      }
      const nextSpan = clampSpan(nextMax - nextMin);
      if (nextSpan !== nextMax - nextMin) {
        const center = (nextMin + nextMax) / 2;
        nextMin = center - nextSpan / 2;
        nextMax = center + nextSpan / 2;
      }
      min = nextMin;
      max = nextMax;
    },

    range(): { min: number; max: number } {
      return { min, max };
    },
  };
}
