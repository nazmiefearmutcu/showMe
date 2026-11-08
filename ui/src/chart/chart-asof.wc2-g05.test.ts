/**
 * WC2-G05 / ASOF-2: the chart legend time is the newest bar's open time, not the
 * envelope asOf (which /api/bars stamps with the serve time).
 */
import { describe, expect, it } from "vitest";
import { lastBarObservedIso } from "./chart-asof";

describe("lastBarObservedIso (WC2-G05 ASOF-2)", () => {
  it("returns null when there are no bars", () => {
    expect(lastBarObservedIso([])).toBeNull();
  });

  it("uses the newest bar open time, not a serve-time stamp", () => {
    const bars = [
      { t: Date.UTC(2026, 8, 14, 0, 0) },
      { t: Date.UTC(2026, 8, 15, 13, 30) },
    ];
    expect(lastBarObservedIso(bars)).toBe("2026-09-15T13:30:00.000Z");
  });

  it("returns null for a non-finite bar time instead of inventing one", () => {
    expect(lastBarObservedIso([{ t: Number.NaN }])).toBeNull();
  });
});
