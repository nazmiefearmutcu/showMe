import { describe, expect, it } from "vitest";
import {
  formatCompactNumber,
  formatCurrency,
  formatMissing,
  formatNumber,
  formatPercent,
  formatPrice,
  formatSignedCurrency,
  formatSignedDelta,
} from "./format";

describe("formatMissing", () => {
  it("is a single em-dash", () => {
    expect(formatMissing).toBe("—");
  });
});

describe("formatCurrency", () => {
  it("renders compact USD with sign before symbol", () => {
    expect(formatCurrency(-1_500_000_000, { compact: true })).toBe("-$1.5B");
  });

  it("renders standard positive USD with no fraction by default", () => {
    expect(formatCurrency(1234)).toBe("$1,234");
  });

  it("respects override fraction digits", () => {
    expect(formatCurrency(1.234, { fractionDigits: 2 })).toBe("$1.23");
  });

  it("treats explicit fractionDigits as the minimum too (trailing zeros)", () => {
    expect(formatCurrency(302.5, { fractionDigits: 2 })).toBe("$302.50");
    expect(formatCurrency(5, { fractionDigits: 2 })).toBe("$5.00");
  });

  it("keeps min-0 (no trailing zeros) when fractionDigits is omitted", () => {
    expect(formatCurrency(302.5)).toBe("$303");
    expect(formatCurrency(1234)).toBe("$1,234");
  });

  it("does not pad compact notation min digits", () => {
    // Compact path is left untouched even with explicit fractionDigits.
    expect(formatCurrency(1_200_000_000, { compact: true })).toBe("$1.2B");
    expect(formatCurrency(1_000_000_000, { compact: true, fractionDigits: 2 })).toBe(
      "$1B",
    );
  });

  it("returns em-dash for null / undefined / NaN / Infinity", () => {
    expect(formatCurrency(null)).toBe(formatMissing);
    expect(formatCurrency(undefined)).toBe(formatMissing);
    expect(formatCurrency(Number.NaN)).toBe(formatMissing);
    expect(formatCurrency(Number.POSITIVE_INFINITY)).toBe(formatMissing);
  });
});

describe("formatCompactNumber", () => {
  it("renders compact magnitudes with up to 2 decimals", () => {
    expect(formatCompactNumber(1_234_567)).toBe("1.23M");
  });

  it("returns em-dash for non-finite", () => {
    expect(formatCompactNumber(Number.NaN)).toBe(formatMissing);
  });

  it("pads to fixed digits for jitter-free grid columns", () => {
    expect(formatCompactNumber(3_500_000, { fixedDigits: 2 })).toBe("3.50M");
    expect(formatCompactNumber(1_200_000_000, { fixedDigits: 2 })).toBe("1.20B");
  });
});

describe("formatSignedCurrency", () => {
  it("adds a leading + for positive values", () => {
    expect(formatSignedCurrency(4.39)).toBe("+$4");
  });

  it("adds a leading - for negative values (sign before symbol)", () => {
    expect(formatSignedCurrency(-16.5)).toMatch(/^-\$1[67]$/);
  });

  it("renders zero without a sign", () => {
    expect(formatSignedCurrency(0)).toBe("$0");
  });

  it("returns em-dash for non-finite", () => {
    expect(formatSignedCurrency(null)).toBe(formatMissing);
    expect(formatSignedCurrency(Number.NaN)).toBe(formatMissing);
  });
});

describe("formatPercent", () => {
  it("renders with two decimals by default", () => {
    expect(formatPercent(0.42)).toBe("0.42%");
  });

  it("multiplies by 100 when fromFraction:true", () => {
    expect(formatPercent(0.42, { fromFraction: true })).toBe("42.00%");
  });

  it("renders negative percent untouched", () => {
    expect(formatPercent(-1.23)).toBe("-1.23%");
  });

  it("adds + sign for positive when signed:true", () => {
    expect(formatPercent(1.23, { signed: true })).toBe("+1.23%");
  });

  it("returns em-dash for non-finite", () => {
    expect(formatPercent(null)).toBe(formatMissing);
  });
});

describe("formatSignedDelta", () => {
  it("renders negative with explicit minus and given precision", () => {
    expect(formatSignedDelta(-0.273, 3)).toBe("-0.273");
  });

  it("renders zero without a sign", () => {
    expect(formatSignedDelta(0)).toBe("0.00");
  });

  it("renders positive with explicit plus", () => {
    expect(formatSignedDelta(1.5)).toBe("+1.50");
  });

  it("returns em-dash for non-finite", () => {
    expect(formatSignedDelta(Number.NaN)).toBe(formatMissing);
  });
});

describe("formatPrice", () => {
  it("uses 2 dp for prices >= 1", () => {
    expect(formatPrice(123.456)).toBe("123.46");
  });

  it("uses 4 dp for prices in [0.01, 1)", () => {
    expect(formatPrice(0.5432)).toBe("0.5432");
  });

  it("uses 6 dp for prices in [0.0001, 0.01)", () => {
    expect(formatPrice(0.00123456)).toBe("0.001235");
  });

  it("falls back to scientific for sub-cent (sub 0.0001) prices", () => {
    expect(formatPrice(0.00000123)).toBe("1.23e-6");
  });

  it("returns em-dash for NaN / Infinity / null", () => {
    expect(formatPrice(Number.NaN)).toBe(formatMissing);
    expect(formatPrice(Number.POSITIVE_INFINITY)).toBe(formatMissing);
    expect(formatPrice(null)).toBe(formatMissing);
  });
});

describe("formatNumber", () => {
  it("uses en-US thousands separators", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
  });

  it("respects fraction-digit override", () => {
    expect(formatNumber(1.5, 2)).toBe("1.5");
  });

  it("keeps trailing zeros when minimumFractionDigits is requested", () => {
    expect(formatNumber(2.1, 2, { minimumFractionDigits: 2 })).toBe("2.10");
    expect(formatNumber(3, 2, { minimumFractionDigits: 2 })).toBe("3.00");
    expect(formatNumber(-1.5, 2, { minimumFractionDigits: 2 })).toBe("-1.50");
  });

  it("default (no minimumFractionDigits) still trims trailing zeros", () => {
    expect(formatNumber(2.1, 2)).toBe("2.1");
    expect(formatNumber(3, 2)).toBe("3");
  });

  it("returns em-dash for non-finite", () => {
    expect(formatNumber(undefined)).toBe(formatMissing);
  });
});
