import type { CSSProperties, ReactNode } from "react";

export interface DataGridColumn<T> {
  key: string;
  header: ReactNode;
  width?: number | string;
  align?: "left" | "right" | "center";
  render?: (row: T, index: number) => ReactNode;
  numeric?: boolean;
}

interface DataGridProps<T> {
  columns: DataGridColumn<T>[];
  rows: T[];
  rowKey?: (row: T, idx: number) => string | number;
  empty?: ReactNode;
  density?: "compact" | "comfortable";
  onRowClick?: (row: T, idx: number) => void;
  onRowDoubleClick?: (row: T, idx: number) => void;
}

const ROW_HEIGHT: Record<"compact" | "comfortable", number> = {
  compact: 22,
  comfortable: 28,
};

export function DataGrid<T>({
  columns,
  rows,
  rowKey,
  empty,
  density = "comfortable",
  onRowClick,
  onRowDoubleClick,
}: DataGridProps<T>) {
  const grid: CSSProperties = {
    display: "grid",
    gridTemplateColumns: columns.map((c) => c.width ?? "1fr").map((w) =>
      typeof w === "number" ? `${w}px` : w,
    ).join(" "),
    fontSize: 12,
    fontFamily: "JetBrains Mono, monospace",
  };
  const rowBaseStyle: CSSProperties = {
    ...grid,
    borderBottom: "1px solid rgba(255,255,255,0.045)",
    alignItems: "center",
    minHeight: ROW_HEIGHT[density],
    cursor: onRowClick ? "default" : undefined,
    transition: onRowClick ? "background var(--motion-fast)" : undefined,
  };
  return (
    <div
      style={{
        overflow: "auto",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        background: "rgba(0,0,0,0.14)",
      }}
    >
      <div style={{ ...grid, position: "sticky", top: 0, background: "var(--bg-elev-2)", borderBottom: "1px solid var(--border-strong)" }}>
        {columns.map((c) => (
          <div
            key={c.key}
            style={{
              padding: "6px 10px",
              fontSize: 10,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: "var(--text-mute)",
              textAlign: c.align ?? (c.numeric ? "right" : "left"),
            }}
          >
            {c.header}
          </div>
        ))}
      </div>
      {rows.length === 0 ? (
        <div style={{ padding: 24, textAlign: "center", color: "var(--text-mute)" }}>
          {empty ?? "no rows"}
        </div>
      ) : (
        rows.map((row, idx) => (
          <div
            key={rowKey ? rowKey(row, idx) : idx}
            role={onRowClick ? "button" : undefined}
            tabIndex={onRowClick ? 0 : undefined}
            onClick={onRowClick ? () => onRowClick(row, idx) : undefined}
            onDoubleClick={
              onRowDoubleClick ? () => onRowDoubleClick(row, idx) : undefined
            }
            onKeyDown={
              onRowClick
                ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onRowClick(row, idx);
                    }
                  }
                : undefined
            }
            onMouseEnter={
              onRowClick
                ? (e) => ((e.currentTarget as HTMLElement).style.background = "var(--bg-elev-2)")
                : undefined
            }
            onMouseLeave={
              onRowClick
                ? (e) => ((e.currentTarget as HTMLElement).style.background = "transparent")
                : undefined
            }
            style={rowBaseStyle}
          >
            {columns.map((c) => {
              const value = c.render
                ? c.render(row, idx)
                : (row as unknown as Record<string, ReactNode>)[c.key];
              return (
                <div
                  key={c.key}
                  style={{
                    padding: "4px 10px",
                    color: idx % 2 === 0 ? "var(--text-primary)" : "var(--text-secondary)",
                    textAlign: c.align ?? (c.numeric ? "right" : "left"),
                    fontVariantNumeric: c.numeric ? "tabular-nums" : undefined,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {value}
                </div>
              );
            })}
          </div>
        ))
      )}
    </div>
  );
}
