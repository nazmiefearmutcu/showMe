/**
 * Bug #18 — TECH-LG preset scanned only 5 hardcoded stocks because
 * `parseUniverse("SP500")` returned `null` and the backend short-circuited
 * to its 5-row sample.
 *
 * Now `parseUniverse` resolves named universes from a static JSON list and
 * returns the full constituent array.
 */
import { describe, expect, it } from "vitest";
import { parseUniverse, NAMED_UNIVERSES } from "../EQS";

describe("EQS parseUniverse — Bug #18", () => {
  it("returns the full SP500 constituents for the SP500 alias", () => {
    const result = parseUniverse("SP500");
    expect(result).not.toBeNull();
    expect(Array.isArray(result)).toBe(true);
    expect(result!.length).toBeGreaterThanOrEqual(400);
    // Sanity: a few canonical SP500 names must be present.
    expect(result).toContain("AAPL");
    expect(result).toContain("MSFT");
    expect(result).toContain("BRK.B");
  });

  it("SP500 lookup is case-insensitive", () => {
    expect(parseUniverse("sp500")).toEqual(parseUniverse("SP500"));
    expect(parseUniverse("Sp500")).toEqual(parseUniverse("SP500"));
  });

  it("returns null for an empty string (use backend default)", () => {
    expect(parseUniverse("")).toBeNull();
    expect(parseUniverse("   ")).toBeNull();
  });

  it("parses comma-/whitespace-delimited tickers", () => {
    expect(parseUniverse("AAPL, MSFT, NVDA")).toEqual(["AAPL", "MSFT", "NVDA"]);
    expect(parseUniverse("aapl msft  nvda")).toEqual(["AAPL", "MSFT", "NVDA"]);
  });

  it("returned arrays are independent copies (defensive)", () => {
    const a = parseUniverse("SP500");
    const b = parseUniverse("SP500");
    expect(a).not.toBe(b);
    a!.push("FAKE");
    expect(b).not.toContain("FAKE");
  });

  it("named-universe table is exported and non-empty", () => {
    expect(NAMED_UNIVERSES).toHaveProperty("SP500");
    expect(NAMED_UNIVERSES.SP500.length).toBeGreaterThanOrEqual(400);
  });
});
