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
    // Round-2B: registry returns React.lazy()-wrapped components (objects with
    // $$typeof = react.lazy), not raw function components.
    const upper = resolvePane("DES");
    const lower = resolvePane("des");
    expect(upper).toBeTruthy();
    expect(lower).toBeTruthy();
    expect(lower).toBe(upper);
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

describe("150-function merged catalog invariant", () => {
  // The static index ships 141 codes from the backend catalog; the native
  // registry contributes 9 codes not in the static index (AGENT, ASK,
  // CONN, INDX, INSTANT, MIS, STRA, WATCH, XSEN — CN overlaps and is
  // dedup'd). Total 150. This is the contract the sidebar, command
  // palette, and FunctionStub fallback all depend on. CONN was added in
  // T9 of the multi-exchange portfolio foundation; INDX was added in F4
  // of the indicator-depot sub-system; STRA was added in E5 of the
  // strategy sub-system. All are native panes with no backend-side stub
  // fallback.
  const NATIVE_ONLY = ["AGENT", "ASK", "CONN", "INDX", "INSTANT", "MIS", "STRA", "WATCH", "XSEN"];

  it("static index is exactly 141 entries", () => {
    expect(STATIC_FUNCTION_INDEX).toHaveLength(141);
  });

  it("merged catalog is exactly 150 entries", () => {
    expect(mergeNativeFunctionIndex(STATIC_FUNCTION_INDEX)).toHaveLength(150);
  });

  it("every native-only entry is appended after merge", () => {
    const codes = new Set(
      mergeNativeFunctionIndex(STATIC_FUNCTION_INDEX).map((e) => e.code),
    );
    for (const code of NATIVE_ONLY) {
      expect(codes.has(code)).toBe(true);
    }
  });

  it("every merged code resolves to a surface (native pane or stub fallback)", () => {
    // Resolution is total: resolvePane returns either a lazy component or
    // null. Null is the FunctionStub fallback path; that still counts as a
    // working surface.
    const merged = mergeNativeFunctionIndex(STATIC_FUNCTION_INDEX);
    for (const entry of merged) {
      const pane = resolvePane(entry.code);
      expect(pane === null || typeof pane === "object").toBe(true);
    }
  });
});
