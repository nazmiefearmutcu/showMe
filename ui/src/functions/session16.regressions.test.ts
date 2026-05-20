/**
 * Session 16 BugHunt — source-level regression guards.
 *
 * These tests pin the small drift fixes that landed in the 10-code
 * sweep so a future PR can't silently revert them. They read files
 * with `readFileSync` and assert string-level invariants — no React
 * tree mounting required.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = resolve(__dirname, "..", "..", "..");

describe("Session 16 — EQS pane forces the live screener path", () => {
  const eqsSource = readFileSync(
    resolve(ROOT, "ui/src/functions/EQS.tsx"),
    "utf8",
  );

  it("passes live_screen: true so backend skips _screen_template_rows", () => {
    // Pre-S16 the dedicated EQS pane sent `{query, limit, universe}`
    // without any `live_screen` flag. backend/showme/engine/functions/
    // equity/eqs.py:156 reads `live_screen` / `deep`; absent both, it
    // serves five hard-coded sample rows from `_screen_template_rows`.
    // The generic FunctionStub already passes `live: true` — the
    // bespoke pane was the outlier.
    expect(eqsSource).toMatch(/live_screen:\s*true/);
  });
});

describe("Session 16 — HP COMPARE overlay tracks the active chart palette", () => {
  const hpSource = readFileSync(
    resolve(ROOT, "ui/src/functions/HP.tsx"),
    "utf8",
  );

  it("no longer hard-codes the dark-mode COMPARE_COLORS hex literal", () => {
    // Old: `const COMPARE_COLORS = ["#7C7AFF", "#F0B445", "#2FD480", "#FF5874"];`
    // pinned compare-chip colors and chart strokes to dark mode. The
    // S16 fix derives them from useChartPalette() so Papyrus / Matrix /
    // custom-slot presets actually recolor the overlay.
    expect(hpSource).not.toMatch(/COMPARE_COLORS\s*=\s*\[/);
    expect(hpSource).toContain("compareColorsFromPalette");
    expect(hpSource).toContain("useChartPalette");
  });
});

describe("Session 16 — NI news-load surfaces use scrim tokens, not raw white/black", () => {
  const niSource = readFileSync(
    resolve(ROOT, "ui/src/functions/NI.tsx"),
    "utf8",
  );

  it("drops the dark-mode-only color-mix(white …) and color-mix(black …) literals from newsLoadShell + newsLoadStep", () => {
    // The drop is narrow: only the white/black overlay variants. Other
    // legitimate color-mix calls (with var(--accent), var(--bg) …)
    // remain in place — they already track the active theme.
    expect(niSource).not.toMatch(/color-mix\(in srgb,\s*white\b/);
    expect(niSource).not.toMatch(/color-mix\(in srgb,\s*black\b/);
    expect(niSource).toContain("var(--scrim-low)");
  });
});

describe("Session 16 — Preferences pane re-enables every native section", () => {
  const prefSource = readFileSync(
    resolve(ROOT, "ui/src/panes/preferences_pane/index.tsx"),
    "utf8",
  );

  it("renders every native settings section behind the active-section guard", () => {
    // Pre-S16 every section was gated with `{false && active === "…" && …}`
    // so the user could never reach AppearanceSection (3-slot color
    // pickers, density, locale, timezone), DataSection, StreamsSection,
    // SecretsSection, MigrationSection, LlmSection, or AboutSection —
    // the SettingsDesignExportRenderer's inert mock buttons were the
    // only visible control surface.
    expect(prefSource).not.toMatch(/\{false\s*&&\s*active\s*===/);
    for (const name of [
      "AppearanceSection",
      "DataSection",
      "StreamsSection",
      "SecretsSection",
      "MigrationSection",
      "LlmSection",
      "AboutSection",
    ]) {
      expect(prefSource).toContain(`<${name}`);
    }
  });

  it("still mounts SettingsDesignExportRenderer as the design shell", () => {
    expect(prefSource).toContain("SettingsDesignExportRenderer");
  });
});
