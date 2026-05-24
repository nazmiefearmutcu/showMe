/**
 * Round 24 HIGH 8 — ALRT threshold validation regression.
 *
 * The old `Number(threshold)` coercion silently accepted:
 *  - "1e500" → Infinity (real bug: persisted as JSON Infinity).
 *  - "Infinity" / "-Infinity" → non-finite numbers.
 *  - "abc" → NaN (saved as null on JSON.stringify, broke alert engine).
 *
 * `parseDecimalSafe()` rejects all of these explicitly so the form can
 * show a TR-language error instead of writing a corrupt row.
 *
 * Also covers `isFiniteNumber` / `isPositive` helpers.
 */
import { describe, expect, it } from "vitest";
import {
  isFiniteNumber,
  isPositive,
  parseDecimalSafe,
} from "@/lib/validators";

describe("parseDecimalSafe — Round 24 HIGH 8", () => {
  it("accepts integers + decimals", () => {
    expect(parseDecimalSafe("200")).toEqual({ ok: true, value: 200 });
    expect(parseDecimalSafe("0.001")).toEqual({ ok: true, value: 0.001 });
    expect(parseDecimalSafe("-12.5")).toEqual({ ok: true, value: -12.5 });
    expect(parseDecimalSafe(42)).toEqual({ ok: true, value: 42 });
  });

  it("rejects empty / whitespace as empty (distinct from invalid)", () => {
    expect(parseDecimalSafe("")).toEqual({ ok: false, reason: "empty" });
    expect(parseDecimalSafe("   ")).toEqual({ ok: false, reason: "empty" });
    expect(parseDecimalSafe(null)).toEqual({ ok: false, reason: "empty" });
    expect(parseDecimalSafe(undefined)).toEqual({ ok: false, reason: "empty" });
  });

  it("rejects garbage as not_a_number", () => {
    expect(parseDecimalSafe("abc")).toEqual({ ok: false, reason: "not_a_number" });
    expect(parseDecimalSafe("12abc")).toEqual({ ok: false, reason: "not_a_number" });
    expect(parseDecimalSafe("1.2.3")).toEqual({ ok: false, reason: "not_a_number" });
    expect(parseDecimalSafe(NaN)).toEqual({ ok: false, reason: "not_a_number" });
    expect(parseDecimalSafe({} as unknown)).toEqual({ ok: false, reason: "not_a_number" });
  });

  it("rejects Infinity / 1e500 / -Infinity as not_finite (THE REAL BUG)", () => {
    expect(parseDecimalSafe("Infinity")).toEqual({ ok: false, reason: "not_finite" });
    expect(parseDecimalSafe("-Infinity")).toEqual({ ok: false, reason: "not_finite" });
    expect(parseDecimalSafe("1e500")).toEqual({ ok: false, reason: "not_finite" });
    expect(parseDecimalSafe(Infinity)).toEqual({ ok: false, reason: "not_finite" });
    expect(parseDecimalSafe(-Infinity)).toEqual({ ok: false, reason: "not_finite" });
  });
});

describe("isFiniteNumber + isPositive helpers", () => {
  it("isFiniteNumber rejects non-finite values", () => {
    expect(isFiniteNumber(0)).toBe(true);
    expect(isFiniteNumber(-1)).toBe(true);
    expect(isFiniteNumber(NaN)).toBe(false);
    expect(isFiniteNumber(Infinity)).toBe(false);
    expect(isFiniteNumber(-Infinity)).toBe(false);
    expect(isFiniteNumber("1")).toBe(false);
    expect(isFiniteNumber(null)).toBe(false);
  });

  it("isPositive requires strictly > 0 + finite", () => {
    expect(isPositive(1)).toBe(true);
    expect(isPositive(0.001)).toBe(true);
    expect(isPositive(0)).toBe(false);
    expect(isPositive(-1)).toBe(false);
    expect(isPositive(NaN)).toBe(false);
    expect(isPositive(Infinity)).toBe(false);
  });
});
