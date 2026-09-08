import { describe, expect, it } from "vitest";
import { listNativeCodes, mergeNativeFunctionIndex, resolvePane } from "./registry";
import { STATIC_FUNCTION_INDEX } from "./static-index";

describe("function pane registry", () => {
  // The COMPLETE native pane set, generated from registry.tsx's PANES map
  // (158 codes). This is an EXACT pin: deleting any registry entry fails CI
  // (the earlier pin stopped at wave-4's FRH, so deleting wave-5 codes such
  // as AV/BGAS/FXGO passed CI silently). Wave-6 must extend this list.
  const EXPECTED_PANE_CODES = [
    // A
    "ACCT", "AGENT", "AIM", "ALLQ", "ALRT", "ANR", "APPL", "ASK", "AV",
    // B
    "BBGT", "BDA", "BETA", "BGAS", "BIO", "BLAK", "BMC", "BMTX", "BOIL",
    "BOT", "BOTS", "BQL", "BQUANT", "BRIEF", "BTFW", "BTMM", "BTUNE",
    // C
    "CACT", "CDE", "CHGS", "CN", "CONN", "CORR", "COUN", "CPF", "CRPR",
    "CRVF", "CSRC",
    // D
    "DAPI", "DARK", "DCF", "DCFS", "DDM", "DDIS", "DEBT", "DINE", "DES",
    "DPF", "DVD",
    // E
    "ECFC", "ECST", "ECO", "EE", "EMSX", "EQS", "EREV", "ESG", "EVTS",
    "EXEC",
    // F
    "FA", "FLDS", "FLW", "FLY", "FORM4", "FRD", "FRH", "FTS", "FSRC",
    "FXFC", "FXGO", "FXH", "FXIP",
    // G
    "GC3D", "GEX", "GLCO", "GMM", "GP", "GRAB", "GREEKS",
    // H
    "HDS", "HFS", "HP", "HVT",
    // I
    "ICX", "INDX", "INSTANT", "ISIN", "IVOL",
    // L
    "LANG", "LITM", "LOTS",
    // M
    "MAP", "MARS", "MEET", "MGN", "MICRO", "MIS", "MLSIG", "MOSS", "MOST",
    // N
    "NALRT", "NGAS", "NI", "NSE",
    // O
    "OMON", "ONCH", "OSA", "OVME", "OVDV",
    // P
    "PCAS", "PEOP", "PERF", "PFA", "PIB", "POLY", "PORT", "PORT_OPT",
    "PORT_WHATIF", "PSC", "PVAR",
    // R
    "READ", "REBA", "REGM", "RPAR", "RV",
    // S
    "SAT", "SCAN", "SECF", "SECT", "SPLC", "SOSC", "SRSK", "SRCH", "STRA",
    "STRS",
    // T
    "TAUC", "TCA", "TECH", "TLDR", "TLH", "TMPL", "TOP", "TRA", "TRAN",
    "TRDH", "TRQA", "TSAR", "TSOX", "TXNS",
    // W / X / Y
    "WACC", "WATCH", "WB", "WCRS", "WEI", "WETR", "WHAL", "WIRP",
    "XSEN", "YAS",
  ];

  it("registers the COMPLETE native pane set (exact pin — deletions fail CI)", () => {
    const registered = listNativeCodes();
    expect(registered).toHaveLength(EXPECTED_PANE_CODES.length);
    expect(registered).toEqual([...EXPECTED_PANE_CODES].sort());
  });

  it("every registered pane resolves and is React.lazy (round-2b contract)", () => {
    const REACT_LAZY = Symbol.for("react.lazy");
    expect(EXPECTED_PANE_CODES.length).toBeGreaterThan(150);
    for (const code of EXPECTED_PANE_CODES) {
      const pane = resolvePane(code);
      expect(pane, `pane ${code} missing from the PANES map`).not.toBeNull();
      expect(
        (pane as unknown as { $$typeof?: symbol }).$$typeof,
        `pane ${code} is not a React.lazy component`,
      ).toBe(REACT_LAZY);
    }
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

  it("resolves TECH to the bespoke technical-indicator pane (FN-WAVE)", () => {
    expect(resolvePane("TECH")).toBeTruthy();
  });

  it("resolves TXNS to the Trade Blotter pane", () => {
    expect(resolvePane("TXNS")).toBeTruthy();
  });

  it("resolves TRAN to the bespoke transcript pane (FN-WAVE)", () => {
    expect(resolvePane("TRAN")).toBeTruthy();
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

describe("157-function merged catalog invariant", () => {
  // The static index ships 142 codes from the backend catalog; the native
  // registry contributes 15 codes not in the static index (AGENT, ASK,
  // BDA, BOT, BOTS, CONN, INDX, INSTANT, MIS, PERF, STRA, TMPL, WATCH,
  // XSEN, TXNS — CN and FLW overlap and are dedup'd). Total 157. This is
  // the contract the sidebar, command palette, and FunctionStub fallback
  // all depend on. CONN was added in T9 of the multi-exchange portfolio foundation;
  // INDX was added in F4 of the indicator-depot sub-system; STRA was
  // added in E5 of the strategy sub-system; BOT was added in D5 of the
  // bot sub-system; TMPL was added in G3 of the template-bot library
  // sub-system; BOTS was added in H2 of the bot-supervision sub-system;
  // PERF was added in I2 of the cumulative-performance sub-system; BDA
  // was added in J1 of the NL-assistant sub-system; TXNS was added to clear
  // collision with TRAN; FLW (FlowMap depth heatmap) joined the static
  // index as a native pane. All are native panes with no backend-side stub fallback.
  const NATIVE_ONLY = ["AGENT", "ASK", "BDA", "BOT", "BOTS", "CONN", "INDX", "INSTANT", "MIS", "PERF", "STRA", "TMPL", "WATCH", "XSEN", "TXNS"];

  it("static index is exactly 142 entries", () => {
    expect(STATIC_FUNCTION_INDEX).toHaveLength(142);
  });

  it("merged catalog is exactly 157 entries", () => {
    expect(mergeNativeFunctionIndex(STATIC_FUNCTION_INDEX)).toHaveLength(157);
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
