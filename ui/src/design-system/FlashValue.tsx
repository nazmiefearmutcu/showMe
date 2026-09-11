/**
 * FlashValue — design-system primitive for value-change feedback.
 *
 * Wraps any rendered value (price cell, tile figure, watchlist row) and
 * paints the global one-shot flash keyframes (`.flash-pos` / `.flash-neg`,
 * tokens.css) whenever the numeric `value` changes direction. Composition
 * (children) is untouched — the wrapper only carries the fleeting class.
 *
 * Contract (frozen cross-lane):
 *   - no flash on first render (nothing to compare against);
 *   - null ↔ null / null ↔ number transitions never flash (no invented
 *     direction) — same math as lib/tick-flash's `tickDirection`;
 *   - class auto-clears after TICK_FLASH_MS;
 *   - timers are cleaned up on re-trigger and unmount (no setState after
 *     unmount, no leaked intervals).
 *
 * The direction math + hook live in `@/lib/tick-flash` so pane-local flash
 * consumers keep using the same single source; this file only maps the
 * direction to the shared CSS class and integrates it with React wrappers.
 */
import type { ReactNode } from "react";
import { tickFlashClass, useTickFlash } from "@/lib/tick-flash";

export interface FlashValueProps {
  /** Numeric value to watch. `null` = unknown (never flashes). */
  value: number | null;
  className?: string;
  children: ReactNode;
}

export function FlashValue({ value, className, children }: FlashValueProps) {
  const flash = useTickFlash(value);
  const flashClass = tickFlashClass(flash);
  const classes = [className, flashClass].filter(Boolean).join(" ");
  return (
    <span
      className={classes || undefined}
      data-flash={flash ?? undefined}
      data-testid="flash-value"
    >
      {children}
    </span>
  );
}

// Frozen interface: the hook is re-exported from the design system so panes
// can opt into the same pulse without reaching into lib/.
export { useTickFlash } from "@/lib/tick-flash";
