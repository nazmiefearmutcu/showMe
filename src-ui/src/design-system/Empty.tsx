import type { ReactNode } from "react";

interface EmptyProps {
  title: string;
  body?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}

export function Empty({ title, body, action, icon = "∅" }: EmptyProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "48px 24px",
        gap: 8,
        color: "var(--text-secondary)",
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontSize: 32,
          color: "var(--text-mute)",
          fontFamily: "JetBrains Mono, monospace",
          opacity: 0.6,
        }}
      >
        {icon}
      </div>
      <strong style={{ color: "var(--text-primary)", fontSize: 13 }}>
        {title}
      </strong>
      {body && (
        <div style={{ fontSize: 11, color: "var(--text-mute)", maxWidth: 360 }}>
          {body}
        </div>
      )}
      {action && <div style={{ marginTop: 8 }}>{action}</div>}
    </div>
  );
}
