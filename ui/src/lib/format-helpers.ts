/**
 * Auxiliary formatting helpers — composes with `lib/format.ts` (frozen
 * contract) without modifying its public API.
 *
 * Background: Wave 2 QA found that lightweight-charts' `priceFormat` defaulted
 * to `{ precision: 2, minMove: 0.01 }`, so sub-cent crypto (e.g. PENGU at
 * $0.000620) rendered as "0.00" on the axis. The chart needs a per-symbol
 * precision derived from the last close. Likewise function_stub helpers used
 * a static `maxFractionDigits: 6` which collapsed both small and large
 * numbers awkwardly.
 *
 * These helpers are intentionally pure (no React, no DOM) so they can be
 * unit-tested and re-used by both the chart and metric code paths.
 */

import { formatMissing } from "./format";

/**
 * Adaptive decimal count for a single price value.
 *
 *   abs(p) >= 1      → 2 dp  (default for stocks / large-cap crypto)
 *   abs(p) >= 0.01   → 4 dp  (penny stocks, alt-coins)
 *   abs(p) >= 0.0001 → 6 dp  (low-cap)
 *   abs(p) >= 1e-8   → 8 dp  (PENGU-class sub-cent crypto)
 *   abs(p) < 1e-8    → 10 dp (effectively scientific-only territory)
 *
 * NaN / Infinity / null / undefined / zero → 2 dp (safe default for
 * downstream lightweight-charts price-format which rejects precision === 0).
 */
export function getDecimalsForPrice(price: number | null | undefined): number {
  if (price == null || !Number.isFinite(price)) return 2;
  const a = Math.abs(price);
  if (a === 0) return 2;
  if (a >= 1) return 2;
  if (a >= 0.01) return 4;
  if (a >= 0.0001) return 6;
  if (a >= 1e-8) return 8;
  return 10;
}

/**
 * Build a lightweight-charts `priceFormat` object whose precision and
 * `minMove` track the asset's price magnitude. The resulting axis ticks
 * show real precision for sub-cent assets instead of collapsing to "0.00".
 */
export function getCandlePriceFormat(price: number | null | undefined): {
  type: "price";
  precision: number;
  minMove: number;
} {
  const precision = getDecimalsForPrice(price);
  // 10**-precision is exact for integer precision in IEEE-754 (no rounding
  // bug at our magnitudes), so we don't need a multiplicand workaround.
  const minMove = Math.pow(10, -precision);
  return { type: "price", precision, minMove };
}

/**
 * Locale-aware number formatter with adaptive decimal count. Used by
 * function_stub helpers to render generic numeric cells (KPI tiles,
 * preview rows) without smashing sub-cent precision.
 *
 * For non-finite input returns the {@link formatMissing} em-dash sentinel.
 */
export function formatAdaptive(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return formatMissing;
  const digits = getDecimalsForPrice(value);
  return value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}
