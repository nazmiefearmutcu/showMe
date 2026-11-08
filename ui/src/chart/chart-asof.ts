import type { Bar } from "./types";

/**
 * ISO time of the newest bar (bar open time, epoch ms), or null when there is
 * no bar or its time is not a finite number. Used for the chart legend time:
 * the /api/bars envelope asOf is the serve time, not the data time.
 */
export function lastBarObservedIso(bars: ReadonlyArray<Pick<Bar, "t">>): string | null {
  const last = bars[bars.length - 1];
  if (!last || !Number.isFinite(last.t)) return null;
  const d = new Date(last.t);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
