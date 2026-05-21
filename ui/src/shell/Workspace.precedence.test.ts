/**
 * Workspace precedence regression — Session 16 BugHunt.
 *
 * Pre-S16 `Workspace.PaneContent` short-circuited every function code to
 * `<DesignExportRenderer/>` whenever `hasDesignExportComponent(code)`
 * returned true. Since `DESIGN_PRO_CODES` contains all 141 catalog codes
 * (plus HOME), every bespoke pane (HP, GP, DES, FA, EQS, BTMM, ASK,
 * BIO, NI → CN alias, MIS, …) was dead code at runtime — users only
 * ever saw the static Claude Design Pro mockups.
 *
 * This test asserts the inverted precedence at the source-text level so
 * a future refactor cannot silently re-introduce the design-first
 * resolution.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = resolve(__dirname, "..", "..", "..");
const WORKSPACE_TSX = resolve(ROOT, "ui/src/shell/Workspace.tsx");

describe("Workspace.PaneContent precedence (S16 / S05)", () => {
  const source = readFileSync(WORKSPACE_TSX, "utf8");

  it("queries the native pane registry before the design export inside the switch", () => {
    // S05 — the inline `if (resolvePane(code))` ladder is gone, replaced
    // with a `switch (choice)` over `resolvePaneRenderer(code)` so the
    // critical-pane guard can short-circuit. The order inside the switch
    // is still native > template > design-export > stub; pin it here.
    const switchIdx = source.indexOf("const choice = resolvePaneRenderer(code);");
    expect(switchIdx).toBeGreaterThan(-1);
    const tail = source.slice(switchIdx);
    const nativeCaseIdx = tail.indexOf(`case "native":`);
    const designCaseIdx = tail.indexOf(`case "design-export":`);
    expect(nativeCaseIdx).toBeGreaterThan(-1);
    expect(designCaseIdx).toBeGreaterThan(-1);
    expect(nativeCaseIdx).toBeLessThan(designCaseIdx);
  });

  it("still calls the design export as a fallback for non-critical codes", () => {
    expect(source).toContain("DesignExportRenderer");
    expect(source).toContain("hasDesignExportComponent");
    // Must still appear inside the switch as the third tier.
    expect(source).toMatch(/case "design-export":[\s\S]{0,200}<DesignExportRenderer/);
  });

  it("falls back to FunctionStub when nothing else matches", () => {
    expect(source).toContain("FunctionStub");
    expect(source).toMatch(/case "stub":[\s\S]{0,200}<FunctionStub/);
  });

  it("suppresses outer PaneChrome only for non-critical design-only leaves", () => {
    // `isDesignLeaf` must check (1) the code is NOT critical, (2) no
    // native pane, (3) no template, before deferring chrome to the
    // design-export shell. S05 added the `!isCritical` guard so that
    // a critical-missing pane keeps its toolbar visible — the trader
    // must still see which code failed.
    expect(source).toMatch(
      /!isCritical\s+&&\s+!hasNative\s+&&\s+!hasTpl\s+&&\s+hasDesignExportComponent/,
    );
  });
});
