/**
 * OrbitMark — the showMe logo (sphere + arc).
 *
 * Used by the topbar wordmark and the splash screen. Color tracks
 * `--accent`; sizing scales the inner stroke widths so the look stays
 * consistent at 16px (titlebar) up to 120px (splash hero).
 */

export function OrbitMark({
  size = 18,
  pulse = false,
  ariaLabel = "showMe",
}: {
  size?: number;
  pulse?: boolean;
  ariaLabel?: string;
}) {
  const stroke = Math.max(1, size / 12);
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role="img"
      aria-label={ariaLabel}
      style={{
        display: "inline-block",
        animation: pulse ? "orbit-pulse 2200ms ease-in-out infinite" : undefined,
      }}
    >
      <defs>
        <radialGradient id="orbit-grad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--accent-strong)" stopOpacity="1" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.92" />
        </radialGradient>
      </defs>
      <circle cx="12" cy="12" r={size / 4} fill="url(#orbit-grad)" />
      <ellipse
        cx="12"
        cy="12"
        rx="9"
        ry="4"
        fill="none"
        stroke="var(--accent)"
        strokeOpacity="0.55"
        strokeWidth={stroke}
        transform="rotate(-22 12 12)"
        strokeLinecap="round"
      />
      <circle
        cx="20"
        cy="9"
        r={Math.max(0.8, size / 18)}
        fill="var(--accent-strong)"
      />
    </svg>
  );
}
