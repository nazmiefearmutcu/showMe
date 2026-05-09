import type { CSSProperties, InputHTMLAttributes, ReactNode } from "react";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  trailing?: ReactNode;
  width?: number | string;
}

export function Field({
  label, hint, trailing, width, ...rest
}: FieldProps) {
  return (
    <label
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        width: width ?? "100%",
      }}
    >
      <span
        style={{
          fontSize: 10,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: "var(--text-mute)",
        }}
      >
        {label}
      </span>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          background: "var(--bg-elev-2)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          height: 28,
          padding: "0 8px",
          transition: "border-color var(--motion-fast)",
        }}
      >
        <input
          {...rest}
          style={{
            background: "transparent",
            border: "none",
            outline: "none",
            color: "var(--text-primary)",
            font: "inherit",
            fontSize: 12,
            flex: 1,
            ...(rest.style as CSSProperties),
          }}
        />
        {trailing}
      </div>
      {hint && (
        <span style={{ fontSize: 10, color: "var(--text-mute)" }}>{hint}</span>
      )}
    </label>
  );
}

export function FieldRow({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12,
        alignItems: "end",
      }}
    >
      {children}
    </div>
  );
}
