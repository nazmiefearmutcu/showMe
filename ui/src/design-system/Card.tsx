import type { CSSProperties, ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  density?: "comfortable" | "compact";
  variant?: "elev-1" | "elev-2";
  style?: CSSProperties;
}

export function Card({
  children,
  className,
  density = "comfortable",
  variant = "elev-1",
  style,
}: CardProps) {
  return (
    <section
      className={`ds-card ds-card--${variant} ds-card--${density}${className ? ` ${className}` : ""}`}
      style={style}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  children,
  trailing,
  level = 2,
}: {
  children: ReactNode;
  trailing?: ReactNode;
  /**
   * Heading level. Defaults to `2`. Welcome / Preferences pass `3` so the
   * h1 (app) → h2 (pane) → h3 (subsection) ordering stays valid. A11Y-05.
   */
  level?: 1 | 2 | 3 | 4 | 5 | 6;
}) {
  const Tag = `h${level}` as "h2";
  return (
    <header className="ds-card__header">
      <Tag className="ds-card__title">{children}</Tag>
      {trailing && <div className="ds-card__trailing">{trailing}</div>}
    </header>
  );
}

export function CardBody({ children }: { children: ReactNode }) {
  return <div>{children}</div>;
}

export function CardFooter({ children }: { children: ReactNode }) {
  return <footer className="ds-card__footer">{children}</footer>;
}
