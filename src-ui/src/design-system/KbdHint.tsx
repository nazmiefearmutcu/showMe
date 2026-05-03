import type { ReactNode } from "react";

export function KbdHint({ children }: { children: ReactNode }) {
  return (
    <kbd
      style={{
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10,
        padding: "1px 5px",
        borderRadius: 3,
        border: "1px solid var(--border-strong)",
        background: "var(--bg-elev-2)",
        color: "var(--text-secondary)",
      }}
    >
      {children}
    </kbd>
  );
}
