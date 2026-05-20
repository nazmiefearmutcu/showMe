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

describe("Workspace.PaneContent precedence (S16)", () => {
  const source = readFileSync(WORKSPACE_TSX, "utf8");

  it("queries the native pane registry before the design export", () => {
    const resolveIdx = source.indexOf("resolvePane(code)");
    const designIdx = source.indexOf("hasDesignExportComponent(code)");
    expect(resolveIdx).toBeGreaterThan(-1);
    expect(designIdx).toBeGreaterThan(-1);
    // Take the LAST occurrence of resolvePane(code) inside PaneContent —
    // it's the call inside the precedence ladder. The HOME branch above
    // it does not consult resolvePane.
    const lastResolveIdx = source.lastIndexOf("resolvePane(code)");
    expect(lastResolveIdx).toBeLessThan(source.lastIndexOf("hasDesignExportComponent(code)"));
  });

  it("still calls the design export as a fallback", () => {
    expect(source).toContain("DesignExportRenderer");
    expect(source).toContain("hasDesignExportComponent(code)");
  });

  it("falls back to FunctionStub when nothing else matches", () => {
    expect(source).toContain("FunctionStub");
  });

  it("suppresses outer PaneChrome only for design-only leaves", () => {
    // `isDesignLeaf` flag must check that there is NO native pane AND
    // NO template before deferring chrome to the design-export shell.
    // Otherwise native panes lose their SymbolBar / RefreshButton when
    // a sibling design-export entry happens to exist for the same code.
    expect(source).toMatch(/!hasNative\s+&&\s+!hasTpl\s+&&\s+hasDesignExportComponent/);
  });
});
