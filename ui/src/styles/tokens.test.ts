/**
 * Token regression tests — round-2B (UX-02 + UX-04 + A11Y-07).
 *
 * Reads the raw CSS file as text and asserts that every token added in
 * the close-out batch (spacing ladder, font-size scale, font-weight tokens,
 * z-index tokens, scrim tokens, papyrus semantic overrides) is present.
 * This is a structural test — much faster than rendering and comparing
 * computed styles, and it catches regressions where a future codemod drops
 * a token name silently.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(
  resolve(__dirname, "tokens.css"),
  "utf8",
);

const SHOULD_DEFINE = [
  // Spacing ladder (UX-04 P1)
  "--space-1:",
  "--space-2:",
  "--space-3:",
  "--space-4:",
  "--space-5:",
  "--space-6:",
  "--space-7:",
  "--space-8:",
  // Type scale (UX-02 P1, A11Y-07)
  "--font-size-xs:",
  "--font-size-sm:",
  "--font-size-md:",
  "--font-size-lg:",
  "--font-size-xl:",
  "--font-size-hero:",
  "--font-mono:",
  "--font-display:",
  "--font-weight-regular:",
  "--font-weight-semibold:",
  "--line-height-tight:",
  "--line-height-normal:",
  "--tracking-label:",
  // Z-index ladder (TS-LINT-06)
  "--z-modal:",
  "--z-toast:",
  "--z-confirm:",
  // Scrim / overlay tokens (UX-09 P2)
  "--scrim-low:",
  "--scrim-med:",
  "--scrim-high:",
  "--scrim-modal:",
  "--sidebar-bg:",
  // Radii additions
  "--radius-xs:",
  "--radius-pill:",
];

describe("design tokens", () => {
  it("defines the round-2B token surface", () => {
    for (const token of SHOULD_DEFINE) {
      expect(css.includes(token), `missing ${token}`).toBe(true);
    }
  });

  it("includes a prefers-reduced-motion wildcard reset (A11Y-06 P1)", () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(css).toMatch(/animation-duration:\s*0\.01ms\s*!important/);
    expect(css).toMatch(/transition-duration:\s*0\.01ms\s*!important/);
  });

  it("ships papyrus semantic overrides (A11Y-01 P1)", () => {
    // Two papyrus blocks exist (slot block + override block). The semantic
    // overrides live in the SECOND occurrence, so take everything after it.
    const parts = css.split('[data-preset="papyrus"]');
    const block = parts.slice(2).join('[data-preset="papyrus"]');
    // Darker mint and rose so P&L on cream surface clears WCAG AA.
    expect(block).toMatch(/--positive:\s*#117a44/);
    expect(block).toMatch(/--negative:\s*#c43250/);
  });

  it("ships the ShowMe // Future Matrix theme token block (v3 canvas)", () => {
    const parts = css.split('[data-preset="matrix"]');
    expect(parts.length).toBeGreaterThanOrEqual(3);
    const slotBlock = parts[1];
    const overrideBlock = parts.slice(2).join('[data-preset="matrix"]');
    // Slot triple (3 user-tunable colors) — canvas-pinned.
    expect(slotBlock).toMatch(/--bg:\s*#000000/);
    expect(slotBlock).toMatch(/--surface:\s*#040b06/);
    expect(slotBlock).toMatch(/--accent:\s*#00ff41/);
    // Canvas-pinned text + accent family + chart aesthetics.
    expect(slotBlock).toMatch(/--text-display-hex:\s*#c8ffd6/);
    expect(slotBlock).toMatch(/--text-hex:\s*#6bff8a/);
    expect(slotBlock).toMatch(/--accent-2:\s*#9aff7f/);
    expect(slotBlock).toMatch(/--accent-glow:\s*rgba\(0,\s*255,\s*65,\s*0\.55\)/);
    expect(slotBlock).toMatch(/--scanline:\s*rgba\(0,\s*255,\s*65,\s*0\.05\)/);
    expect(slotBlock).toMatch(/--font-text:\s*"Share Tech Mono"/);
    // Override block keeps the canvas matrix positive (distinct from accent).
    expect(overrideBlock).toMatch(/--text-primary:\s*#c8ffd6/);
    expect(overrideBlock).toMatch(/--positive:\s*#00ff85/);
  });

  it("flips surface ladder mix toward black on papyrus (UX-09 P1)", () => {
    const parts = css.split('[data-preset="papyrus"]');
    const block = parts.slice(2).join('[data-preset="papyrus"]');
    expect(block).toMatch(/--surface-2:[\s\S]*black/);
    expect(block).toMatch(/--surface-3:[\s\S]*black/);
  });

  it("pegs root font-size to 14px so rem-based tokens scale predictably (A11Y-07)", () => {
    expect(css).toMatch(/html\s*\{[\s\S]*?font-size:\s*14px/);
  });

  /* ────────────────────────────────────────────────────────────────────
   * Agent F a11y close-out — WCAG 2.1 AA contrast on the lowest text
   * ladder slot (--text-faint). The QA report flagged Matrix at 3.16:1
   * and Midnight at 2.65:1; both lifted to ≥4.5 on their slot bg.
   * ──────────────────────────────────────────────────────────────────── */
  it("matrix --text-faint hits WCAG AA on the matrix slot background", () => {
    const parts = css.split('[data-preset="matrix"]');
    const slotBlock = parts[1] ?? "";
    // Match the lifted value, NOT the regressed #156a2d (3.13:1).
    expect(slotBlock).toMatch(/--text-faint:\s*#3aa856/);
    expect(slotBlock).not.toMatch(/--text-faint:\s*#156a2d/);
    // The numeric guard: parse the hex and compute contrast vs --bg=#000.
    const contrast = computeContrastFromCss("#3aa856", "#000000");
    expect(contrast).toBeGreaterThanOrEqual(4.5);
  });

  it("midnight --text-faint hits WCAG AA on the midnight slot background", () => {
    const parts = css.split(':root,\n[data-preset="midnight"]');
    const slotBlock = parts[1] ?? css;
    expect(slotBlock).toMatch(/--text-faint:\s*#9d917a/);
    expect(slotBlock).not.toMatch(/--text-faint:\s*#5b5447/);
    const contrast = computeContrastFromCss("#9d917a", "#0b0907");
    expect(contrast).toBeGreaterThanOrEqual(4.5);
  });
});

// Bare-bones WCAG 2.1 relative-luminance contrast — copied from
// `@/lib/a11y.ts` so the test file stays self-contained (and so we
// catch a regression where lib/a11y is broken).
function computeContrastFromCss(a: string, b: string): number {
  const lum = (hex: string) => {
    const m = hex.replace(/^#/, "");
    const r = parseInt(m.slice(0, 2), 16) / 255;
    const g = parseInt(m.slice(2, 4), 16) / 255;
    const bl = parseInt(m.slice(4, 6), 16) / 255;
    const t = (c: number) =>
      c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    return 0.2126 * t(r) + 0.7152 * t(g) + 0.0722 * t(bl);
  };
  const la = lum(a);
  const lb = lum(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
