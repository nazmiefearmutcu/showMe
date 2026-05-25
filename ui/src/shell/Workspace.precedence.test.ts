/**
 * Workspace precedence regression — Session 16 BugHunt + QA-2026-05-23.
 *
 * Pre-S16 `Workspace.PaneContent` short-circuited every function code to
 * `<DesignExportRenderer/>` whenever `hasDesignExportComponent(code)`
 * returned true. Since `DESIGN_PRO_CODES` contains all 141 catalog codes
 * (plus HOME), every bespoke pane (HP, GP, DES, FA, EQS, BTMM, ASK,
 * BIO, NI → CN alias, MIS, …) was dead code at runtime — users only
 * ever saw the static Claude Design Pro mockups.
 *
 * S16 inverted the precedence (native > template > design-export > stub)
 * but the design-export tier still served the 39k-line mockup with
 * `Math.random()` drift for ~110 catalog codes that lack a bespoke pane
 * or template. QA-2026-05-23 collapsed the design-export branch into
 * stub so FunctionStub handles every catalog code via `/api/fn/{code}`.
 *
 * This test asserts the collapsed precedence at the source-text level so
 * a future refactor cannot silently re-introduce the design-mockup
 * routing.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = resolve(__dirname, "..", "..", "..");
const WORKSPACE_TSX = resolve(ROOT, "ui/src/shell/Workspace.tsx");

describe("Workspace.PaneContent precedence (S16 / S05 / QA-2026-05-23)", () => {
  const source = readFileSync(WORKSPACE_TSX, "utf8");

  it("queries the native pane registry before any fallback inside the switch", () => {
    // S05 — the inline `if (resolvePane(code))` ladder is gone, replaced
    // with a `switch (choice)` over `resolvePaneRenderer(code)` so the
    // critical-pane guard can short-circuit. QA-2026-05-23 collapses the
    // ladder to native > template > stub; pin the native-first order.
    const switchIdx = source.indexOf("const choice = resolvePaneRenderer(code);");
    expect(switchIdx).toBeGreaterThan(-1);
    const tail = source.slice(switchIdx);
    const nativeCaseIdx = tail.indexOf(`case "native":`);
    const templateCaseIdx = tail.indexOf(`case "template":`);
    const stubCaseIdx = tail.indexOf(`case "stub":`);
    expect(nativeCaseIdx).toBeGreaterThan(-1);
    expect(templateCaseIdx).toBeGreaterThan(nativeCaseIdx);
    expect(stubCaseIdx).toBeGreaterThan(templateCaseIdx);
  });

  it("QA-2026-05-23: Workspace no longer imports DesignExportRenderer or hasDesignExportComponent", () => {
    // The 39k-line `showme-design-export.tsx` module must never be
    // mounted by the Workspace any more. Removing these imports also
    // tree-shakes the entire mockup module out of the production bundle.
    // The `Settings*` variant is kept by Preferences pane and may
    // still be name-dropped in a comment block, so we anchor the
    // import-form match instead of a bare substring.
    expect(source).not.toMatch(
      /from\s+["']@\/design-export\/showme-design-export["']/,
    );
    // No bare DesignExportRenderer / hasDesignExportComponent JSX or
    // call expression. Comments mentioning SettingsDesignExportRenderer
    // are tolerated by anchoring to JSX `<` or call `(`.
    expect(source).not.toMatch(/<DesignExportRenderer\b/);
    expect(source).not.toMatch(/hasDesignExportComponent\s*\(/);
  });

  it("QA-2026-05-23: design-export choice falls through to FunctionStub", () => {
    // The resolver may still return "design-export" for inventory /
    // diagnostics consumers (pane-completeness.paneInventory), but the
    // Workspace switch must treat it the same as "stub" so the real
    // `/api/fn/{code}` response is rendered. The case-fallthrough
    // pattern is the explicit contract.
    expect(source).toMatch(
      /case\s+"design-export":\s*\n\s*case\s+"stub":/,
    );
  });

  it("falls back to ManifestPane when nothing else matches", () => {
    // 2026-05-24 rebuild: production-fakery removal — FunctionStub +
    // TemplateRenderer dropped from Workspace.tsx. Every non-native
    // non-critical code now collapses to <ManifestPane>, which loads
    // the function manifest and renders the contract-driven shell.
    expect(source).toContain("ManifestPane");
    // The default-case block may contain a long explanatory comment
    // before the JSX, so the window is generous.
    expect(source).toMatch(/default:[\s\S]{0,1200}<ManifestPane/);
  });

  it("only Preferences remains a design-leaf — every other code keeps PaneChrome", () => {
    // Pre QA-2026-05-23 the `isDesignLeaf` expression also matched any
    // non-critical, non-native, non-template code that had a design
    // export. QA-2026-05-23 narrowed the expression to PREF only so
    // FunctionStub (the new fallback for those codes) renders inside
    // the normal PaneChrome / SymbolBar / RefreshButton shell.
    expect(source).toMatch(/const isDesignLeaf\s*=\s*node\.code\s*===\s*["']PREF["']/);
    // The legacy `(!isCritical && !hasNative && !hasTpl && hasDesignExportComponent…)`
    // tail clause must be gone.
    expect(source).not.toMatch(/hasDesignExportComponent\(/);
  });
});
