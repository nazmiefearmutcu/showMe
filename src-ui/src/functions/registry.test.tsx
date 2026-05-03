import { describe, expect, it } from "vitest";
import { listNativeCodes, mergeNativeFunctionIndex, resolvePane } from "./registry";
import { STATIC_FUNCTION_INDEX } from "./static-index";

describe("function pane registry", () => {
  it("includes Rounds 14/17/19 + Round-23/24/25 panes", () => {
    expect(listNativeCodes()).toEqual(
      expect.arrayContaining([
        "DES", "FA", "GP", "TECH", "EQS", "PORT", "SCAN", "ASK",
        "TOP", "ECO", "WATCH", "ALRT",
        "NI", "CN", "MOST", "WEI", "HP",
        "TRAN", "WCRS", "GLCO", "BTMM", "AGENT",
      ]),
    );
  });

  it("resolves canonical and lower-case codes", () => {
    expect(resolvePane("DES")).toBeTypeOf("function");
    expect(resolvePane("des")).toBeTypeOf("function");
  });

  it("treats TECH as an alias for GP", () => {
    expect(resolvePane("TECH")).toBe(resolvePane("GP"));
  });

  it("treats CN as an alias for NI (Round 24)", () => {
    expect(resolvePane("CN")).toBe(resolvePane("NI"));
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
