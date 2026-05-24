/**
 * UA-CRITICAL-01 — HP/GP chart `Math.max(...arr)` spread overflow regression.
 *
 * Validates that the shared `maxOf` / `minOf` helpers process 150k points
 * without throwing `RangeError: Maximum call stack size exceeded`. These
 * helpers are now consumed by HP.tsx, GP.tsx, WACC.tsx, PERF.tsx, BTMM.tsx,
 * MOST.tsx, WEI.tsx, XSEN.tsx, MarketHeatmap.tsx, SCAN.tsx — anywhere a
 * chart series can cross ~100k points.
 */
import { describe, expect, it } from "vitest";
import { maxOf, minOf, maxAbsOf } from "@/lib/maxOf";

describe("UA-CRITICAL-01: HP/GP chart overflow safety", () => {
  it("maxOf / minOf process 150k points without throwing", () => {
    const arr = Array.from({ length: 150_000 }, (_, i) => Math.sin(i * 0.001) * 100);
    expect(() => maxOf(arr)).not.toThrow();
    expect(() => minOf(arr)).not.toThrow();
    expect(maxOf(arr)).toBeGreaterThan(0);
    expect(minOf(arr)).toBeLessThan(0);
  });

  it("maxOf / minOf match Math.max/min on small arrays", () => {
    const arr = [3, -7, 12, 0, 5];
    expect(maxOf(arr)).toBe(Math.max(...arr));
    expect(minOf(arr)).toBe(Math.min(...arr));
  });

  it("maxOf returns -Infinity for empty, minOf returns +Infinity (Math contract)", () => {
    expect(maxOf([])).toBe(-Infinity);
    expect(minOf([])).toBe(Infinity);
  });

  it("maxAbsOf respects the floor argument", () => {
    expect(maxAbsOf([0.2, -0.5], 1)).toBe(1);
    expect(maxAbsOf([2.5, -3.1], 1)).toBe(3.1);
    expect(maxAbsOf([], 0)).toBe(0);
  });

  it("maxAbsOf handles 100k mixed-sign values", () => {
    const arr = Array.from({ length: 100_000 }, (_, i) => (i % 2 ? -i : i));
    expect(() => maxAbsOf(arr, 0)).not.toThrow();
    expect(maxAbsOf(arr, 0)).toBe(99_999);
  });
});
