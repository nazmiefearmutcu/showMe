/**
 * DeltaChip — small pill that conveys change direction + magnitude.
 *
 * Pass either `value` (negative ⇒ down) or both `value` and explicit
 * `direction`. Format hook covers % vs absolute. Soft pill background
 * tracks positive/negative tokens so dark and light themes both read.
 */

import { memo } from "react";

type Direction = "up" | "down" | "flat";

function DeltaChipImpl({
  value,
  direction,
  format = "percent",
  fractionDigits = 2,
  ariaLabel,
}: {
  value: number;
  direction?: Direction;
  format?: "percent" | "currency" | "raw";
  fractionDigits?: number;
  ariaLabel?: string;
}) {
  const dir: Direction = direction ?? (value > 0 ? "up" : value < 0 ? "down" : "flat");
  const tone =
    dir === "up" ? "positive" : dir === "down" ? "negative" : "muted";
  const fg =
    tone === "positive"
      ? "var(--positive)"
      : tone === "negative"
        ? "var(--negative)"
        : "var(--text-mute)";
  const bg =
    tone === "positive"
      ? "var(--positive-soft)"
      : tone === "negative"
        ? "var(--negative-soft)"
        : "color-mix(in srgb, var(--text-mute) 14%, transparent)";

  const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "—";
  const sign = value > 0 ? "+" : "";
  const formatted =
    format === "percent"
      ? `${sign}${value.toFixed(fractionDigits)}%`
      : format === "currency"
        ? `${sign}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: fractionDigits })}`
        : `${sign}${value.toLocaleString(undefined, { maximumFractionDigits: fractionDigits })}`;

  return (
    <span
      role="status"
      aria-label={ariaLabel ?? `change ${formatted}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "1px 6px",
        height: 18,
        minWidth: 0,
        borderRadius: 9,
        fontSize: 10,
        fontFamily: "JetBrains Mono, monospace",
        fontWeight: 600,
        background: bg,
        color: fg,
        whiteSpace: "nowrap",
      }}
    >
      <span aria-hidden style={{ fontSize: 8, lineHeight: 1 }}>
        {arrow}
      </span>
      {formatted}
    </span>
  );
}

export const DeltaChip = memo(DeltaChipImpl);
