/**
 * Virtualized, memoized data grid — round-3B (A11Y-08 semantic table upgrade).
 *
 * Uses a real <table> / <thead> / <tbody> / <tr> / <th> / <td> structure so
 * assistive tech announces headers, row count, and column index. The previous
 * implementation used CSS `display: grid` on plain divs, which prevented the
 * automatic screen-reader semantics.
 *
 * Virtualization (via @tanstack/react-virtual) is preserved: when row count
 * exceeds VIRTUAL_THRESHOLD we inject a single tall <tr> wrapper whose height
 * matches `getTotalSize()`, then position each visible <tr> with absolute
 * positioning + translateY. Below the threshold every row renders inline.
 *
 * The component is wrapped in `React.memo` so callers' `useMemo` on `cols`
 * keeps working.
 *
 * Header sorting hooks: `sortBy` + `sortDir` props let consumers wire ARIA
 * `aria-sort` on a column header without restructuring.
 */
import {
  memo,
  useMemo,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

export interface DataGridColumn<T> {
  key: string;
  header: ReactNode;
  width?: number | string;
  align?: "left" | "right" | "center";
  render?: (row: T, index: number) => ReactNode;
  numeric?: boolean;
  sortable?: boolean;
}

interface DataGridProps<T> {
  columns: DataGridColumn<T>[];
  rows: T[];
  className?: string;
  rowKey?: (row: T, idx: number) => string | number;
  rowClassName?: (row: T, idx: number) => string | undefined;
  empty?: ReactNode;
  density?: "compact" | "comfortable";
  onRowClick?: (row: T, idx: number) => void;
  onRowDoubleClick?: (row: T, idx: number) => void;
  /** ARIA label for the table — A11Y-04 P2 / A11Y-08. */
  ariaLabel?: string;
  /** Force virtualization on / off (default: auto when rows.length > 100). */
  virtualize?: boolean;
  /** Active sort column key, if any (drives `aria-sort` on the header). */
  sortBy?: string;
  /** Active sort direction; "none" suppresses aria-sort for that column. */
  sortDir?: "ascending" | "descending" | "none";
  /** Called when a sortable header is clicked. */
  onSort?: (key: string) => void;
}

const ROW_HEIGHT: Record<"compact" | "comfortable", number> = {
  compact: 22,
  comfortable: 28,
};

const VIRTUAL_THRESHOLD = 100;

function textTitle(value: ReactNode): string | undefined {
  if (typeof value === "string" || typeof value === "number") return String(value);
  return undefined;
}

function colWidth(width: number | string | undefined): string {
  if (width == null) return "auto";
  return typeof width === "number" ? `${width}px` : width;
}

function DataGridImpl<T>({
  columns,
  rows,
  className,
  rowKey,
  rowClassName,
  empty,
  density = "comfortable",
  onRowClick,
  onRowDoubleClick,
  ariaLabel,
  virtualize,
  sortBy,
  sortDir,
  onSort,
}: DataGridProps<T>) {
  const rowHeight = ROW_HEIGHT[density];

  const shouldVirtualize =
    virtualize === true ||
    (virtualize !== false && rows.length > VIRTUAL_THRESHOLD);

  const scrollRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    estimateSize: () => rowHeight,
    overscan: 8,
    getScrollElement: () => scrollRef.current,
  });

  const containerStyle: CSSProperties = useMemo(
    () => ({
      overflow: "auto",
      minWidth: 0,
      maxWidth: "100%",
      border: "1px solid var(--border-subtle)",
      borderRadius: "var(--radius-md)",
      background: "var(--scrim-low)",
      contain: "layout style paint",
    }),
    [],
  );

  const tableStyle: CSSProperties = useMemo(
    () => ({
      width: "100%",
      borderCollapse: "collapse",
      tableLayout: "fixed",
      fontSize: "var(--font-size-md)",
      fontFamily: "var(--font-mono)",
      minWidth: 0,
    }),
    [],
  );

  const colgroup = useMemo(
    () => (
      <colgroup>
        {columns.map((c) => (
          <col key={c.key} style={{ width: colWidth(c.width) }} />
        ))}
      </colgroup>
    ),
    [columns],
  );

  const headerCells = columns.map((c) => {
    const sortable = Boolean(c.sortable && onSort);
    const ariaSort = sortable && sortBy === c.key ? sortDir ?? "none" : undefined;
    return (
      <th
        key={c.key}
        scope="col"
        title={textTitle(c.header)}
        aria-sort={ariaSort}
        onClick={sortable ? () => onSort?.(c.key) : undefined}
        style={{
          padding: "var(--space-3) var(--space-5)",
          fontSize: "var(--font-size-xs)",
          letterSpacing: "var(--tracking-label)",
          textTransform: "uppercase",
          color: "var(--text-mute)",
          textAlign: c.align ?? (c.numeric ? "right" : "left"),
          fontWeight: 400,
          background: "var(--bg-elev-2)",
          borderBottom: "1px solid var(--border-strong)",
          position: "sticky",
          top: 0,
          zIndex: 1,
          cursor: sortable ? "pointer" : undefined,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {c.header}
      </th>
    );
  });

  if (rows.length === 0) {
    return (
      <div
        ref={scrollRef}
        className={className}
        style={containerStyle}
      >
        <table
          role="table"
          aria-label={ariaLabel}
          aria-rowcount={1}
          style={tableStyle}
        >
          {colgroup}
          <thead>
            <tr>{headerCells}</tr>
          </thead>
          <tbody>
            <tr>
              <td
                colSpan={columns.length}
                style={{
                  padding: "var(--space-7)",
                  textAlign: "center",
                  color: "var(--text-mute)",
                }}
              >
                {empty ?? "no rows"}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    );
  }

  let body: ReactNode;
  if (shouldVirtualize) {
    const items = rowVirtualizer.getVirtualItems();
    const totalSize = rowVirtualizer.getTotalSize();
    const before = items.length > 0 ? items[0].start : 0;
    const after = items.length > 0 ? totalSize - items[items.length - 1].end : 0;
    body = (
      <tbody>
        {before > 0 ? <tr aria-hidden="true" style={{ height: before }} /> : null}
        {items.map((virtualRow) => {
          const row = rows[virtualRow.index];
          return (
            <DataGridRow
              key={rowKey ? rowKey(row, virtualRow.index) : virtualRow.index}
              row={row}
              idx={virtualRow.index}
              columns={columns}
              rowHeight={rowHeight}
              rowClassName={rowClassName?.(row, virtualRow.index)}
              onRowClick={onRowClick}
              onRowDoubleClick={onRowDoubleClick}
            />
          );
        })}
        {after > 0 ? <tr aria-hidden="true" style={{ height: after }} /> : null}
      </tbody>
    );
  } else {
    body = (
      <tbody>
        {rows.map((row, idx) => (
          <DataGridRow
            key={rowKey ? rowKey(row, idx) : idx}
            row={row}
            idx={idx}
            columns={columns}
            rowHeight={rowHeight}
            rowClassName={rowClassName?.(row, idx)}
            onRowClick={onRowClick}
            onRowDoubleClick={onRowDoubleClick}
          />
        ))}
      </tbody>
    );
  }

  return (
    <div
      ref={scrollRef}
      className={className}
      style={containerStyle}
    >
      <table
        role="table"
        aria-label={ariaLabel}
        aria-rowcount={rows.length}
        style={tableStyle}
      >
        {colgroup}
        <thead>
          <tr>{headerCells}</tr>
        </thead>
        {body}
      </table>
    </div>
  );
}

interface DataGridRowProps<T> {
  row: T;
  idx: number;
  columns: DataGridColumn<T>[];
  rowHeight: number;
  rowClassName?: string;
  onRowClick?: (row: T, idx: number) => void;
  onRowDoubleClick?: (row: T, idx: number) => void;
}

function DataGridRowImpl<T>({
  row,
  idx,
  columns,
  rowHeight,
  rowClassName,
  onRowClick,
  onRowDoubleClick,
}: DataGridRowProps<T>) {
  const interactive = Boolean(onRowClick);
  return (
    <tr
      className={[
        rowClassName,
        interactive ? "showme-data-row showme-data-row--interactive" : "showme-data-row",
      ]
        .filter(Boolean)
        .join(" ")}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? () => onRowClick?.(row, idx) : undefined}
      onDoubleClick={onRowDoubleClick ? () => onRowDoubleClick(row, idx) : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onRowClick?.(row, idx);
              }
            }
          : undefined
      }
      style={{
        borderBottom: "1px solid var(--border-row)",
        height: rowHeight,
        cursor: interactive ? "pointer" : undefined,
        transition: interactive ? "background var(--motion-fast)" : undefined,
      }}
    >
      {columns.map((c) => {
        const value = c.render
          ? c.render(row, idx)
          : (row as unknown as Record<string, ReactNode>)[c.key];
        return (
          <td
            key={c.key}
            title={textTitle(value)}
            style={{
              padding: "var(--space-2) var(--space-5)",
              color: idx % 2 === 0 ? "var(--text-primary)" : "var(--text-secondary)",
              textAlign: c.align ?? (c.numeric ? "right" : "left"),
              fontVariantNumeric: c.numeric ? "tabular-nums" : undefined,
              minWidth: 0,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {value}
          </td>
        );
      })}
    </tr>
  );
}

const DataGridRow = memo(DataGridRowImpl) as typeof DataGridRowImpl;

export const DataGrid = memo(DataGridImpl) as typeof DataGridImpl;
