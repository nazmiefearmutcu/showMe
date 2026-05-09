import { describe, expect, it } from "vitest";
import { listNativeCodes, mergeNativeFunctionIndex, resolvePane } from "./registry";
import { STATIC_FUNCTION_INDEX } from "./static-index";

describe("function pane registry", () => {
  it("includes Rounds 14/17/19 + Round-23/24/25 panes", () => {
    expect(listNativeCodes()).toEqual(
      expect.arrayContaining([
        "DES", "FA", "GP", "EQS", "PORT", "SCAN", "ASK",
        "TOP", "ECO", "WATCH", "ALRT", "ANR",
        "NI", "CN", "MOST", "WEI", "HP",
        "WCRS", "GLCO", "BTMM", "AGENT",
        "MAP", "SECT", "BIO", "CORR",
      ]),
    );
  });

  it("resolves canonical and lower-case codes", () => {
    expect(resolvePane("DES")).toBeTypeOf("function");
    expect(resolvePane("des")).toBeTypeOf("function");
  });

  it("lets TECH fall back to the generic technical-indicator function", () => {
    expect(resolvePane("TECH")).toBeNull();
  });

  it("treats CN as an alias for NI (Round 24)", () => {
    expect(resolvePane("CN")).toBe(resolvePane("NI"));
  });

  it("lets TRAN fall back to the earnings transcript function", () => {
    expect(resolvePane("TRAN")).toBeNull();
  });

  it("adds native-only panes to a backend function index", () => {
    const merged = mergeNativeFunctionIndex([
      { code: "BETA", name: "Beta", category: "equity", description: "Live beta" },
    ]);
    expect(merged.map((entry) => entry.code)).toEqual(
      expect.arrayContaining(["BETA", "WATCH", "AGENT"]),
    );
  });

  it("ships a static backend index fallback for first-paint navigation", () => {
    expect(STATIC_FUNCTION_INDEX.length).toBeGreaterThan(100);
    expect(STATIC_FUNCTION_INDEX.map((entry) => entry.code)).toEqual(
      expect.arrayContaining(["BETA", "CN", "GP", "ACCT"]),
    );
  });

  it("returns null for unknown codes (caller falls back to FunctionStub)", () => {
    expect(resolvePane("ZZZ")).toBeNull();
  });
});
