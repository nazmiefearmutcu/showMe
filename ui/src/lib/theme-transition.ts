/**
 * Theme transition bridge — covers the layout-reflow freeze that happens
 * when a preset or density change ripples through the workspace
 * (chart-palette fan-out + grid recalc + design-export Pro tile reflow).
 *
 * Pattern: dispatch `THEME_TRANSITION_START`, defer the actual mutation
 * to the next `requestAnimationFrame` (overlay is painted by then), then
 * dispatch `THEME_TRANSITION_END` after the overlay's leaving phase.
 *
 * Recovery S01 hardening (2026-05-20): every `runThemeTransition` call is
 * guaranteed to dispatch `THEME_TRANSITION_END` exactly once, even if the
 * `mutate` callback throws or the rAF chain stalls (background tab, focus
 * loss). Mechanism: `try/finally` around the mutation schedules the
 * planned END, and a hard `setTimeout` watchdog forces END if the rAF
 * chain never reaches `mutate`. A separate `THEME_TRANSITION_FORCE_END`
 * event lets the overlay self-heal as a last line of defense.
 *
 * Respect `prefers-reduced-motion`: skip the overlay (and the rAF defer)
 * so the freeze remains explicit rather than hidden behind motion.
 */

export const THEME_TRANSITION_START = "showme:theme-transition-start";
export const THEME_TRANSITION_END = "showme:theme-transition-end";
/**
 * Emergency clear — emitted by the watchdog OR available to outside callers
 * who detect a stuck overlay (e.g. a future error boundary). The overlay
 * listens for it and synchronously force-clears active + depth state.
 */
export const THEME_TRANSITION_FORCE_END = "showme:theme-transition-force-end";

/** Brief overlay total runtime (ms): expand 180 + leave 100 ≈ 280. */
export const THEME_TRANSITION_DURATION_MS = 300;

/**
 * Hard watchdog. If `mutate` never runs (rAF chain dropped while a tab is
 * backgrounded) or the planned END is otherwise lost, the watchdog fires
 * END after this many ms so the overlay can never become a permanent
 * input-blocker. Picked to be comfortably above the planned end (300ms)
 * + a generous reflow budget so it never beats the happy path.
 */
export const THEME_TRANSITION_WATCHDOG_MS = 1200;

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
 * Emit a synchronous force-end. The overlay's listener resets `depth`,
 * cancels any pending leave timer, and hides itself immediately.
 */
export function forceEndThemeTransition(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(THEME_TRANSITION_FORCE_END));
}

/**
 * Run `mutate` (a heavy theme/density write that triggers layout reflow)
 * under a brief overlay so the user never sees the freeze.
 *
 * In SSR / reduced-motion / vitest: runs `mutate` synchronously without
 * overlay. In every other path, END is guaranteed to fire exactly once.
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

  let endFired = false;
  const fireEnd = () => {
    if (endFired) return;
    endFired = true;
    if (watchdog != null) {
      window.clearTimeout(watchdog);
      watchdog = null;
    }
    window.dispatchEvent(new CustomEvent(THEME_TRANSITION_END));
  };

  window.dispatchEvent(new CustomEvent(THEME_TRANSITION_START));

  // Hard watchdog — fires END if nothing else does, no matter what.
  let watchdog: number | null = window.setTimeout(
    fireEnd,
    THEME_TRANSITION_WATCHDOG_MS,
  );

  // Two rAF ticks: first lets React mount the overlay, second guarantees
  // the browser has actually painted the opaque overlay before we trigger
  // the reflow. Without the second tick, the mutation can land in the
  // same paint cycle as the mount and the freeze peeks through.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      try {
        mutate();
      } finally {
        // Even if `mutate` threw, schedule the planned END so the overlay
        // never gets stranded with `depth > 0` (which would keep it
        // visible AND, given the legacy CSS, eat every click).
        window.setTimeout(fireEnd, THEME_TRANSITION_DURATION_MS);
      }
    });
  });
}
