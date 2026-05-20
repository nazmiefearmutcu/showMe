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
      <div role="tablist" className="tabs--segmented">
        {items.map((it) => {
          const isActive = it.id === active;
          return (
            <button
              role="tab"
              aria-selected={isActive}
              type="button"
              key={it.id}
              onClick={() => onChange(it.id)}
              className={`tabs__seg${isActive ? " tabs__seg--active" : ""}`}
            >
              {it.label}
              {it.badge != null && <span className="tabs__seg-badge">{it.badge}</span>}
            </button>
          );
        })}
      </div>
    );
  }
  return (
    <div role="tablist" className="tabs--underline">
      {items.map((it) => {
        const isActive = it.id === active;
        return (
          <button
            role="tab"
            aria-selected={isActive}
            type="button"
            key={it.id}
            onClick={() => onChange(it.id)}
            className={`tabs__under${isActive ? " tabs__under--active" : ""}`}
          >
            {it.label}
            {it.badge != null && <span className="tabs__under-badge">{it.badge}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function Tab({ children }: { children: ReactNode }) {
  return <div className="tabs__panel">{children}</div>;
}
