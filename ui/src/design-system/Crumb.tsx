import type { ReactNode } from "react";

interface CrumbSpec {
  label: ReactNode;
  href?: string;
  onClick?: () => void;
}

export function Crumbs({ items }: { items: CrumbSpec[] }) {
  return (
    <nav aria-label="breadcrumb" className="ds-crumbs">
      {items.map((it, idx) => {
        const isLast = idx === items.length - 1;
        return (
          <span key={idx} className="ds-crumbs__item">
            {idx > 0 && <span className="ds-crumbs__sep">›</span>}
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
  const klass = `ds-crumb${active ? " ds-crumb--active" : ""}`;
  if (href) {
    return (
      <a href={href} onClick={onClick} className={klass}>
        {label}
      </a>
    );
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={klass}>
        {label}
      </button>
    );
  }
  return <span className={klass}>{label}</span>;
}
