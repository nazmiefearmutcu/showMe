import type { ReactNode } from "react";

/**
 * Toolbar — horizontal action bar for pane headers / dialog rows.
 * Children opt out of drag region via `.interactive`.
 */
export function Toolbar({ children }: { children: ReactNode }) {
  return (
    <div
      className="interactive"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "0 4px",
        height: 28,
      }}
    >
      {children}
    </div>
  );
}

export function ToolbarGroup({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        padding: "0 6px",
        borderRight: "1px solid var(--border-subtle)",
        height: 22,
      }}
    >
      {children}
    </div>
  );
}

export function ToolbarSpacer() {
  return <div style={{ flex: 1 }} />;
}
