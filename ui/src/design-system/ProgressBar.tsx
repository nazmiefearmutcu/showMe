/**
 * ProgressBar — themed horizontal progress meter with inverted-text fill.
 *
 * The label appears in TWO colors: one color on the empty portion, the
 * inverted color on the filled portion. A single ``clip-path`` mask on
 * the "fill-color label" reveals exactly the filled fraction — no canvas,
 * no double-paint flicker, just CSS.
 *
 *     ▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░  →  fill div grows L→R
 *     [▓42%▓]    42% (light)                  ← bg label (full width)
 *                                             ← fill label clipped to 42%
 *
 * Wired to showMe theme tokens so the colors track ``--accent`` and
 * surface tints across the active preset. Shape is wide-and-thin
 * (default 14px tall) to match the "enine uzun, boyuna ince" brief — a
 * 48px tall pill would shout louder than the content it's reporting on.
 */
import type { CSSProperties } from "react";

export interface ProgressBarProps {
  /** Current percent in [0, 100]. Values outside the range are clamped. */
  value: number;
  /** Height in px. Default 14 — wide bar, thin profile. */
  height?: number;
  /** Override the displayed label. Default = ``{Math.round(value)}%``. */
  label?: string;
  /** Disable the % label entirely (e.g., for an indeterminate-ish look). */
  hideLabel?: boolean;
  /** Inline style overrides — useful for setting a fixed width. */
  style?: CSSProperties;
  /** Optional ARIA label for screen readers. */
  ariaLabel?: string;
}

export function ProgressBar({
  value,
  height = 14,
  label,
  hideLabel = false,
  style,
  ariaLabel,
}: ProgressBarProps) {
  // Defensive clamp — the backend can theoretically return >100 if a
  // future fix counts beyond `total`. Never trust the upstream blindly.
  const pct = Math.min(Math.max(Number.isFinite(value) ? value : 0, 0), 100);
  const text = label ?? `${Math.round(pct)}%`;

  // Font scales with bar height so the label always fits visually. The
  // mins/maxes keep it readable on the extremes (very thin or chunky
  // bars). Weight stays at 600 — the label is informational, not chrome.
  const fontSize = Math.max(10, Math.min(Math.round(height * 0.75), 13));

  return (
    <div
      role="progressbar"
      aria-label={ariaLabel ?? "progress"}
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      style={{
        position: "relative",
        width: "100%",
        height,
        // Empty-portion surface — borrows the same elevation token the
        // Skeleton uses so the bar feels at home in any Card.
        background: "var(--bg-elev-2, var(--surface-2, #1f2937))",
        border: "1px solid var(--border-subtle, rgba(255,255,255,0.08))",
        borderRadius: "var(--radius-sm, 4px)",
        overflow: "hidden",
        boxSizing: "border-box",
        ...style,
      }}
    >
      {/* Fill — width-driven, accent-tinted. ``transition: width`` keeps
          the bar smooth even when the polling cadence is choppy. */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          inset: "0 auto 0 0",
          width: `${pct}%`,
          background: "var(--accent, #5b9cf0)",
          transition: "width 200ms ease-out",
        }}
      />

      {!hideLabel && (
        <>
          {/* Bottom layer: label color used on the EMPTY portion. */}
          <span
            aria-hidden
            style={{
              ...labelBaseStyle(fontSize),
              color: "var(--text-secondary, rgba(255,255,255,0.62))",
            }}
          >
            {text}
          </span>
          {/* Top layer: label color used on the FILLED portion, clipped
              to exactly the filled fraction so it only shows over the
              fill div. ``inset(0 (100 - pct)% 0 0)`` crops from the
              right edge — same value as the fill width, inverted. */}
          <span
            aria-hidden
            style={{
              ...labelBaseStyle(fontSize),
              color: "var(--accent-contrast, var(--surface-1, #0b1018))",
              clipPath: `inset(0 ${100 - pct}% 0 0)`,
              transition: "clip-path 200ms ease-out",
            }}
          >
            {text}
          </span>
        </>
      )}
    </div>
  );
}

function labelBaseStyle(fontSize: number): CSSProperties {
  return {
    position: "absolute",
    inset: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily: "JetBrains Mono, ui-monospace, monospace",
    fontSize,
    fontWeight: 600,
    letterSpacing: "0.04em",
    pointerEvents: "none",
    userSelect: "none",
  };
}

ProgressBar.displayName = "ProgressBar";
