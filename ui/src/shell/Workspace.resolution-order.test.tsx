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

  it("uses TemplateRenderer for S13 codes without a bespoke pane", () => {
    // STRS / TAUC / TCA / TECH / TLDR / TLH / TRA / TRDH / TRAN all
    // have template entries in mock-data.ts and no bespoke pane in
    // registry.PANES — they should land on the template tier so the
    // live overlay can fetch real data.
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
      expect(choosePaneRenderer(code)).toBe("template");
    }
  });

  it("falls through to FunctionStub for unknown codes", () => {
    expect(choosePaneRenderer("ZZZZZZ")).toBe("stub");
  });
});
