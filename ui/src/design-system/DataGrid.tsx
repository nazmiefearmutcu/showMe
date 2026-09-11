/**
 * Virtualized, memoized data grid — round-3B (A11Y-08 semantic table
 * upgrade) + terminal-grade pane kit upgrade (L7, 2026-09-11).
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
 * ── L7 additions (all opt-in; the 88 existing consumers are untouched) ──
 *
 *  - Built-in sort: pass `defaultSortKey` (+ optional `defaultSortDir`) and
 *    the grid owns a tri-state sort (asc → desc → none), sorts rows with a
 *    stable comparator (numbers numerically, strings locale-aware, nullish
 *    always last) and draws `⇅ / ▲ / ▼` header affordances. Controlled
 *    consumers (`sortBy` + `onSort`) keep the exact legacy behavior.
 *  - Keyboard cell navigation (`keyboardNavigable`): Arrow keys, Home/End,
 *    Ctrl+Home/End, PageUp/PageDown, roving tabindex, `role="grid"`,
 *    `aria-rowindex` / `aria-colindex`, focus ring.
 *  - Clipboard: Ctrl/Cmd+C copies the focused cell, Ctrl/Cmd+Shift+C copies
 *    the focused row as TSV (`onCopyCell` / `onCopyRow` callbacks).
 *  - Column resize (`resizable`): drag the header separator; double-click
 *    resets a column to its declared width.
 */
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { copyTextToClipboard, scalarToText } from "./clipboard";

export type DataGridSortDir = "ascending" | "descending" | "none";

export interface DataGridColumn<T> {
  key: string;
  header: ReactNode;
  width?: number | string;
  align?: "left" | "right" | "center";
  render?: (row: T, index: number) => ReactNode;
  numeric?: boolean;
  sortable?: boolean;
  /** Raw accessor for the built-in sorter (defaults to `row[key]`). */
  sortValue?: (row: T) => unknown;
}

export interface DataGridCopyEvent<T> {
  kind: "cell" | "row";
  text: string;
  row: T;
  index: number;
  columnKey?: string;
}

export interface DataGridProps<T> {
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
  sortDir?: DataGridSortDir;
  /** Called when a sortable header is clicked (controlled mode). */
  onSort?: (key: string) => void;
  // ── L7 additions ───────────────────────────────────────────────────
  /** Initial sort column for the built-in (uncontrolled) sorter. */
  defaultSortKey?: string;
  /** Initial direction for the built-in sorter (default "ascending"). */
  defaultSortDir?: DataGridSortDir;
  /** Notified whenever the built-in sorter cycles (uncontrolled mode). */
  onSortChange?: (key: string, dir: DataGridSortDir) => void;
  /** Enables keyboard cell navigation + roving tabindex + copy shortcuts. */
  keyboardNavigable?: boolean;
  /** Clipboard accessor for a cell (defaults to the raw row value). */
  getCellText?: (row: T, column: DataGridColumn<T>, index: number) => string;
  /** Called after a Ctrl/Cmd+C cell copy. */
  onCopyCell?: (text: string, row: T, columnKey: string, index: number) => void;
  /** Called after a Ctrl/Cmd+Shift+C row copy (TSV). */
  onCopyRow?: (text: string, row: T, index: number) => void;
  /** Enables pointer-driven column resizing handles in the header. */
  resizable?: boolean;
  /** Minimum width (px) when resizing a column (default 56). */
  minColumnWidth?: number;
}

// Desk-instrument density (DESIGN-BRIEF law 6): rows live in the 24-26px
// band; never below 24px so interactive rows keep a legal hit target.
const ROW_HEIGHT: Record<"compact" | "comfortable", number> = {
  compact: 24,
  comfortable: 26,
};

const VIRTUAL_THRESHOLD = 100;
const DEFAULT_RESIZE_WIDTH = 140;

function textTitle(value: ReactNode): string | undefined {
  if (typeof value === "string" || typeof value === "number") return String(value);
  return undefined;
}

function colWidth(width: number | string | undefined): string {
  if (width == null) return "auto";
  return typeof width === "number" ? `${width}px` : width;
}

