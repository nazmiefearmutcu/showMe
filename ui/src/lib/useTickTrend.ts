/**
 * Tick-trend history — honest watchlist sparklines.
 *
 * Background: the old synthetic sin/cos sparkline generator was removed by QA
 * (fabricated history), so watchlist rows shipped `trend: []` and the UI
 * rendered a "Trend data unavailable" placeholder. This module is the missing
 * "tick history hook" the placeholder comment asked for: it accumulates the
 * REAL live prices already flowing through `useLiveQuotes` into a short
 * per-symbol series. No network, no fabrication — the line starts short and
 * grows as ticks arrive; symbols without ticks keep the placeholder.
 */
import { useEffect, useState } from "react";
import type { QuoteView } from "@/lib/market-data";

/** How many recent ticks a sparkline keeps (intraday shape, bounded memory). */
export const TICK_TREND_MAX_POINTS = 30;

/**
 * Pure append: returns the SAME array reference when nothing should change
 * (missing/non-finite price, or price equal to the last point), so callers
 * can skip re-renders with a cheap `!==` check.
 */
export function appendTickPoint(
  history: readonly number[],
  price: number | null | undefined,
  maxPoints: number = TICK_TREND_MAX_POINTS,
): number[] {
  if (price == null || !Number.isFinite(price)) return history as number[];
  if (history.length > 0 && history[history.length - 1] === price) {
    return history as number[];
  }
  if (history.length >= maxPoints) {
    return [...history.slice(history.length - maxPoints + 1), price];
  }
  return [...history, price];
}

/**
 * Accumulate `quote.price` per symbol (upper-cased key) across renders.
 * Symbols that disappear from `liveQuotes` are pruned. State only updates
 * when at least one series actually grew, so idle ticks cost no renders.
 */
export function useTickTrend(
  liveQuotes: Record<string, QuoteView>,
  maxPoints: number = TICK_TREND_MAX_POINTS,
): Record<string, number[]> {
  const [series, setSeries] = useState<Record<string, number[]>>({});
  useEffect(() => {
    setSeries((prev) => {
      let changed = false;
      const next: Record<string, number[]> = { ...prev };
      const seen = new Set<string>();
      for (const [rawKey, quote] of Object.entries(liveQuotes ?? {})) {
        const key = rawKey.toUpperCase();
        seen.add(key);
        const updated = appendTickPoint(next[key] ?? [], quote?.price, maxPoints);
        if (updated !== next[key]) {
          next[key] = updated;
          changed = true;
        }
      }
      for (const key of Object.keys(next)) {
        if (!seen.has(key)) {
          delete next[key];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [liveQuotes, maxPoints]);
  return series;
}
