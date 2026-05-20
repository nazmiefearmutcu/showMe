/**
 * Accessibility primitives — round-2B audit close-out (A11Y-02..06).
 *
 * Exports:
 *   useReducedMotion — listens to OS prefers-reduced-motion
 *   useFocusTrap     — traps Tab inside a modal element + restores focus
 *   useEscape        — calls a callback when the user hits Escape
 *   computeContrast  — WCAG 2.1 relative-luminance ratio
 */
import { useEffect, useRef, useState } from "react";
import { createFocusTrap, type FocusTrap } from "focus-trap";

/**
 * Returns true when the OS-level "prefers-reduced-motion: reduce" flag is set.
 * Components should swap infinite/sliding animations for instant transitions
 * when this returns true. The hook subscribes to the media query so a runtime
 * preference change re-renders the consumer.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (event: MediaQueryListEvent) => setReduced(event.matches);
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    }
    // Safari < 14 fallback.
    mq.addListener(handler);
    return () => mq.removeListener(handler);
  }, []);

  return reduced;
}

/**
 * Trap Tab/Shift-Tab focus inside `containerRef` while `active` is true.
 * Restores focus to the previously focused element on deactivation.
 *
 * Usage:
 *   const ref = useRef<HTMLDivElement>(null);
 *   useFocusTrap(ref, isOpen);
 */
export function useFocusTrap(
  containerRef: React.RefObject<HTMLElement | null>,
  active: boolean,
): void {
  const trapRef = useRef<FocusTrap | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!active || !container) return;

    const trap = createFocusTrap(container, {
      escapeDeactivates: false, // Caller owns the Escape handler.
      clickOutsideDeactivates: true,
      returnFocusOnDeactivate: true,
      allowOutsideClick: true,
      // Fallback in case no focusable element is present yet (loading states).
      fallbackFocus: container,
      initialFocus: false,
    });
    trapRef.current = trap;
    try {
      trap.activate();
    } catch {
      // jsdom-friendly: focus-trap throws when there's nothing focusable.
      trapRef.current = null;
      return;
    }
    return () => {
      try {
        trap.deactivate();
      } catch {
        // ignore
      }
      trapRef.current = null;
    };
  }, [containerRef, active]);
}

/** Run `onEscape` when the document receives an Escape keydown while `active`. */
export function useEscape(active: boolean, onEscape: () => void): void {
  useEffect(() => {
    if (!active) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onEscape();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [active, onEscape]);
}

/**
 * Compute the WCAG 2.1 relative-luminance contrast ratio between two hex colors.
 * Accepts `#rgb` or `#rrggbb`; returns 1.0 (worst) … 21.0 (best).
 * Returns `null` when either input cannot be parsed.
 *
 * Used by Preferences to surface a live contrast warning when the user picks
 * surface=background or otherwise unreadable custom colors. UI-INT-03.
 */
export function computeContrast(a: string, b: string): number | null {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  if (la == null || lb == null) return null;
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Decide whether a hex color is "light" (relative luminance ≥ 0.5).
 * Used to flip overlay text/scrim direction when previewing user-picked
 * surfaces under Papyrus / custom-light themes.
 */
export function isLightHex(hex: string): boolean {
  const lum = relativeLuminance(hex);
  return lum != null && lum >= 0.5;
}

function relativeLuminance(hex: string): number | null {
  const rgb = parseHex(hex);
  if (!rgb) return null;
  const transform = (channel: number): number => {
    const v = channel / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  const [r, g, b] = rgb.map(transform);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function parseHex(hex: string): [number, number, number] | null {
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) {
    h = h
      .split("")
      .map((c) => c + c)
      .join("");
  }
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}
