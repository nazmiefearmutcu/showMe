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
  value: number;
  range?: number;
  diagonal?: boolean;
  size?: number;
  fractionDigits?: number;
  label?: ReactNode;
  onClick?: () => void;
  ariaLabel?: string;
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
}: HeatCellProps) {
  const bg = diagonal ? "var(--surface-1)" : intensityToken(value, range);
  const ratio = Math.min(1, Math.abs(value) / range);
  const fg = diagonal
    ? "var(--text-mute)"
    : ratio > 0.5
      ? "var(--text-display)"
      : "var(--text-secondary)";
  const interactive = Boolean(onClick);
  const sign = value > 0 ? "+" : value < 0 ? "" : "";
  return (
    <button
      type="button"
      onClick={onClick}
      className={interactive ? "showme-heat-cell showme-heat-cell--interactive" : "showme-heat-cell"}
      aria-label={ariaLabel ?? `value ${sign}${value.toFixed(fractionDigits)}`}
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
      {label ?? (diagonal ? "—" : value.toFixed(fractionDigits))}
    </button>
  );
}

export const HeatCell = memo(HeatCellImpl);
