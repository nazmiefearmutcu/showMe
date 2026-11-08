/**
 * HeatCell — single cell of a correlation matrix or a sector heatmap.
 *
 * Maps a `value` in [-1,1] (or any [-max, +max]) to a 5-step intensity
 * background. Diagonal cells (i == j) get a subdued look. Numeric label
 * is in tabular monospace so the matrix lines up.
 *
 * ROUND-2B: React.memo + CSS-only hover (PERF-09 P3) so 50×50 correlation
 * matrices don't ship 2,500 inline mouseenter/leave handlers.
 */

import { memo, type ReactNode } from "react";

export type HeatTone = "negative" | "positive" | "neutral";

export function intensityToken(value: number, range = 1): string {
  const ratio = Math.min(1, Math.abs(value) / range);
  const step = Math.max(1, Math.ceil(ratio * 5));
  if (value === 0) return "transparent";
  return value > 0 ? `var(--heat-pos-${step})` : `var(--heat-neg-${step})`;
}

interface HeatCellProps {
  /** `null` marks a missing cell: neutral, untinted, never shown as 0. */
  value: number | null;
  range?: number;
  diagonal?: boolean;
  size?: number;
  fractionDigits?: number;
  label?: ReactNode;
  onClick?: () => void;
  ariaLabel?: string;
  /**
   * Optional tab-index pass-through for roving-focus grids (FIX R1-F2).
   * Without it the caller's `tabIndex` on a wrapper never reaches this
   * natively focusable button, so every cell became a tab stop. Additive:
   * omitted (`undefined`) keeps the browser default focusability.
   */
  tabIndex?: number;
}

function HeatCellImpl({
  value,
  range = 1,
  diagonal = false,
  size = 40,
  fractionDigits = 2,
  label,
  onClick,
  ariaLabel,
  tabIndex,
}: HeatCellProps) {
  const missing = value === null;
  const bg = diagonal
    ? "var(--surface-1)"
    : value === null
      ? "transparent"
      : intensityToken(value, range);
  const ratio = value === null ? 0 : Math.min(1, Math.abs(value) / range);
  const fg =
    diagonal || missing
      ? "var(--text-mute)"
      : ratio > 0.5
        ? "var(--text-display)"
        : "var(--text-secondary)";
  const interactive = Boolean(onClick);
  const sign = value !== null && value > 0 ? "+" : "";
  const defaultAria =
    value === null ? "no value" : `value ${sign}${value.toFixed(fractionDigits)}`;
  const defaultLabel =
    value === null ? "—" : diagonal ? "—" : value.toFixed(fractionDigits);
  return (
    <button
      type="button"
      onClick={onClick}
      tabIndex={tabIndex}
      // `focus-ring` re-arms the global :focus-visible ring: this element's
      // inline `all: unset` would otherwise swallow it (Lane C utility).
      className={
        `showme-heat-cell focus-ring${interactive ? " showme-heat-cell--interactive" : ""}`
      }
      aria-label={ariaLabel ?? defaultAria}
      style={{
        all: "unset",
        cursor: interactive ? "pointer" : "default",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        background: bg,
        color: fg,
        fontSize: "var(--font-size-xs)",
        fontFamily: "var(--font-mono)",
        fontVariantNumeric: "tabular-nums",
        fontWeight: 500,
        border: "1px solid var(--border-row)",
        transition: "transform var(--motion-fast)",
      }}
    >
      {label ?? defaultLabel}
    </button>
  );
}

export const HeatCell = memo(HeatCellImpl);
