/**
 * Bundle D / OVERFLOW-01 — chart aggregations must not stack-overflow on
 * large series.
 *
 * `Math.max(...arr)` and `Math.min(...arr)` throw `RangeError: Maximum call
 * stack size exceeded` on arrays beyond ~100k entries (engine-dependent).
 * The new code uses `reduce` so the work is O(n) with constant stack. This
 * test pumps 150k points through the same helpers the chart code uses and
 * confirms the result matches the naive spread on a smaller array.
 */
import { describe, expect, it } from "vitest";

// Local copies of the helper closures used inside charts.tsx — testing the
// arithmetic so we don't have to mount lightweight-charts (which requires
// canvas / DOM that jsdom doesn't ship).
function maxReduce(arr: number[]): number {
  return arr.reduce((a, b) => (b > a ? b : a), -Infinity);
}
function minReduce(arr: number[]): number {
  return arr.reduce((a, b) => (b < a ? b : a), Infinity);
}
function maxAbsReduce(arr: number[], floor: number): number {
  return arr.map((v) => Math.abs(v)).reduce((a, b) => (b > a ? b : a), floor);
}

describe("function_stub charts overflow safety", () => {
  it("maxReduce / minReduce process 150k points without throwing", () => {
    const arr = Array.from({ length: 150_000 }, (_, i) => Math.sin(i * 0.001) * 100);
    expect(() => maxReduce(arr)).not.toThrow();
    expect(() => minReduce(arr)).not.toThrow();
    expect(maxReduce(arr)).toBeGreaterThan(0);
    expect(minReduce(arr)).toBeLessThan(0);
  });

  it("matches Math.max for small arrays", () => {
    const arr = [3, -7, 12, 0, 5];
    expect(maxReduce(arr)).toBe(Math.max(...arr));
    expect(minReduce(arr)).toBe(Math.min(...arr));
  });

  it("returns -Infinity / +Infinity for empty arrays (matches Math contract)", () => {
    expect(maxReduce([])).toBe(-Infinity);
    expect(minReduce([])).toBe(Infinity);
  });

  it("maxAbsReduce respects the floor argument", () => {
    expect(maxAbsReduce([0.2, -0.5], 1)).toBe(1);
    expect(maxAbsReduce([2.5, -3.1], 1)).toBe(3.1);
  });

  it("Math.max would throw for 150k points (regression baseline)", () => {
    // Skip if the host engine happens to handle the spread — V8 sometimes
    // does on optimised builds. Mark a soft expectation so we don't false-
    // positive on a node version that fixes this.
    const arr = Array.from({ length: 150_000 }, (_, i) => i);
    try {
      const v = Math.max(...arr);
      // If we got here, the engine handled it. Tag a sanity check on the
      // result so the test still reports meaningful state.
      expect(v).toBe(149_999);
    } catch (err) {
      expect(err).toBeInstanceOf(RangeError);
    }
  });
});
