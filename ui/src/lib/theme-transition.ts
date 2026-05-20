/**
 * Theme transition bridge — covers the layout-reflow freeze that happens
 * when a preset or density change ripples through the workspace
 * (chart-palette fan-out + grid recalc + design-export Pro tile reflow).
 *
 * Pattern: dispatch `THEME_TRANSITION_START`, defer the actual mutation
 * to the next `requestAnimationFrame` (overlay is painted by then), then
 * dispatch `THEME_TRANSITION_END` after the overlay's leaving phase.
 *
 * Respect `prefers-reduced-motion`: skip the overlay (and the rAF defer)
 * so the freeze remains explicit rather than hidden behind motion.
 */

export const THEME_TRANSITION_START = "showme:theme-transition-start";
export const THEME_TRANSITION_END = "showme:theme-transition-end";

/** Brief overlay total runtime (ms): expand 180 + leave 100 ≈ 280. */
export const THEME_TRANSITION_DURATION_MS = 300;

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/**
 * Vitest / SSR escape hatch: when this is true, `runThemeTransition`
 * applies its mutation synchronously and skips the overlay events. The
 * theme.test.ts suite relies on synchronous reads of `data-preset` /
 * `data-density` after `setPreset` / `setDensity` returns.
 */
let _bypassTransition =
  // Vite's `import.meta.env.MODE` is "test" under Vitest.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ((globalThis as any)?.import?.meta?.env?.MODE === "test") ||
  // Node's `process.env.NODE_ENV` is "test" under Jest / Vitest legacy.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ((globalThis as any)?.process?.env?.NODE_ENV === "test");

export function __setBypassThemeTransitionForTests(b: boolean): void {
  _bypassTransition = b;
}

/**
 * Run `mutate` (a heavy theme/density write that triggers layout reflow)
 * under a brief overlay so the user never sees the freeze.
 *
 * In SSR / reduced-motion: runs `mutate` synchronously without overlay.
 */
export function runThemeTransition(mutate: () => void): void {
  if (typeof window === "undefined") {
    mutate();
    return;
  }
  if (_bypassTransition) {
    mutate();
    return;
  }
  if (prefersReducedMotion()) {
    mutate();
    return;
  }
  window.dispatchEvent(new CustomEvent(THEME_TRANSITION_START));
  // Two rAF ticks: first lets React mount the overlay, second guarantees
  // the browser has actually painted the opaque overlay before we trigger
  // the reflow. Without the second tick, the mutation can land in the
  // same paint cycle as the mount and the freeze peeks through.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      mutate();
      window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent(THEME_TRANSITION_END));
      }, THEME_TRANSITION_DURATION_MS);
    });
  });
}
