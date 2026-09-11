/**
 * Lane L4 — flash keyframe token pin (campaign 2026-09-11).
 *
 * The up/down flash pulses used hardcoded rgba() in their keyframes, so
 * papyrus/matrix presets never resolved their own soft tones. The fix routes
 * both keyframes through --positive-soft-hex / --negative-soft-hex. This
 * structural test reads tokens.css as text and pins that contract (and the
 * class → keyframe wiring) so a future codemod cannot silently re-bake the
 * literals.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

function keyframeBlock(name: string): string {
  const match = new RegExp(`@keyframes ${name} \\{([\\s\\S]*?)\\n\\}`).exec(css);
  return match?.[1] ?? "";
}

describe("flash keyframes resolve per-preset soft tokens", () => {
  it("flash-pos paints with var(--positive-soft-hex), not a baked rgba", () => {
    const block = keyframeBlock("flash-pos");
    expect(block).not.toBe("");
    expect(block).toContain("var(--positive-soft-hex)");
    expect(block).not.toMatch(/rgba?\(/);
  });

  it("flash-neg paints with var(--negative-soft-hex), not a baked rgba", () => {
    const block = keyframeBlock("flash-neg");
    expect(block).not.toBe("");
    expect(block).toContain("var(--negative-soft-hex)");
    expect(block).not.toMatch(/rgba?\(/);
  });

  it("keeps the .flash-pos / .flash-neg class → keyframe wiring", () => {
    expect(css).toMatch(/\.flash-pos\s*\{[^}]*animation:\s*flash-pos/);
    expect(css).toMatch(/\.flash-neg\s*\{[^}]*animation:\s*flash-neg/);
  });
});
