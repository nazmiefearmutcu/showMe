import type { ReactNode } from "react";

type Tone = "neutral" | "positive" | "negative" | "accent" | "warn" | "muted";

const TONE: Record<Tone, string> = {
  neutral: "var(--neutral)",
  positive: "var(--positive)",
  negative: "var(--negative)",
  accent: "var(--accent)",
  warn: "var(--warn)",
  muted: "var(--text-mute)",
};

export function Pill({
  children,
  tone = "neutral",
  withDot = true,
}: {
  children: ReactNode;
  tone?: Tone;
  withDot?: boolean;
}) {
  const color = TONE[tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        minWidth: 0,
        maxWidth: "100%",
        padding: "0 8px",
        height: 18,
        borderRadius: 9,
        fontSize: 10,
        fontFamily: "JetBrains Mono, monospace",
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        fontWeight: 600,
        background: "var(--bg-elev-3)",
        color,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}
    >
      {withDot && (
        <span
          className="dot"
          style={{
            width: 6,
            flex: "0 0 6px",
            height: 6,
            borderRadius: "50%",
            background: "currentColor",
            boxShadow: "0 0 6px currentColor",
          }}
        />
      )}
      <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
        {children}
      </span>
    </span>
  );
}
