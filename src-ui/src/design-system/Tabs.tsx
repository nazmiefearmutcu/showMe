import type { ReactNode } from "react";

interface TabSpec {
  id: string;
  label: ReactNode;
  badge?: string | number;
}

interface TabsProps {
  items: TabSpec[];
  active: string;
  onChange: (id: string) => void;
  variant?: "underline" | "segmented";
}

export function Tabs({ items, active, onChange, variant = "underline" }: TabsProps) {
  if (variant === "segmented") {
    return (
      <div
        role="tablist"
        style={{
          display: "inline-flex",
          background: "var(--bg-elev-2)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          padding: 2,
          gap: 2,
        }}
      >
        {items.map((it) => {
          const isActive = it.id === active;
          return (
            <button
              role="tab"
              aria-selected={isActive}
              type="button"
              key={it.id}
              onClick={() => onChange(it.id)}
              style={{
                background: isActive ? "var(--bg-elev-3)" : "transparent",
                color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                border: "none",
                borderRadius: "var(--radius-sm)",
                padding: "4px 10px",
                fontSize: 11,
                letterSpacing: "0.02em",
                cursor: "default",
                transition: "background var(--motion-fast)",
              }}
            >
              {it.label}
              {it.badge != null && (
                <span style={{ marginLeft: 6, color: "var(--accent)" }}>
                  {it.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    );
  }
  return (
    <div
      role="tablist"
      style={{
        display: "flex",
        gap: 4,
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      {items.map((it) => {
        const isActive = it.id === active;
        return (
          <button
            role="tab"
            aria-selected={isActive}
            type="button"
            key={it.id}
            onClick={() => onChange(it.id)}
            style={{
              background: "transparent",
              border: "none",
              color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
              padding: "8px 12px 6px",
              fontSize: 12,
              borderBottom: `2px solid ${
                isActive ? "var(--accent)" : "transparent"
              }`,
              cursor: "default",
              transition: "color var(--motion-fast), border-color var(--motion-fast)",
            }}
          >
            {it.label}
            {it.badge != null && (
              <span
                style={{
                  marginLeft: 6,
                  color: "var(--text-mute)",
                  fontSize: 10,
                }}
              >
                {it.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function Tab({ children }: { children: ReactNode }) {
  return <div style={{ paddingTop: 12 }}>{children}</div>;
}
