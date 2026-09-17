/**
 * Daily-close trends — honest watchlist sparklines, take two.
 *
 * The tick-history hook (`useTickTrend`) draws whatever the live socket
 * happens to emit — on a quiet symbol that is a flat second-by-second line,
 * not a trend. This hook fetches the last N DAILY closes per symbol through
 * the same GP candle path the chart panes use (`runFunction("GP",
 * { interval: "1d", bars })`) and returns one close series per symbol.
 * Daily closes win over tick history in the watchlist; when candles are
 * unavailable the symbol simply has no entry here (placeholder stays —
 * never fabricated).
 *
 * Module-level cache (15 min TTL): the watchlist mounts/polls often, daily
 * closes barely move. `runFunction` already dedupes in-flight calls.
 */
import { useEffect, useState } from "react";
import { runFunction } from "@/lib/functions";
import { parseOhlcRows } from "@/lib/market-data";

/** How many daily closes a sparkline shows. */
export const DAILY_TREND_BARS = 30;
/** Daily closes barely move — refetch at most this often per symbol. */
export const DAILY_TREND_TTL_MS = 15 * 60 * 1000;

interface CacheEntry {
  closes: number[];
  fetchedAt: number;
}

const _cache = new Map<string, CacheEntry>();

/** Test seam: clear the module cache. */
export function clearDailyTrendCache(): void {
  _cache.clear();
}

function cachedCloses(symbol: string, now: number): number[] | null {
  const entry = _cache.get(symbol);
  if (!entry) return null;
  if (now - entry.fetchedAt > DAILY_TREND_TTL_MS) {
    _cache.delete(symbol);
    return null;
  }
  return entry.closes;
}

interface GpData {
  ohlcv?: unknown;
  bars?: unknown;
  rows?: unknown;
}

/** Pure: pull finite closes (time-ascending) out of a GP payload. */
export function closesFromGpPayload(payload: GpData | null | undefined): number[] {
  const source = payload?.ohlcv ?? payload?.bars ?? payload?.rows ?? null;
  return parseOhlcRows(source)
    .map((bar) => bar.close)
    .filter((close) => Number.isFinite(close));
}

/**
 * Fetch daily closes for `symbols` (upper-cased keys). Returns only symbols
 * with a non-empty series; the rest keep their tick history / placeholder.
 */
export function useDailyTrends(
  symbols: readonly string[],
  options: { enabled?: boolean; bars?: number } = {},
): Record<string, number[]> {
  const { enabled = true, bars = DAILY_TREND_BARS } = options;
  const [series, setSeries] = useState<Record<string, number[]>>({});
  const key = symbols.join(",");
  useEffect(() => {
    if (!enabled || symbols.length === 0) {
      setSeries((prev) => (Object.keys(prev).length > 0 ? {} : prev));
      return undefined;
    }
    let cancelled = false;
    const now = Date.now();
    const missing = symbols
      .map((s) => s.toUpperCase())
      .filter((s) => s && cachedCloses(s, now) === null);
    // Seed state from cache first so remounts paint instantly.
    setSeries((prev) => {
      const next: Record<string, number[]> = {};
      let changed = Object.keys(prev).length > 0;
      for (const raw of symbols) {
        const sym = raw.toUpperCase();
        const hit = cachedCloses(sym, now);
        if (hit && hit.length > 0) {
          next[sym] = hit;
          if (prev[sym] !== hit) changed = true;
        }
      }
      return changed ? next : prev;
    });
    if (missing.length === 0) return undefined;
    (async () => {
      const results = await Promise.all(
        missing.map(async (sym) => {
          try {
            const raw = await runFunction<GpData>("GP", {
              symbol: sym,
              params: { interval: "1d", bars },
            });
            const closes = closesFromGpPayload(raw?.data);
            return { sym, closes } as const;
          } catch {
            return { sym, closes: [] as number[] } as const;
          }
        }),
      );
      if (cancelled) return;
      const fetchedAt = Date.now();
      setSeries((prev) => {
        const next = { ...prev };
        let changed = false;
        for (const { sym, closes } of results) {
          if (closes.length === 0) continue;
          _cache.set(sym, { closes, fetchedAt });
          if (next[sym] !== closes) {
            next[sym] = closes;
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, bars]);
  return series;
}
