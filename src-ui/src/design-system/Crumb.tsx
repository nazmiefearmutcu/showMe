import type { ReactNode } from "react";

interface CrumbSpec {
  label: ReactNode;
  href?: string;
  onClick?: () => void;
}

export function Crumbs({ items }: { items: CrumbSpec[] }) {
  return (
    <nav
      aria-label="breadcrumb"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        fontSize: 11,
        fontFamily: "JetBrains Mono, monospace",
        color: "var(--text-secondary)",
      }}
    >
      {items.map((it, idx) => {
        const isLast = idx === items.length - 1;
        return (
          <span key={idx} style={{ display: "flex", alignItems: "center" }}>
            {idx > 0 && (
              <span style={{ margin: "0 6px", color: "var(--text-mute)" }}>›</span>
            )}
            <Crumb {...it} active={isLast} />
          </span>
        );
      })}
    </nav>
  );
}

export function Crumb({
  label,
  href,
  onClick,
  active,
}: CrumbSpec & { active?: boolean }) {
  const color = active ? "var(--text-primary)" : "var(--text-secondary)";
  if (href) {
    return (
      <a
        href={href}
        onClick={onClick}
        style={{ color, textDecoration: "none" }}
      >
        {label}
      </a>
    );
  }
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        style={{
          background: "transparent",
          border: "none",
          color,
          cursor: "default",
          padding: 0,
          font: "inherit",
        }}
      >
        {label}
      </button>
    );
  }
  return <span style={{ color }}>{label}</span>;
}
