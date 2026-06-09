import { memo, type ReactNode } from "react";

type Tone = "neutral" | "positive" | "negative" | "accent" | "warn" | "muted";
type Variant = "ghost" | "soft" | "filled";

function PillImpl({
  children,
  tone = "neutral",
  withDot = true,
  variant = "ghost",
  arrow,
  "aria-label": ariaLabel,
}: {
  children: ReactNode;
  tone?: Tone;
  withDot?: boolean;
  variant?: Variant;
  arrow?: "up" | "down" | null;
  /** Accessible name — use when the visible text alone is ambiguous. */
  "aria-label"?: string;
}) {
  return (
    <span
      className={`ds-pill ds-pill--${variant} ds-pill--tone-${tone}`}
      aria-label={ariaLabel}
    >
      {withDot && <span className="dot ds-pill__dot" />}
      {arrow && <span aria-hidden className="ds-pill__arrow">{arrow === "up" ? "▲" : "▼"}</span>}
      <span className="ds-pill__label">{children}</span>
    </span>
  );
}

export const Pill = memo(PillImpl);
