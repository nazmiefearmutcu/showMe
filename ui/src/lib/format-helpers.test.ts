/**
 * Wave 2 / Agent G — adaptive precision contract tests.
 *
 * The QA report (Section 50) flagged PENGU at $0.000620 rendering as
 * "0.00" on chart axes and "$0.00" in panes. The helpers below back the
 * fixes; this suite pins their behaviour so a future static-precision
 * regression is caught immediately.
 */

import { describe, expect, it } from "vitest";
import { formatMissing } from "./format";
import {
  formatAdaptive,
  getCandlePriceFormat,
  getDecimalsForPrice,
} from "./format-helpers";

describe("getDecimalsForPrice", () => {
  it("returns 2 dp for prices >= 1", () => {
    expect(getDecimalsForPrice(123.45)).toBe(2);
    expect(getDecimalsForPrice(1)).toBe(2);
  });

  it("returns 4 dp for prices in [0.01, 1)", () => {
    expect(getDecimalsForPrice(0.5)).toBe(4);
    expect(getDecimalsForPrice(0.01)).toBe(4);
  });

  it("returns 6 dp for prices in [0.0001, 0.01)", () => {
    expect(getDecimalsForPrice(0.005)).toBe(6);
    expect(getDecimalsForPrice(0.0001)).toBe(6);
  });

  it("returns 6 dp for PENGU-class $0.000620 (sub-cent crypto)", () => {
    // 0.000620 is in [1e-4, 1e-2) so the 6-dp band keeps full precision:
    // "0.00062" — the QA failure mode was 2-dp rounding to "0.00".
    expect(getDecimalsForPrice(0.000620)).toBe(6);
  });

  it("returns 8 dp for sub-1e-4 magnitudes", () => {
    expect(getDecimalsForPrice(5e-5)).toBe(8);
    expect(getDecimalsForPrice(1e-8)).toBe(8);
  });

  it("returns 10 dp for ultra-small magnitudes < 1e-8", () => {
    expect(getDecimalsForPrice(1e-9)).toBe(10);
  });

  it("returns safe default 2 dp for non-finite / null", () => {
    expect(getDecimalsForPrice(null)).toBe(2);
    expect(getDecimalsForPrice(undefined)).toBe(2);
    expect(getDecimalsForPrice(Number.NaN)).toBe(2);
    expect(getDecimalsForPrice(Number.POSITIVE_INFINITY)).toBe(2);
  });

  it("treats negative prices by magnitude (sign-agnostic)", () => {
    expect(getDecimalsForPrice(-0.000620)).toBe(6);
    expect(getDecimalsForPrice(-5e-5)).toBe(8);
  });
});

describe("getCandlePriceFormat", () => {
  it("returns lightweight-charts shape", () => {
    const fmt = getCandlePriceFormat(123.45);
    expect(fmt.type).toBe("price");
    expect(fmt.precision).toBe(2);
    expect(fmt.minMove).toBeCloseTo(0.01, 10);
  });

  it("tracks precision = 6 / minMove = 1e-6 for PENGU-class $0.000620", () => {
    const fmt = getCandlePriceFormat(0.000620);
    expect(fmt.precision).toBe(6);
    expect(fmt.minMove).toBeCloseTo(1e-6, 12);
  });

  it("tracks precision = 8 / minMove = 1e-8 for sub-1e-4 magnitudes", () => {
    const fmt = getCandlePriceFormat(5e-5);
    expect(fmt.precision).toBe(8);
    expect(fmt.minMove).toBeCloseTo(1e-8, 12);
  });

  it("handles non-finite by emitting the safe precision 2 / minMove 0.01", () => {
    const fmt = getCandlePriceFormat(Number.NaN);
    expect(fmt.precision).toBe(2);
    expect(fmt.minMove).toBeCloseTo(0.01, 10);
  });
});

describe("formatAdaptive", () => {
  it("renders sub-cent crypto without collapsing to 0", () => {
    // PENGU $0.000620 must keep its precision.
    expect(formatAdaptive(0.000620)).toBe("0.00062");
  });

  it("uses 2 dp for prices >= 1", () => {
    expect(formatAdaptive(1234.5678)).toBe("1,234.57");
  });

  it("returns the em-dash sentinel for non-finite / null", () => {
    expect(formatAdaptive(null)).toBe(formatMissing);
    expect(formatAdaptive(undefined)).toBe(formatMissing);
    expect(formatAdaptive(Number.NaN)).toBe(formatMissing);
  });
});
