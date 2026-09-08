import type { ReactNode } from "react";

export function KbdHint({ children }: { children: ReactNode }) {
  return (
    <kbd
      style={{
        fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
        fontSize: 10,
        padding: "1px 5px",
        borderRadius: "var(--radius-sm, 4px)",
        border: "1px solid var(--line, var(--border-strong))",
        background: "var(--surface-2, var(--bg-elev-2))",
        color: "var(--text-secondary)",
      }}
    >
      {children}
    </kbd>
  );
}
