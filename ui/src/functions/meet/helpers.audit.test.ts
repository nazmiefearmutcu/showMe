import { describe, expect, it } from "vitest";
import { formatPrint, surpriseOf } from "./helpers";

describe("MEET audit: units and exact surprise", () => {
  it("does not repeat a unit already carried by the source", () => {
    expect(formatPrint("3.9%", "%")).toBe("3.9%");
    expect(formatPrint("180K", "K")).toBe("180K");
    expect(formatPrint("1.4M", "K")).toBe("1.4M");
    expect(formatPrint(3.9, "%")).toBe("3.9%");
  });
  it("rejects arithmetic across percentage and absolute prints", () => {
    expect(surpriseOf({ actual: "3%", forecast: "2M" })).toBeNull();
    expect(surpriseOf({ actual: "3%", forecast: "2" })).toBeNull();
  });
  it("compares compatible scaled prints and percentage prints", () => {
    expect(surpriseOf({ actual: "1M", forecast: "900K" })).toBe(100000);
    expect(surpriseOf({ actual: "3%", forecast: "2%" })).toBe(1);
    expect(surpriseOf({ actual: "+1m", forecast: "900k" })).toBe(100000);
    expect(formatPrint("N/A", "%")).toBe("N/A");
  });
});
