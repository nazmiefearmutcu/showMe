/**
 * Tick-flash primitive (upgrade U10, 2026-09-08).
 *
 * Welcome's market tiles re-render silently on every tick — the eye cannot
 * catch what moved. This module provides the DIRECTION math plus a tiny
 * hook that emits a short-lived "up"/"down" pulse state whenever a numeric
 * price changes. The visual is a 450 ms background animation in
 * styles/workspace-ux.css, declared only under
 * `prefers-reduced-motion: no-preference`.
 *
 * Deliberately store-free: `QuoteView` does not expose the previous price
 * (verified 2026-09-08), and the DO-NOT list forbids touching the data
 * layer for presentation. The hook keeps its own previous-value ref, so it
 * composes with any `price: number | null` source and never re-renders
 * anything beyond the component that calls it.
 */
import { useEffect, useRef, useState } from "react";

export type TickDirection = "up" | "down" | null;

/** How long the flash background stays visible (ms). Matches the CSS keyframes. */
export const TICK_FLASH_MS = 450;

/** Pure direction of a price move; null when either side is missing/invalid or flat. */
export function tickDirection(
  prev: number | null | undefined,
  next: number | null | undefined,
): TickDirection {
  if (prev == null || next == null) return null;
  if (!Number.isFinite(prev) || !Number.isFinite(next)) return null;
  if (next > prev) return "up";
  if (next < prev) return "down";
  return null;
}

/**
 * CSS class for a flash direction — single-sourced mapping so every
 * consumer (FlashValue, pane-local flashes) paints with the same global
 * `.flash-pos` / `.flash-neg` rules in tokens.css.
 */
export function tickFlashClass(dir: TickDirection): string | null {
  if (dir === "up") return "flash-pos";
  if (dir === "down") return "flash-neg";
  return null;
}

/**
 * Emit a one-shot flash direction each time `price` changes to a DIFFERENT
 * finite value. Equal values and first renders (no previous observation)
 * do not flash. The timer is cleaned up on unmount / re-trigger.
 */
export function useTickFlash(price: number | null | undefined): TickDirection {
  const [flash, setFlash] = useState<TickDirection>(null);
  const prevRef = useRef<number | null | undefined>(price);
  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = price;
    const dir = tickDirection(prev, price);
    if (!dir) return undefined;
    setFlash(dir);
    const timer = window.setTimeout(() => setFlash(null), TICK_FLASH_MS);
    return () => window.clearTimeout(timer);
  }, [price]);
  return flash;
}
