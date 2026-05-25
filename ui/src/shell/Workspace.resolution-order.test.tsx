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

  it("collapses non-native S13 codes to stub (ManifestPane fallback)", () => {
    // 2026-05-24 rebuild: template tier is no longer in the production
    // resolver. Every non-bespoke non-critical code now falls through to
    // "stub", which Workspace.tsx maps to <ManifestPane>. ManifestPane
    // loads the function manifest (143 registered across Wave 1 + Wave 2)
    // and renders the contract-driven shell.
    for (const code of [
      "STRS",
      "TAUC",
      "TCA",
      "TECH",
      "TLDR",
      "TLH",
      "TRA",
      "TRAN",
      "TRDH",
    ]) {
      expect(choosePaneRenderer(code)).toBe("stub");
    }
  });

  it("falls through to stub (ManifestPane) for unknown codes", () => {
    expect(choosePaneRenderer("ZZZZZZ")).toBe("stub");
  });
});
