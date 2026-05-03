import type { CSSProperties, ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  density?: "comfortable" | "compact";
  variant?: "elev-1" | "elev-2";
  style?: CSSProperties;
}

const PAD: Record<"comfortable" | "compact", string> = {
  comfortable: "12px 14px",
  compact: "8px 10px",
};

export function Card({
  children,
  className,
  density = "comfortable",
  variant = "elev-1",
  style,
}: CardProps) {
  return (
    <section
      className={className}
      style={{
        background:
          variant === "elev-1" ? "var(--bg-elev-1)" : "var(--bg-elev-2)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        padding: PAD[density],
        ...style,
      }}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  children,
  trailing,
}: {
  children: ReactNode;
  trailing?: ReactNode;
}) {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        gap: 12,
        marginBottom: 8,
      }}
    >
      <h2
        style={{
          margin: 0,
          fontSize: 11,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--accent)",
        }}
      >
        {children}
      </h2>
      {trailing && (
        <div style={{ fontSize: 11, color: "var(--text-mute)" }}>
          {trailing}
        </div>
      )}
    </header>
  );
}

export function CardBody({ children }: { children: ReactNode }) {
  return <div>{children}</div>;
}

export function CardFooter({ children }: { children: ReactNode }) {
  return (
    <footer
      style={{
        marginTop: 10,
        paddingTop: 8,
        borderTop: "1px solid var(--border-subtle)",
        fontSize: 11,
        color: "var(--text-secondary)",
      }}
    >
      {children}
    </footer>
  );
}
