/**
 * S05 — pane-completeness inventory regression.
 *
 * Pins the inventory contract so future catalog churn cannot silently
 * regress the critical-pane guarantees:
 *   • no duplicate codes
 *   • the derived inventory covers every design-catalog code
 *   • every CRITICAL_CODES entry has the correct readiness flag set
 *   • a stubbed "missing critical native" actually emits the
 *     "critical-missing" branch with the "high" synthetic-risk tag
 *   • the readiness mapping is a pure function of the renderer choice
 *
 * No React tree is mounted — the inventory is a deterministic derivation
 * over the registry / templates / design-export modules, so a unit test
 * is the right fidelity.
 */
import { describe, expect, it } from "vitest";
import {
  CRITICAL_CODES,
  criticalInventory,
  isCriticalCode,
  paneInventory,
  readinessFlags,
  resolvePaneRenderer,
  type PaneInventoryEntry,
  type PaneRendererChoice,
} from "./pane-completeness";
import {
  DESIGN_BASIC_CODES,
  DESIGN_PRO_CODES,
} from "@/design-export/showme-design-export";

describe("CRITICAL_CODES", () => {
  it("contains exactly the 10 codes S05 lists", () => {
    expect([...CRITICAL_CODES]).toEqual([
      "GP",
      "HP",
      "DES",
      "WATCH",
      "SCAN",
      "PORT",
      "TOP",
      "NI",
      "CN",
      "MIS",
    ]);
  });

  it("isCriticalCode is case-insensitive", () => {
    for (const code of CRITICAL_CODES) {
      expect(isCriticalCode(code)).toBe(true);
      expect(isCriticalCode(code.toLowerCase())).toBe(true);
    }
    expect(isCriticalCode("HOME")).toBe(false);
    expect(isCriticalCode("ZZZZ")).toBe(false);
  });
});

describe("paneInventory", () => {
  const inventory = paneInventory();

  it("contains no duplicate codes", () => {
    const codes = inventory.map((entry) => entry.code);
    const unique = new Set(codes);
    expect(codes.length).toBe(unique.size);
  });

  it("is sorted by code so snapshots are stable", () => {
    const codes = inventory.map((entry) => entry.code);
    const sorted = [...codes].sort();
    expect(codes).toEqual(sorted);
  });

  it("covers every DESIGN_PRO_CODES entry", () => {
    const known = new Set(inventory.map((entry) => entry.code));
    for (const code of DESIGN_PRO_CODES) {
      expect(known.has(code.toUpperCase())).toBe(true);
    }
  });

  it("covers every DESIGN_BASIC_CODES entry", () => {
    const known = new Set(inventory.map((entry) => entry.code));
    for (const code of DESIGN_BASIC_CODES) {
      expect(known.has(code.toUpperCase())).toBe(true);
    }
  });

  it("includes every CRITICAL_CODES entry even if catalog drift removes it elsewhere", () => {
    const known = new Set(inventory.map((entry) => entry.code));
    for (const code of CRITICAL_CODES) {
      expect(known.has(code)).toBe(true);
    }
  });

  it("flags every critical entry as native today (all 10 panes are registered)", () => {
    // If a future PR removes one of these from registry.PANES, this
    // test fails loudly — exactly the regression S05 is designed to
    // catch before it ships.
    for (const entry of criticalInventory()) {
      expect({ code: entry.code, renderer: entry.renderer }).toEqual({
        code: entry.code,
        renderer: "native",
      });
      expect(entry.critical).toBe(true);
      expect(entry.synthetic_risk).toBe("none");
      expect(entry.native_ui_ready).toBe(true);
    }
  });
});

describe("readinessFlags is pure on renderer choice", () => {
  // Every choice maps to a single deterministic flag-set. Pin each so a
  // future refactor that flips one bit (e.g. mark stub as a11y_ready)
  // cannot land without an updated test.
  const cases: Array<{
    choice: PaneRendererChoice;
    expected: Omit<PaneInventoryEntry, "code" | "renderer" | "critical">;
  }> = [
    {
      choice: "native",
      expected: {
        native_ui_ready: true,
        live_data_ready: true,
        interaction_ready: true,
        a11y_ready: true,
        test_ready: true,
        synthetic_risk: "none",
      },
    },
    {
      choice: "template",
      expected: {
        native_ui_ready: false,
        live_data_ready: true,
        interaction_ready: false,
        a11y_ready: true,
        test_ready: true,
        synthetic_risk: "low",
      },
    },
    {
      choice: "stub",
      expected: {
        native_ui_ready: false,
        live_data_ready: true,
        interaction_ready: false,
        a11y_ready: false,
        test_ready: false,
        synthetic_risk: "low",
      },
    },
    {
      choice: "design-export",
      expected: {
        native_ui_ready: false,
        live_data_ready: false,
        interaction_ready: false,
        a11y_ready: false,
        test_ready: false,
        synthetic_risk: "medium",
      },
    },
    {
      choice: "critical-missing",
      expected: {
        native_ui_ready: false,
        live_data_ready: false,
        interaction_ready: false,
        a11y_ready: false,
        test_ready: false,
        synthetic_risk: "high",
      },
    },
  ];

  for (const c of cases) {
    it(`maps ${c.choice} to the documented flag-set`, () => {
      expect(readinessFlags(c.choice)).toEqual(c.expected);
    });
  }
});

describe("resolvePaneRenderer — adapter-injected critical-missing branch", () => {
  // Default behavior — every critical code is native today.
  for (const code of CRITICAL_CODES) {
    it(`${code} resolves to "native" with the real registry`, () => {
      expect(resolvePaneRenderer(code)).toBe("native");
    });
  }

  it(`a critical code with NO native renderer resolves to "critical-missing"`, () => {
    // Inject an adapter that pretends GP is missing. Everything else
    // is reported as not-having either — so the only way a non-critical
    // fallback could fire is if the critical guard fails.
    const missingAll = {
      hasNative: () => false,
      hasTemplate: () => true, // even with a template available…
      hasDesignExport: () => true, // …and a design export available…
    };
    for (const code of CRITICAL_CODES) {
      // …the critical short-circuit must still return critical-missing.
      expect(resolvePaneRenderer(code, missingAll)).toBe("critical-missing");
    }
  });

  it("non-critical codes still get the precedence ladder", () => {
    // Mock a code that is not critical, has no native, has a template:
    expect(
      resolvePaneRenderer("STRS", {
        hasNative: () => false,
        hasTemplate: (c) => c === "STRS",
        hasDesignExport: () => false,
      }),
    ).toBe("template");

    // Same code with no template and a design export:
    expect(
      resolvePaneRenderer("STRS", {
        hasNative: () => false,
        hasTemplate: () => false,
        hasDesignExport: (c) => c === "STRS",
      }),
    ).toBe("design-export");

    // Same code with nothing:
    expect(
      resolvePaneRenderer("STRS", {
        hasNative: () => false,
        hasTemplate: () => false,
        hasDesignExport: () => false,
      }),
    ).toBe("stub");
  });
});
