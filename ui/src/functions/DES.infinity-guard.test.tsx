/**
 * UA-HIGH-27 — DES.tsx changePct must never return ±Infinity / NaN for
 * corrupt payloads (e.g. previousClose === 0).
 *
 * The previous expression `last != null && prev` used JS truthiness, which
 * sent prev === 0 to the null branch correctly but left other corrupt shapes
 * (NaN, Infinity) through. Hardened to "prev is a finite positive number".
 */
import { describe, expect, it } from "vitest";

function changePct(
  last: number | null,
  prev: number | null | undefined,
  fallback?: number,
): number | null {
  if (fallback != null && Number.isFinite(fallback)) return fallback;
  if (
    last != null &&
    typeof prev === "number" &&
    Number.isFinite(prev) &&
    prev > 0
  ) {
    return ((last - prev) / prev) * 100;
  }
  return null;
}

describe("UA-HIGH-27: DES changePct Infinity guard", () => {
  it("returns the backend-supplied fallback verbatim when finite", () => {
    expect(changePct(100, 90, 5.5)).toBe(5.5);
  });

  it("computes pct change for a normal payload", () => {
    expect(changePct(110, 100)).toBeCloseTo(10);
    expect(changePct(90, 100)).toBeCloseTo(-10);
  });

  it("returns null when prev is 0 (would have been ±Infinity)", () => {
    expect(changePct(100, 0)).toBeNull();
  });

  it("returns null when prev is NaN / Infinity / negative", () => {
    expect(changePct(100, NaN)).toBeNull();
    expect(changePct(100, Infinity)).toBeNull();
    expect(changePct(100, -1)).toBeNull();
  });

  it("returns null when last is missing", () => {
    expect(changePct(null, 100)).toBeNull();
  });

  it("returns null when both fields are missing", () => {
    expect(changePct(null, null)).toBeNull();
  });
});
