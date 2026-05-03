/**
 * Signed numeric formatter — green for positive, red for negative, mute zero.
 * Always tabular-nums, always trailing-sign safe.
 */
export function ChangeText({
  value,
  digits = 2,
  prefix = "",
  suffix = "",
  signed = true,
}: {
  value: number | null | undefined;
  digits?: number;
  prefix?: string;
  suffix?: string;
  signed?: boolean;
}) {
  if (value == null || Number.isNaN(value)) {
    return <span style={{ color: "var(--text-mute)" }}>—</span>;
  }
  const color =
    value > 0
      ? "var(--positive)"
      : value < 0
        ? "var(--negative)"
        : "var(--text-mute)";
  const formatted =
    Math.abs(value).toLocaleString(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  const sign = signed ? (value > 0 ? "+" : value < 0 ? "−" : "") : "";
  return (
    <span
      style={{
        color,
        fontVariantNumeric: "tabular-nums",
        fontFeatureSettings: "'tnum' 1",
      }}
    >
      {sign}
      {prefix}
      {formatted}
      {suffix}
    </span>
  );
}
