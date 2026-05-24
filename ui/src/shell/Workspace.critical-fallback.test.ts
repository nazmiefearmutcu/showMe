/**
 * S05 — Workspace critical-pane fallback guard.
 *
 * Pins three orthogonal invariants:
 *
 *   1. `choosePaneRenderer(code)` returns "native" for every critical
 *      code in the live registry — the production happy path.
 *   2. With an injected adapter that simulates a missing native
 *      renderer, every critical code routes to "critical-missing" —
 *      never to template, design-export, or stub. This is the safety
 *      contract S05 exists to enforce.
 *   3. Source-level guards on `PaneContent` so a future refactor cannot
 *      silently re-introduce the template/design/stub fallback for
 *      critical codes.
 *
 * No React tree mount — the resolver is pure logic and the source
 * guards run via `readFileSync`. Heavy panes (TOP, MIS, NI) require
 * sidecar + workspace + router providers, so a mount-based test of
 * the rendering branch would drag in the whole shell.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { choosePaneRenderer } from "./Workspace";
import { CRITICAL_CODES } from "@/lib/pane-completeness";

const ROOT = resolve(__dirname, "..", "..", "..");
const WORKSPACE_TSX = resolve(ROOT, "ui/src/shell/Workspace.tsx");
const SOURCE = readFileSync(WORKSPACE_TSX, "utf8");

describe("S05 · critical codes resolve to native today", () => {
  for (const code of CRITICAL_CODES) {
    it(`${code} → native`, () => {
      expect(choosePaneRenderer(code)).toBe("native");
    });
  }

  it("case-insensitive — lowercase critical codes still resolve to native", () => {
    for (const code of CRITICAL_CODES) {
      expect(choosePaneRenderer(code.toLowerCase())).toBe("native");
    }
  });
});

describe("S05 · critical codes cannot fall through to template/design/stub", () => {
  const noNative = { hasNative: () => false };

  it(`every critical code routes to "critical-missing" when native is unavailable`, () => {
    for (const code of CRITICAL_CODES) {
      expect(choosePaneRenderer(code, noNative)).toBe("critical-missing");
    }
  });

  it("does not degrade to template even if a template exists", () => {
    for (const code of CRITICAL_CODES) {
      expect(
        choosePaneRenderer(code, {
          hasNative: () => false,
          hasTemplate: () => true,
        }),
      ).toBe("critical-missing");
    }
  });

  it("does not degrade to design-export even if a design export exists", () => {
    for (const code of CRITICAL_CODES) {
      expect(
        choosePaneRenderer(code, {
          hasNative: () => false,
          hasTemplate: () => false,
          hasDesignExport: () => true,
        }),
      ).toBe("critical-missing");
    }
  });

  it("does not degrade to stub when everything is missing", () => {
    for (const code of CRITICAL_CODES) {
      expect(
        choosePaneRenderer(code, {
          hasNative: () => false,
          hasTemplate: () => false,
          hasDesignExport: () => false,
        }),
      ).toBe("critical-missing");
    }
  });
});

describe("S05 · non-critical codes keep the precedence ladder", () => {
  it("non-critical code with template only resolves to template", () => {
    // STRS is a known template-only code from S13 — pin it as the
    // canonical "template-only still template" smoke.
    expect(choosePaneRenderer("STRS")).toBe("template");
  });

  it("non-critical code with a fully empty resolver falls through to stub", () => {
    const empty = {
      hasNative: () => false,
      hasTemplate: () => false,
      hasDesignExport: () => false,
    };
    expect(choosePaneRenderer("ZZZZZZ", empty)).toBe("stub");
    // Real "ZZZZZZ" also lands on stub because nothing knows about it.
    expect(choosePaneRenderer("ZZZZZZ")).toBe("stub");
  });

  it("non-critical code that only has a design export resolves to design-export", () => {
    expect(
      choosePaneRenderer("APPL", {
        hasNative: () => false,
        hasTemplate: () => false,
        hasDesignExport: () => true,
      }),
    ).toBe("design-export");
  });
});

describe("S05 · Workspace source guards", () => {
  it("imports the critical-pane helpers from @/lib/pane-completeness", () => {
    expect(SOURCE).toMatch(/from "@\/lib\/pane-completeness"/);
    expect(SOURCE).toMatch(/CRITICAL_CODES/);
    expect(SOURCE).toMatch(/isCriticalCode/);
    expect(SOURCE).toMatch(/resolvePaneRenderer/);
  });

  it("PaneContent switches on the resolvePaneRenderer choice", () => {
    expect(SOURCE).toMatch(/const choice = resolvePaneRenderer\(code\);/);
    expect(SOURCE).toMatch(/case "critical-missing":/);
  });

  it("defines an explicit CriticalMissingPane guard component", () => {
    expect(SOURCE).toMatch(/function CriticalMissingPane\b/);
    // The guard pane must use a loud aria role so the user notices —
    // not a silent dim placeholder.
    expect(SOURCE).toMatch(/role="alert"/);
    expect(SOURCE).toMatch(/Critical pane unavailable/);
  });

  it("only Preferences becomes a design-leaf (every other code keeps chrome)", () => {
    // QA-2026-05-23: the design-leaf carve-out is now PREF only. Before
    // the fix, any non-critical, non-native, non-template code with a
    // hasDesignExportComponent hit also stripped the PaneChrome so the
    // 39k-line static cockpit owned the entire pane surface. With the
    // design-export tier collapsed into stub, only the Preferences
    // shell still hosts its own design-export wrapper.
    expect(SOURCE).toMatch(/const isDesignLeaf\s*=\s*node\.code\s*===\s*["']PREF["']/);
    expect(SOURCE).not.toMatch(/hasDesignExportComponent\(/);
  });

  it("collapses the non-critical ladder to native > template > stub (design-export → stub fallthrough)", () => {
    // The switch must list the three live branches in order, plus the
    // legacy `design-export` label as a fallthrough into the stub body
    // (kept so the resolver inventory can still emit "design-export"
    // for diagnostics without breaking the Workspace switch).
    const switchIndex = SOURCE.indexOf("const choice = resolvePaneRenderer(code);");
    expect(switchIndex).toBeGreaterThan(-1);
    const tail = SOURCE.slice(switchIndex);
    const nativeIdx = tail.indexOf(`case "native":`);
    const tplIdx = tail.indexOf(`case "template":`);
    const designIdx = tail.indexOf(`case "design-export":`);
    const stubIdx = tail.indexOf(`case "stub":`);
    expect(nativeIdx).toBeGreaterThan(-1);
    expect(tplIdx).toBeGreaterThan(nativeIdx);
    // design-export still appears as a fallthrough label.
    expect(designIdx).toBeGreaterThan(tplIdx);
    expect(stubIdx).toBeGreaterThan(designIdx);
    // Crucial: design-export must immediately fall through into stub
    // (no body), so the FunctionStub render runs for both labels.
    expect(tail).toMatch(/case\s+"design-export":\s*\n\s*case\s+"stub":/);
  });
});
