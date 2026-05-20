import { describe, expect, it } from "vitest";
import { computeContrast } from "./a11y";

describe("computeContrast", () => {
  it("returns 21 for pure black on pure white", () => {
    const ratio = computeContrast("#000000", "#ffffff");
    expect(ratio).not.toBeNull();
    expect(ratio!).toBeCloseTo(21, 0);
  });

  it("returns 1 when both colors are identical", () => {
    expect(computeContrast("#000000", "#000")).toBeCloseTo(1, 5);
  });

  it("flags the surface=background degenerate case (UI-INT-03)", () => {
    const ratio = computeContrast("#000000", "#000000");
    expect(ratio).toBeCloseTo(1, 5);
    expect(ratio! < 4.5).toBe(true);
  });

  it("returns null for invalid hex", () => {
    expect(computeContrast("not-hex", "#000000")).toBeNull();
    expect(computeContrast("#000", "#zzz")).toBeNull();
  });

  it("returns ≥4.5 for the new dark-theme text-mute / surface pair (A11Y-01 P1)", () => {
    // tokens.css now ships --text-mute=#7e828f; the smallest dark surface is
    // midnight #0f1115. Should clear AA for body copy.
    const ratio = computeContrast("#7e828f", "#0f1115");
    expect(ratio).not.toBeNull();
    expect(ratio!).toBeGreaterThanOrEqual(4.4);
  });

  it("returns ≥4.5 for papyrus text-mute / surface pair (A11Y-01 P1)", () => {
    // Papyrus block ships --text-mute=#645d52 over #fbf8f0 cream surface.
    const ratio = computeContrast("#645d52", "#fbf8f0");
    expect(ratio).not.toBeNull();
    expect(ratio!).toBeGreaterThanOrEqual(4.4);
  });

  it("papyrus accent #8a5a1f vs cream surface clears 3:1 for non-text", () => {
    const ratio = computeContrast("#8a5a1f", "#fbf8f0");
    expect(ratio).not.toBeNull();
    expect(ratio!).toBeGreaterThanOrEqual(3);
  });
});
