/**
 * Pins the pane-renderer resolution order: native > template > design-export
 * > stub.
 *
 * The original Workspace.tsx had design-export winning first (before
 * either bespoke or template), which silently shadowed live panes like
 * TOPPane (~800 lines, live `/api/fn/TOP` + Veryfinder overlay) with a
 * static design mock. S13 BugHunt 2026-05-17 inverted the order so the
 * highest-fidelity renderer wins. This test asserts the order across
 * representative S13 codes — a regression here would re-introduce the
 * fake-data regression that motivated the fix.
 */
import { describe, expect, it } from "vitest";
import { choosePaneRenderer } from "./Workspace";

describe("Workspace pane-renderer resolution order", () => {
  it("prefers the bespoke pane (TOP) over template and design-export", () => {
    expect(choosePaneRenderer("TOP")).toBe("native");
    expect(choosePaneRenderer("top")).toBe("native");
  });

  it("collapses unknown non-catalog codes to stub (ManifestPane fallback)", () => {
    // 2026-05-24 rebuild: template tier is no longer in the production
    // resolver. Every non-bespoke non-critical code now falls through to
    // "stub", which Workspace.tsx maps to <ManifestPane>. ManifestPane
    // loads the function manifest and renders the contract-driven shell.
    // NOTE (FN-WAVE 2026-09-08): every catalog code now resolves native —
    // the last generic examples (AV/BBGT/BMC/EVTS/FLY, waves 1-5) were
    // removed from this list — so the stub path is pinned with a
    // non-catalog code instead.
    for (const code of ["ZZZZ", "FAKE1", "NOTACODE"]) {
      expect(choosePaneRenderer(code)).toBe("stub");
    }
  });

  it("de-garbaged codes with a new bespoke pane resolve to native", () => {
    // The nine functions whose backends now return real keyless data also
    // got bespoke panes; they must render natively, not via the stub.
    for (const code of ["CRPR", "DEBT", "IVOL", "OVDV", "MICRO", "AIM", "TCA", "SAT", "POLY"]) {
      expect(choosePaneRenderer(code)).toBe("native");
    }
  });

  it("falls through to stub (ManifestPane) for unknown codes", () => {
    expect(choosePaneRenderer("ZZZZZZ")).toBe("stub");
  });
});
