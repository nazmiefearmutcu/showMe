/**
 * HFS#3: pct_outstanding is a fraction of shares outstanding. The formatter
 * must not guess the unit from magnitude; out-of-range values are missing.
 */
import { describe, expect, it } from "vitest";
import { fmtPctOut } from "./HFS";

describe("HFS pct_outstanding unit (HFS#3)", () => {
  it("renders a fraction as a percent", () => {
    expect(fmtPctOut(0.087)).toBe("8.70%");
    expect(fmtPctOut(0.069)).toBe("6.90%");
    expect(fmtPctOut(1)).toBe("100.00%");
    expect(fmtPctOut(0)).toBe("0.00%");
  });

  it("does not rescale values above 1 as if they were percent units", () => {
    // Old heuristic: 2.5 (|v| > 1.5) was shown as "2.50%" and 1.2 as "120%".
    // A share of outstanding shares cannot exceed 1, so both are missing.
    expect(fmtPctOut(2.5)).toBe("—");
    expect(fmtPctOut(1.2)).toBe("—");
  });

  it("renders negative and non-numeric values as missing", () => {
    expect(fmtPctOut(-0.01)).toBe("—");
    expect(fmtPctOut(null)).toBe("—");
    expect(fmtPctOut(undefined)).toBe("—");
    expect(fmtPctOut("n/a")).toBe("—");
  });
});
