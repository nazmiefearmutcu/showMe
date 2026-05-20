/**
 * StatusSection — one slot of a sectioned statusbar.
 *
 * Statusbar groups (left/center/right) drop these. Each section pairs a
 * tiny dot/icon, a small uppercase label, and optionally a value that's
 * monospaced + tabular. Separator borders are draw on the parent (not
 * here) so consecutive sections look like dividers, not boxes.
 */

import type { ReactNode } from "react";

type Tone = "neutral" | "positive" | "negative" | "accent" | "warn" | "muted";

const TONE_FG: Record<Tone, string> = {
  neutral: "var(--text-secondary)",
  positive: "var(--positive)",
  negative: "var(--negative)",
  accent: "var(--accent)",
  warn: "var(--warn)",
  muted: "var(--text-mute)",
};

export function StatusSection({
  icon,
  label,
  value,
  tone = "neutral",
  withDot = false,
  title,
}: {
  icon?: ReactNode;
  label?: ReactNode;
  value?: ReactNode;
  tone?: Tone;
  withDot?: boolean;
  title?: string;
}) {
  const fg = TONE_FG[tone];
  return (
    <span
      className={`ds-status${tone !== "neutral" ? ` ds-status--toned` : ""}`}
      style={{ ["--ds-status-fg" as string]: fg }}
      title={title}
    >
      {withDot && <span aria-hidden className="ds-status__dot" />}
      {icon && (
        <span aria-hidden className="ds-status__icon">{icon}</span>
      )}
      {label && <span className="ds-status__label">{label}</span>}
      {value !== undefined && value !== null && (
        <span className="ds-status__value">{value}</span>
      )}
    </span>
  );
}

export function StatusDivider() {
  return <span aria-hidden className="ds-status-divider" />;
}
