/**
 * showMe chart engine — timeframe catalog + OHLCV resampling.
 *
 * The catalog is the single source of truth for chart intervals. `provider`
 * is intentionally identical to `id`: the shell sends it verbatim as the
 * `interval` query parameter of GET /api/bars, and the backend maps it to the
 * per-venue provider interval (Binance `1d`/`1w`/`1M`, Yahoo `1wk`/`1mo`,
 * stooq `d`/`w`/`m`). Keeping the two strings equal here means no frontend
 * mapping table can drift away from the backend's own mapping.
 */

import type { Bar, TimeframeDef } from "./types";

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;

/**
 * A month is bucketed as exactly 30 days by convention — the same constant
 * the backend uses (`1mo` = 2_592_000 s). Calendar months are not constant
 * length, so a fixed 30-day bucket is the only mapping that keeps
 * resampling deterministic.
 */
const MONTH = 30 * DAY;

export const TIMEFRAMES: TimeframeDef[] = [
  { id: "1s", label: "1s", seconds: 1, provider: "1s", group: "seconds" },
  { id: "5s", label: "5s", seconds: 5, provider: "5s", group: "seconds" },
  { id: "15s", label: "15s", seconds: 15, provider: "15s", group: "seconds" },
  { id: "30s", label: "30s", seconds: 30, provider: "30s", group: "seconds" },
  { id: "1m", label: "1m", seconds: 1 * MINUTE, provider: "1m", group: "minutes" },
  { id: "3m", label: "3m", seconds: 3 * MINUTE, provider: "3m", group: "minutes" },
  { id: "5m", label: "5m", seconds: 5 * MINUTE, provider: "5m", group: "minutes" },
  { id: "15m", label: "15m", seconds: 15 * MINUTE, provider: "15m", group: "minutes" },
  { id: "30m", label: "30m", seconds: 30 * MINUTE, provider: "30m", group: "minutes" },
  { id: "1h", label: "1h", seconds: HOUR, provider: "1h", group: "hours" },
  { id: "2h", label: "2h", seconds: 2 * HOUR, provider: "2h", group: "hours" },
  { id: "4h", label: "4h", seconds: 4 * HOUR, provider: "4h", group: "hours" },
  { id: "6h", label: "6h", seconds: 6 * HOUR, provider: "6h", group: "hours" },
  { id: "8h", label: "8h", seconds: 8 * HOUR, provider: "8h", group: "hours" },
  { id: "12h", label: "12h", seconds: 12 * HOUR, provider: "12h", group: "hours" },
  { id: "1D", label: "1D", seconds: DAY, provider: "1D", group: "days" },
  { id: "1W", label: "1W", seconds: WEEK, provider: "1W", group: "weeks" },
  { id: "1M", label: "1M", seconds: MONTH, provider: "1M", group: "months" },
];

const TIMEFRAMES_BY_ID: Map<string, TimeframeDef> = new Map(
  TIMEFRAMES.map((tf) => [tf.id, tf]),
);

/**
 * Exact-id lookup. Deliberately case-sensitive: "1m" (minute) and "1M"
 * (month) are distinct instruments in the catalog, so a case-insensitive
 * fallback would silently pick the wrong bucket.
 */
export function timeframeById(id: string): TimeframeDef | undefined {
  return TIMEFRAMES_BY_ID.get(id);
}

/**
 * Provider support mirrors the backend's maps in
 * `showme/server_routes/bars.py` (same canonical ids the shell sends).
 * Binance serves every catalog id except the 5s/15s/30s "recognized but
 * unmapped" seconds; Yahoo serves minutes, 30m/1h and above — no seconds
 * and no 3m/2h/4h/6h/8h/12h. Unknown/empty sources return true so the
 * backend stays the single source of truth for honest refusals.
 */
const BINANCE_UNSUPPORTED: ReadonlySet<string> = new Set(["5s", "15s", "30s"]);
const YAHOO_SUPPORTED: ReadonlySet<string> = new Set([
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "1D",
  "1W",
  "1M",
]);

export function intervalSupported(source: string, id: string): boolean {
  if (source === "binance") return !BINANCE_UNSUPPORTED.has(id);
  if (source === "yahoo") return YAHOO_SUPPORTED.has(id);
  return true;
}

/** Closest supported horizon when a (source, interval) pair is refused. */
export function fallbackIntervalFor(source: string): string | null {
  if (source === "yahoo") return "1D";
  if (source === "binance") return "1m";
  return null;
}

/** Duration in seconds for a catalog id, or null when unknown. */
export function timeframeSeconds(id: string): number | null {
  return TIMEFRAMES_BY_ID.get(id)?.seconds ?? null;
}

/**
 * Bucket-aligned OHLCV aggregation.
 *
 * Each bucket starts at `floor(t / bucketMs) * bucketMs`; open = first bar's
 * open, high = max, low = min, close = last bar's close, volume = sum.
 * Buckets with no bars are skipped (empty gaps stay gaps). The result is
 * ascending by bucket start; the input is never mutated.
 *
 * When the bucket is not coarser than the source spacing (or the input is
 * too short for resampling to mean anything), a sorted copy of the input is
 * returned instead.
 */
export function resampleBars(bars: Bar[], targetSeconds: number): Bar[] {
  const sorted = [...bars].sort((a, b) => a.t - b.t);
  if (bars.length === 0 || !Number.isFinite(targetSeconds) || targetSeconds <= 0) {
    return sorted;
  }
  if (sorted.length < 2) {
    return sorted;
  }

  // Source granularity = smallest positive gap between neighbors. Using the
  // minimum keeps the passthrough test conservative on irregular series.
  let sourceSpacing = Number.POSITIVE_INFINITY;
  for (let i = 1; i < sorted.length; i += 1) {
    const gap = sorted[i].t - sorted[i - 1].t;
    if (gap > 0 && gap < sourceSpacing) {
      sourceSpacing = gap;
    }
  }
  const bucketMs = targetSeconds * 1000;
  if (!Number.isFinite(sourceSpacing) || bucketMs <= sourceSpacing) {
    return sorted;
  }

  const out: Bar[] = [];
  let current: Bar | null = null;
  for (const bar of sorted) {
    const bucketStart = Math.floor(bar.t / bucketMs) * bucketMs;
    if (current === null || current.t !== bucketStart) {
      if (current !== null) {
        out.push(current);
      }
      current = { t: bucketStart, o: bar.o, h: bar.h, l: bar.l, c: bar.c, v: bar.v };
    } else {
      if (bar.h > current.h) {
        current.h = bar.h;
      }
      if (bar.l < current.l) {
        current.l = bar.l;
      }
      current.c = bar.c;
      current.v += bar.v;
    }
  }
  if (current !== null) {
    out.push(current);
  }
  return out;
}