/**
 * Stable comparator for the built-in sorter. Numbers compare numerically
 * (non-finite sorts last), strings locale-compare with numeric collation;
 * nullish values always sink to the bottom regardless of direction.
 */
export function compareGridValues(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "number" && typeof b === "number") {
    const af = Number.isFinite(a);
    const bf = Number.isFinite(b);
    if (af && bf) return a - b;
    if (af) return -1;
    if (bf) return 1;
    return 0;
  }
  return String(a).localeCompare(String(b), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function defaultSortValue<T>(row: T, column: DataGridColumn<T>): unknown {
  return (row as unknown as Record<string, unknown>)[column.key];
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
  defaultSortKey,
  defaultSortDir = "ascending",
  onSortChange,
  keyboardNavigable = false,
  getCellText,
  onCopyCell,
  onCopyRow,
  resizable = false,
  minColumnWidth = 56,
}: DataGridProps<T>) {
  const rowHeight = ROW_HEIGHT[density];
  // A provided `onSort` means the consumer owns the sort state (legacy
  // PORT/TXNS/WEI pattern passes `sortBy={state ?? undefined}` while always
  // wiring `onSort`). Only `defaultSortKey` without `onSort`/`sortBy` opts
  // into the built-in sorter.
  const controlled = sortBy !== undefined || onSort !== undefined;
  const internalEnabled = !controlled && defaultSortKey !== undefined;

  const [internalSort, setInternalSort] = useState<{ key?: string; dir: DataGridSortDir }>(
    () => ({ key: defaultSortKey, dir: defaultSortDir }),
  );
  const [widths, setWidths] = useState<Record<string, number>>({});
  const [resizeDrag, setResizeDrag] = useState<{
    key: string;
    startX: number;
    startWidth: number;
  } | null>(null);
  const [activeCell, setActiveCell] = useState({ row: 0, col: 0 });
  const [navFocused, setNavFocused] = useState(false);

  const viewRows = useMemo(() => {
    if (!internalEnabled || !internalSort.key || internalSort.dir === "none") return rows;
    const column = columns.find((c) => c.key === internalSort.key);
    if (!column) return rows;
    const dirMul = internalSort.dir === "descending" ? -1 : 1;
    const accessor = (row: T) =>
      column.sortValue ? column.sortValue(row) : defaultSortValue(row, column);
    return rows
      .map((row, index) => ({ row, index }))
      .sort((a, b) => {
        const av = accessor(a.row);
        const bv = accessor(b.row);
        if (av == null && bv == null) return a.index - b.index;
        if (av == null) return 1;
        if (bv == null) return -1;
        const cmp = compareGridValues(av, bv);
        if (cmp !== 0) return dirMul * cmp;
        return a.index - b.index;
      })
      .map((entry) => entry.row);
  }, [rows, columns, internalEnabled, internalSort.key, internalSort.dir]);

  const shouldVirtualize =
    virtualize === true ||
    (virtualize !== false && viewRows.length > VIRTUAL_THRESHOLD);

  const scrollRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: viewRows.length,
    estimateSize: () => rowHeight,
    overscan: 8,
    getScrollElement: () => scrollRef.current,
  });

  // Keep the roving active cell inside the current row/column bounds.
  useEffect(() => {
    setActiveCell((c) => {
      const row = Math.min(c.row, Math.max(0, viewRows.length - 1));
      const col = Math.min(c.col, Math.max(0, columns.length - 1));
      return row === c.row && col === c.col ? c : { row, col };
    });
  }, [viewRows.length, columns.length]);

  const focusCellAfterMove = useRef(false);
  useEffect(() => {
    if (!focusCellAfterMove.current) return;
    focusCellAfterMove.current = false;
    const selector = `[data-cell="${activeCell.row}-${activeCell.col}"]`;
    let attempts = 0;
    let rafId: number | null = null;
    const tryFocus = () => {
      const el = scrollRef.current?.querySelector<HTMLElement>(selector);
      if (el) {
        el.focus();
        return;
      }
      // A virtualized row can mount a frame later (async measurement), so
      // retry a bounded number of frames instead of losing keyboard focus
      // until the next click (R1-F5).
      attempts += 1;
      if (attempts < 4) rafId = requestAnimationFrame(tryFocus);
    };
    tryFocus();
    return () => {
      if (rafId != null) cancelAnimationFrame(rafId);
    };
  }, [activeCell]);

  const moveActiveCell = useCallback(
    (row: number, col: number) => {
      const r = Math.max(0, Math.min(viewRows.length - 1, row));
      const c = Math.max(0, Math.min(columns.length - 1, col));
      focusCellAfterMove.current = true;
      setActiveCell({ row: r, col: c });
      if (shouldVirtualize) rowVirtualizer.scrollToIndex(r, { align: "auto" });
    },
    [viewRows.length, columns.length, shouldVirtualize, rowVirtualizer],
  );

  const cellText = useCallback(
    (row: T, column: DataGridColumn<T>, index: number): string => {
      if (getCellText) return getCellText(row, column, index);
      // Clipboard fallback uses the RAW cell value (not the sort accessor,
      // which may be a rank/score) so copied text matches the data model.
      return scalarToText(defaultSortValue(row, column));
    },
    [getCellText],
  );

  const handleSortActivate = useCallback(
    (key: string) => {
      if (controlled) {
        onSort?.(key);
        return;
      }
      if (!internalEnabled) return;
      const next: { key: string; dir: DataGridSortDir } =
        internalSort.key !== key
          ? { key, dir: "ascending" }
          : internalSort.dir === "ascending"
            ? { key, dir: "descending" }
            : internalSort.dir === "descending"
              ? { key, dir: "none" }
              : { key, dir: "ascending" };
      setInternalSort(next);
      onSortChange?.(key, next.dir);
    },
    [controlled, internalEnabled, internalSort.key, internalSort.dir, onSort, onSortChange],
  );

  // Resize drag lifecycle (pointer deltas — no layout reads needed in jsdom).
  useEffect(() => {
    if (!resizeDrag) return;
    const onMove = (e: MouseEvent) => {
      const next = Math.max(
        minColumnWidth,
        Math.round(resizeDrag.startWidth + (e.clientX - resizeDrag.startX)),
      );
      setWidths((w) => ({ ...w, [resizeDrag.key]: next }));
    };
    const onUp = () => setResizeDrag(null);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [resizeDrag, minColumnWidth]);

  const beginResize = useCallback(
    (e: ReactMouseEvent, key: string) => {
      e.preventDefault();
      e.stopPropagation();
      const column = columns.find((c) => c.key === key);
      const startWidth =
        widths[key] ??
        (typeof column?.width === "number" ? column.width : DEFAULT_RESIZE_WIDTH);
      setResizeDrag({ key, startX: e.clientX, startWidth });
    },
    [columns, widths],
  );

  const resetColumnWidth = useCallback((e: ReactMouseEvent, key: string) => {
    e.preventDefault();
    e.stopPropagation();
    setWidths((w) => {
      if (!(key in w)) return w;
      const copy = { ...w };
      delete copy[key];
      return copy;
    });
  }, []);

  const handleCellKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLTableCellElement>, row: T, idx: number, colIdx: number) => {
      const clientHeight = scrollRef.current?.clientHeight ?? 0;
      const page = Math.max(1, Math.round((clientHeight || 240) / rowHeight));
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          moveActiveCell(idx + 1, colIdx);
          break;
        case "ArrowUp":
          e.preventDefault();
          moveActiveCell(idx - 1, colIdx);
          break;
        case "ArrowRight":
          e.preventDefault();
          moveActiveCell(idx, colIdx + 1);
          break;
        case "ArrowLeft":
          e.preventDefault();
          moveActiveCell(idx, colIdx - 1);
          break;
        case "Home":
          e.preventDefault();
          if (e.ctrlKey || e.metaKey) moveActiveCell(0, 0);
          else moveActiveCell(idx, 0);
          break;
        case "End":
          e.preventDefault();
          if (e.ctrlKey || e.metaKey) moveActiveCell(viewRows.length - 1, columns.length - 1);
          else moveActiveCell(idx, columns.length - 1);
          break;
        case "PageDown":
          e.preventDefault();
          moveActiveCell(idx + page, colIdx);
          break;
        case "PageUp":
          e.preventDefault();
          moveActiveCell(idx - page, colIdx);
          break;
        case "Enter":
        case " ":
          if (onRowClick) {
            e.preventDefault();
            onRowClick(row, idx);
          }
          break;
        case "c":
        case "C": {
          if (!(e.ctrlKey || e.metaKey)) break;
          e.preventDefault();
          const column = columns[colIdx];
          if (!column) break;
          if (e.shiftKey) {
            const text = columns.map((c) => cellText(row, c, idx)).join("\t");
            copyTextToClipboard(text);
            onCopyRow?.(text, row, idx);
          } else {
            const text = cellText(row, column, idx);
            copyTextToClipboard(text);
            onCopyCell?.(text, row, column.key, idx);
          }
          break;
        }
        default:
          break;
      }
    },
    [cellText, columns, moveActiveCell, onCopyCell, onCopyRow, onRowClick, rowHeight, viewRows.length],
  );

  const containerStyle: CSSProperties = useMemo(
    () => ({
      overflow: "auto",
      minWidth: 0,
      maxWidth: "100%",
      border: "1px solid var(--border-subtle)",
      // Data surface geometry (DESIGN-BRIEF law 3): radius-sm max.
      borderRadius: "var(--radius-sm)",
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
          <col
            key={c.key}
            style={{
              width:
                resizable && widths[c.key] != null
                  ? `${widths[c.key]}px`
                  : colWidth(c.width),
            }}
          />
        ))}
      </colgroup>
    ),
    [columns, resizable, widths],
  );

  const headerCells = columns.map((c) => {
    const sortable = controlled
      ? Boolean(c.sortable && onSort)
      : Boolean(internalEnabled && (c.sortable || c.key === defaultSortKey));
    const ariaSort = sortable
      ? controlled
        ? sortBy === c.key
          ? (sortDir ?? "none")
          : undefined
        : internalSort.key === c.key
          ? internalSort.dir
          : undefined
      : undefined;
    const glyphDir = controlled
      ? sortBy === c.key
        ? (sortDir ?? "none")
        : "none"
      : internalSort.key === c.key
        ? internalSort.dir
        : "none";
    return (
      <th
        key={c.key}
        scope="col"
        title={textTitle(c.header)}
        aria-sort={ariaSort}
        tabIndex={sortable ? 0 : undefined}
        onClick={sortable ? () => handleSortActivate(c.key) : undefined}
        onKeyDown={
          sortable
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleSortActivate(c.key);
                }
              }
            : undefined
        }
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
        {sortable ? (
          <span
            aria-hidden="true"
            style={{
              marginLeft: 4,
              opacity: glyphDir === "none" ? 0.45 : 1,
              fontSize: "0.85em",
            }}
          >
            {glyphDir === "ascending" ? "▲" : glyphDir === "descending" ? "▼" : "⇅"}
          </span>
        ) : null}
        {resizable ? (
          <span
            aria-hidden="true"
            data-resize-key={c.key}
            onMouseDown={(e) => beginResize(e, c.key)}
            onDoubleClick={(e) => resetColumnWidth(e, c.key)}
            style={{
              position: "absolute",
              top: 0,
              right: 0,
              bottom: 0,
              width: 6,
              cursor: "col-resize",
              userSelect: "none",
              zIndex: 2,
              borderRight: "1px solid var(--border-subtle)",
            }}
          />
        ) : null}
      </th>
    );
  });

  if (viewRows.length === 0) {
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
          aria-colcount={columns.length}
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

  const renderRow = (row: T, idx: number) => (
    <DataGridRow
      key={rowKey ? rowKey(row, idx) : idx}
      row={row}
      idx={idx}
      columns={columns}
      rowHeight={rowHeight}
      rowClassName={rowClassName?.(row, idx)}
      onRowClick={onRowClick}
      onRowDoubleClick={onRowDoubleClick}
      keyboardNavigable={keyboardNavigable}
      activeCell={keyboardNavigable ? activeCell : null}
      navFocused={navFocused}
      onCellFocus={(r, c) => setActiveCell({ row: r, col: c })}
      onCellKeyDown={keyboardNavigable ? handleCellKeyDown : undefined}
    />
  );

  let body: ReactNode;
  if (shouldVirtualize) {
    const items = rowVirtualizer.getVirtualItems();
    const totalSize = rowVirtualizer.getTotalSize();
    const before = items.length > 0 ? items[0].start : 0;
    const after = items.length > 0 ? totalSize - items[items.length - 1].end : 0;
    body = (
      <tbody>
        {before > 0 ? <tr aria-hidden="true" style={{ height: before }} /> : null}
        {items.map((virtualRow) => renderRow(viewRows[virtualRow.index], virtualRow.index))}
        {after > 0 ? <tr aria-hidden="true" style={{ height: after }} /> : null}
      </tbody>
    );
  } else {
    body = <tbody>{viewRows.map((row, idx) => renderRow(row, idx))}</tbody>;
  }

  return (
    <div
      ref={scrollRef}
      className={className}
      style={containerStyle}
      onFocus={keyboardNavigable ? () => setNavFocused(true) : undefined}
      onBlur={keyboardNavigable ? () => setNavFocused(false) : undefined}
    >
      <table
        role={keyboardNavigable ? "grid" : "table"}
        aria-label={ariaLabel}
        aria-rowcount={viewRows.length + 1}
        aria-colcount={columns.length}
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
  keyboardNavigable?: boolean;
  activeCell?: { row: number; col: number } | null;
  navFocused?: boolean;
  onCellFocus?: (row: number, col: number) => void;
  onCellKeyDown?: (
    e: ReactKeyboardEvent<HTMLTableCellElement>,
    row: T,
    idx: number,
    colIdx: number,
  ) => void;
}

function DataGridRowImpl<T>({
  row,
  idx,
  columns,
  rowHeight,
  rowClassName,
  onRowClick,
  onRowDoubleClick,
  keyboardNavigable = false,
  activeCell,
  navFocused = false,
  onCellFocus,
  onCellKeyDown,
}: DataGridRowProps<T>) {
  // Row click / Enter affordance. When roving cell navigation is enabled the
  // cells own the tab stops (and Enter is handled at cell level), but pointer
  // clicks still activate the row.
  const interactive = Boolean(onRowClick);
  const rovingRows = interactive && !keyboardNavigable;
  return (
    <tr
      className={[
        rowClassName,
        interactive ? "showme-data-row showme-data-row--interactive" : "showme-data-row",
      ]
        .filter(Boolean)
        .join(" ")}
      role={rovingRows ? "button" : undefined}
      tabIndex={rovingRows ? 0 : undefined}
      aria-rowindex={idx + 2}
      onClick={interactive ? () => onRowClick?.(row, idx) : undefined}
      onDoubleClick={onRowDoubleClick ? () => onRowDoubleClick(row, idx) : undefined}
      onKeyDown={
        rovingRows
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
      {columns.map((c, colIdx) => {
        const value = c.render
          ? c.render(row, idx)
          : (row as unknown as Record<string, ReactNode>)[c.key];
        const isActive =
          keyboardNavigable &&
          activeCell != null &&
          activeCell.row === idx &&
          activeCell.col === colIdx;
        return (
          <td
            key={c.key}
            title={textTitle(value)}
            data-cell={keyboardNavigable ? `${idx}-${colIdx}` : undefined}
            aria-colindex={keyboardNavigable ? colIdx + 1 : undefined}
            tabIndex={keyboardNavigable ? (isActive ? 0 : -1) : undefined}
            onFocus={
              keyboardNavigable
                ? () => {
                    onCellFocus?.(idx, colIdx);
                  }
                : undefined
            }
            onKeyDown={
              keyboardNavigable && onCellKeyDown
                ? (e) => onCellKeyDown(e, row, idx, colIdx)
                : undefined
            }
            style={{
              padding: "var(--space-2) var(--space-5)",
              color: idx % 2 === 0 ? "var(--text-primary)" : "var(--text-secondary)",
              textAlign: c.align ?? (c.numeric ? "right" : "left"),
              fontVariantNumeric: c.numeric ? "tabular-nums" : undefined,
              minWidth: 0,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              outline: isActive && navFocused ? "1px solid var(--accent)" : undefined,
              outlineOffset: isActive && navFocused ? "-1px" : undefined,
              background: isActive && navFocused ? "var(--surface-2)" : undefined,
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
