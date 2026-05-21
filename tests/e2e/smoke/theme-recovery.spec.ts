/**
 * S06 gate 1 — theme transition overlay recovery.
 *
 * The overlay covers the layout-reflow freeze during a preset / density
 * change (see `lib/theme-transition.ts`). Past incidents:
 *   * Recovery S01 (2026-05-20) — under rapid presses the overlay could
 *     stay mounted with `pointer-events: auto` and silently eat every
 *     click for the rest of the session.
 *
 * Insurance gates here:
 *   1. After firing five theme toggles back-to-back, the overlay must
 *      disappear from the DOM within the producer+consumer watchdog
 *      ceiling (1500ms self-watchdog + 140ms leave buffer + slack).
 *   2. While the overlay IS visible, it MUST advertise itself as
 *      non-hit-testable (`pointer-events: none`) so clicks land on the
 *      real UI. We assert this with `elementHandle.evaluate` so a CSS
 *      regression that flips it back to `auto` would trip the gate.
 *   3. Post-recovery, the command palette opens via ⌘K and key events
 *      reach the input — a strict signal that input routing isn't stuck.
 */
import { expect, test } from "@playwright/test";
import { seedBrowserShellLocalStorage, stubSidecar } from "./_fixtures/stub-sidecar";

test.describe("theme transition recovery", () => {
  test.beforeEach(async ({ page }) => {
    await stubSidecar(page);
    await seedBrowserShellLocalStorage(page);
  });

  test("rapid theme toggles never leave the overlay hit-testable", async ({ page }) => {
    await page.goto("/");
    // Wait for the shell to settle before we start hammering — the
    // statusbar FN count is the cheapest "boot done" signal, but the
    // boot intro splash (`aria-label="showMe loading"`) keeps its
    // `pointer-events: auto` invariant on top of the workspace until
    // its leave animation completes (~2.3s). Without waiting for the
    // splash to detach, our theme-toggle click would be intercepted
    // by the splash and not by the actual button.
    await expect(page.locator("body")).toContainText(/FN\s*\d+/i, {
      timeout: 8_000,
    });
    await expect(page.locator('[aria-label="showMe loading"]')).toHaveCount(
      0,
      { timeout: 6_000 },
    );

    // The theme button has aria-label "Toggle theme (currently <Preset>)".
    // Playwright's `getByRole({ name })` accessible-name resolution misses
    // it because the visible text is the preset label (e.g. "Papyrus") and
    // there's no aria-labelledby — match by the stable aria-label substring
    // via `getByLabel`, which checks aria-label directly.
    const themeToggle = page.getByLabel(/Toggle theme/i).first();
    await expect(themeToggle).toBeVisible({ timeout: 4_000 });

    // ── Fire 5 toggles in quick succession. Force-click bypasses
    //    actionability checks so the overlay itself can't gate the test:
    //    if it ever managed to swallow clicks, that's the bug we want to
    //    surface.
    for (let i = 0; i < 5; i += 1) {
      await themeToggle.click({ force: true, noWaitAfter: true });
    }

    // ── While the overlay is mounted it must never block pointer events.
    //    We catch it during the active window (~280ms expanding + leave).
    //    Skip if it already cleared — the producer-side bypass for
    //    reduced-motion or test mode is a valid path.
    const overlay = page.locator('[data-testid="theme-transition-overlay"]');
    const sawOverlay = await overlay
      .first()
      .waitFor({ state: "visible", timeout: 600 })
      .then(() => true)
      .catch(() => false);
    if (sawOverlay) {
      const pointerEvents = await overlay.first().evaluate(
        (el) => window.getComputedStyle(el as HTMLElement).pointerEvents,
      );
      expect(
        pointerEvents,
        "overlay must remain non-hit-testable so clicks pass through",
      ).toBe("none");
      expect(await overlay.first().getAttribute("aria-hidden")).toBe("true");
    }

    // ── Overlay must clear within the watchdog ceiling. 1500ms self-
    //    watchdog + 140ms leave + 360ms slack = 2000ms.
    await expect(overlay).toHaveCount(0, { timeout: 2_000 });

    // ── Input routing not stuck: clicking the command-palette open
    //    button must reach a non-overlay target and toggle the palette.
    //    We click the button rather than relying on Cmd+K so the gate
    //    proves "real clicks land" (i.e. pointer-events not stuck).
    //    The button is aria-labeled, so getByLabel finds it stably.
    const paletteOpenBtn = page
      .getByLabel(/Open command palette/i)
      .first();
    await expect(paletteOpenBtn).toBeVisible({ timeout: 3_000 });
    await paletteOpenBtn.click();
    // The palette input is `role="combobox"` with aria-label "Function
    // search" — placeholder copy is i18n-bound so we use role instead.
    const palette = page.getByRole("combobox", { name: /Function search/i });
    await expect(palette).toBeVisible({ timeout: 3_000 });
    await palette.fill("port");
    await expect(page.locator("body")).toContainText(/Portfolio/i, {
      timeout: 3_000,
    });
    await page.keyboard.press("Escape");

    // ── And a normal button click still lands — the theme toggle itself
    //    works again. If the overlay were stuck with `pointer-events: auto`
    //    this click would either no-op or hit the overlay div.
    await themeToggle.click();
    await expect(overlay).toHaveCount(0, { timeout: 2_000 });
  });
});
