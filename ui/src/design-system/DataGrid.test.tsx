/**
 * DataGrid smoke tests — round-3B (A11Y-08 semantic table upgrade) + L7
 * terminal-grade kit additions.
 *
 * round-3B contract:
 *   - renders as a real <table> (getByRole("table") returns the grid)
 *   - headers are <th scope="col"> (columnheader role)
 *   - row count is exposed via aria-rowcount
 *   - virtualization kicks in above the threshold
 *   - small grids render every row inline
 *   - rowKey is honored
 *   - aria-label is exposed for screen readers
 *   - aria-sort is set on the active sort column
 *   - interactive rows expose role=button / tabIndex
 *
 * L7 additions (all opt-in):
 *   - built-in tri-state sort via defaultSortKey + stable comparator
 *   - header keyboard activation (Enter / Space)
 *   - keyboard cell navigation + roving tabindex + aria row/col index
 *   - Ctrl/Cmd+C cell copy / Ctrl+Shift+C row copy (TSV)
 *   - column resize handles
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DataGrid, type DataGridColumn } from "./DataGrid";

interface Row {
  symbol: string;
  px: number;
}

const cols: DataGridColumn<Row>[] = [
  { key: "symbol", header: "Symbol" },
  { key: "px", header: "Price", numeric: true },
];

const small: Row[] = Array.from({ length: 20 }, (_, i) => ({
  symbol: `AAA${i}`,
  px: 100 + i,
}));

const large: Row[] = Array.from({ length: 250 }, (_, i) => ({
  symbol: `LRG${i}`,
  px: i,
}));

interface UnsortedRow {
  id: string;
  rank: number;
}

const unsorted: UnsortedRow[] = [
  { id: "mid", rank: 5 },
  { id: "low", rank: 1 },
  { id: "high", rank: 9 },
];

const rankCols: DataGridColumn<UnsortedRow>[] = [
  { key: "id", header: "Id" },
  { key: "rank", header: "Rank", numeric: true, sortable: true },
];

function bodyTexts(container: HTMLElement): string {
  return Array.from(container.querySelectorAll("tbody tr"))
    .map((tr) => tr.textContent ?? "")
    .join("|");
}

function activeCellIndex(container: HTMLElement): string | null {
  const node = container.querySelector<HTMLElement>('td[tabindex="0"]');
  return node?.getAttribute("data-cell") ?? null;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("DataGrid", () => {
  it("renders as a semantic <table>", () => {
    render(<DataGrid columns={cols} rows={small} ariaLabel="Test grid" />);
    const table = screen.getByRole("table");
    expect(table).toBeTruthy();
    expect(table.tagName).toBe("TABLE");
    expect(table.getAttribute("aria-label")).toBe("Test grid");
  });

  it("exposes column headers via <th scope=col>", () => {
    render(<DataGrid columns={cols} rows={small} ariaLabel="hdrs" />);
    const headers = screen.getAllByRole("columnheader");
    expect(headers.length).toBe(cols.length);
    headers.forEach((h) => {
      expect(h.tagName).toBe("TH");
      expect(h.getAttribute("scope")).toBe("col");
    });
    expect(headers[0].textContent).toBe("Symbol");
    expect(headers[1].textContent).toBe("Price");
  });

  it("reports the row count via aria-rowcount (header row included)", () => {
    render(<DataGrid columns={cols} rows={small} ariaLabel="rc" />);
    const table = screen.getByRole("table");
    // R2-F10: the ARIA spec counts the header row; data rows are indexed
    // from 2 in every mode, so the total is rows + 1.
    expect(table.getAttribute("aria-rowcount")).toBe(String(small.length + 1));
    const firstRow = screen.getByText("AAA0").closest("tr");
    expect(firstRow?.getAttribute("aria-rowindex")).toBe("2");
  });

  it("renders every row inline below the virtualization threshold", () => {
    render(<DataGrid columns={cols} rows={small} ariaLabel="inline" />);
    expect(screen.getByText("AAA0")).toBeTruthy();
    expect(screen.getByText("AAA19")).toBeTruthy();
  });

  it("virtualizes large row counts (windowed under real metrics)", async () => {
    // R1-F6: without mocked metrics jsdom renders zero rows and this test
    // could never fail. TanStack measures offsetHeight/offsetWidth, so pin a
    // 200px viewport there to force a real virtual window.
    const heightSpy = vi
      .spyOn(HTMLElement.prototype, "offsetHeight", "get")
      .mockReturnValue(200);
    const widthSpy = vi
      .spyOn(HTMLElement.prototype, "offsetWidth", "get")
      .mockReturnValue(800);
    try {
      const { container } = render(
        <DataGrid columns={cols} rows={large} virtualize ariaLabel="virt" />,
      );
      await act(async () => {
        await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
      });
      const table = container.querySelector("table");
      expect(table).toBeTruthy();
      const allMatches = (table?.textContent ?? "").match(/LRG\d+/g) ?? [];
      // A real window: some rows rendered — but never all 250.
      expect(allMatches.length).toBeGreaterThan(0);
      expect(allMatches.length).toBeLessThan(large.length);
    } finally {
      heightSpy.mockRestore();
      widthSpy.mockRestore();
    }
  });

  it("keeps roving focus on the target cell after PageDown (virtual window shift)", async () => {
    // R1-F5 regression: focus follow used to be one-shot; if the target row
    // mounted a frame later, the grid went keyboard-dead until a click.
    const heightSpy = vi
      .spyOn(HTMLElement.prototype, "offsetHeight", "get")
      .mockReturnValue(200);
    const widthSpy = vi
      .spyOn(HTMLElement.prototype, "offsetWidth", "get")
      .mockReturnValue(800);
    try {
      render(
        <DataGrid columns={cols} rows={large} virtualize keyboardNavigable ariaLabel="navvirt" />,
      );
      await act(async () => {
        await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
      });
      const firstCell = document.querySelector<HTMLElement>('[data-cell="0-0"]');
      expect(firstCell).toBeTruthy();
      firstCell!.focus();
      fireEvent.keyDown(firstCell!, { key: "PageDown" });
      await act(async () => {
        await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
      });
      // Page size = max(1, round((clientHeight || 240) / rowHeight)) — derive
      // rowHeight from the rendered row so density changes don't break this.
      const rowHeightPx = Number(
        ((document.querySelector("tbody tr") as HTMLElement | null)?.style.height || "24px")
          .replace("px", ""),
      ) || 24;
      const expectedRow = Math.max(1, Math.round(240 / rowHeightPx));
      const active = document.activeElement as HTMLElement | null;
      expect(active?.getAttribute("data-cell")).toBe(`${expectedRow}-0`);
    } finally {
      heightSpy.mockRestore();
      widthSpy.mockRestore();
    }
  });

  it("renders the empty slot when rows is empty", () => {
    render(<DataGrid columns={cols} rows={[]} empty="nothing yet" ariaLabel="empty" />);
    expect(screen.getByText("nothing yet")).toBeTruthy();
    // Still a real table even when empty.
    expect(screen.getByRole("table")).toBeTruthy();
  });

  it("makes interactive rows focusable", () => {
    const { container } = render(
      <DataGrid columns={cols} rows={small} onRowClick={() => undefined} ariaLabel="int" />,
    );
    const rows = container.querySelectorAll(".showme-data-row--interactive");
    expect(rows.length).toBeGreaterThan(0);
    rows.forEach((row) => {
      expect(row.tagName).toBe("TR");
      expect(row.getAttribute("tabIndex")).toBe("0");
      expect(row.getAttribute("role")).toBe("button");
    });
  });

  it("annotates the active sort column with aria-sort", () => {
    const sortable: DataGridColumn<Row>[] = [
      { key: "symbol", header: "Symbol", sortable: true },
      { key: "px", header: "Price", numeric: true, sortable: true },
    ];
    render(
      <DataGrid
        columns={sortable}
        rows={small}
        ariaLabel="sort"
        sortBy="px"
        sortDir="descending"
        onSort={() => undefined}
      />,
    );
    const headers = screen.getAllByRole("columnheader");
    expect(headers[0].getAttribute("aria-sort")).toBeNull();
    expect(headers[1].getAttribute("aria-sort")).toBe("descending");
  });
});

describe("DataGrid — built-in sort (L7)", () => {
  it("sorts rows by defaultSortKey with aria-sort and header affordance", () => {
    const { container } = render(
      <DataGrid
        columns={rankCols}
        rows={unsorted}
        ariaLabel="sorted"
        defaultSortKey="rank"
        defaultSortDir="ascending"
      />,
    );
    expect(bodyTexts(container)).toBe("low1|mid5|high9");
    const headers = screen.getAllByRole("columnheader");
    expect(headers[1].getAttribute("aria-sort")).toBe("ascending");
    // Affordance glyph rides along with the sortable header.
    expect(headers[1].textContent).toContain("▲");
  });

  it("cycles asc → desc → none on header click (tri-state)", () => {
    const onSortChange = vi.fn();
    const { container } = render(
      <DataGrid
        columns={rankCols}
        rows={unsorted}
        ariaLabel="cycle"
        defaultSortKey="rank"
        defaultSortDir="ascending"
        onSortChange={onSortChange}
      />,
    );
    const header = screen.getAllByRole("columnheader")[1];
    fireEvent.click(header);
    expect(bodyTexts(container)).toBe("high9|mid5|low1");
    expect(header.getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(header);
    expect(bodyTexts(container)).toBe("mid5|low1|high9"); // original order
    expect(header.getAttribute("aria-sort")).toBe("none");
    fireEvent.click(header);
    expect(bodyTexts(container)).toBe("low1|mid5|high9");
    expect(header.getAttribute("aria-sort")).toBe("ascending");
    expect(onSortChange.mock.calls).toEqual([
      ["rank", "descending"],
      ["rank", "none"],
      ["rank", "ascending"],
    ]);
  });

  it("activates sorting from the keyboard (Enter / Space)", () => {
    const { container } = render(
      <DataGrid
        columns={rankCols}
        rows={unsorted}
        ariaLabel="kb-sort"
        defaultSortKey="rank"
        defaultSortDir="ascending"
      />,
    );
    const header = screen.getAllByRole("columnheader")[1];
    expect(header.getAttribute("tabIndex")).toBe("0");
    fireEvent.keyDown(header, { key: "Enter" });
    expect(bodyTexts(container)).toBe("high9|mid5|low1");
    fireEvent.keyDown(header, { key: " " });
    expect(bodyTexts(container)).toBe("mid5|low1|high9");
  });

  it("keeps controlled consumers untouched (no internal row sorting)", () => {
    const { container } = render(
      <DataGrid
        columns={rankCols}
        rows={unsorted}
        ariaLabel="controlled"
        sortBy="rank"
        sortDir="ascending"
        onSort={() => undefined}
      />,
    );
    expect(bodyTexts(container)).toBe("mid5|low1|high9");
  });
});

describe("DataGrid — keyboard cell navigation (L7)", () => {
  it("exposes grid semantics with row/col indexes and roving tabindex", () => {
    const { container } = render(
      <DataGrid columns={cols} rows={small} ariaLabel="nav" keyboardNavigable />,
    );
    const table = screen.getByRole("grid");
    expect(table.getAttribute("aria-rowcount")).toBe(String(small.length + 1));
    expect(table.getAttribute("aria-colcount")).toBe("2");
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].getAttribute("aria-rowindex")).toBe("2");
    expect(rows[0].querySelector("td")?.getAttribute("aria-colindex")).toBe("1");
    expect(container.querySelector('[data-cell="0-0"]')?.getAttribute("tabindex")).toBe("0");
    expect(container.querySelector('[data-cell="0-1"]')?.getAttribute("tabindex")).toBe("-1");
  });

  it("moves the active cell with arrows, Home/End and PageDown", () => {
    const { container } = render(
      <DataGrid columns={cols} rows={small} ariaLabel="nav2" keyboardNavigable />,
    );
    const cell = (r: number, c: number) =>
      container.querySelector<HTMLElement>(`[data-cell="${r}-${c}"]`)!;
    const press = (key: string) => {
      const target =
        container.querySelector<HTMLElement>('td[tabindex="0"]') ?? cell(0, 0);
      fireEvent.keyDown(target, { key });
    };
    fireEvent.focus(cell(0, 0));
    press("ArrowDown");
    expect(activeCellIndex(container)).toBe("1-0");
    press("ArrowRight");
    expect(activeCellIndex(container)).toBe("1-1");
    press("Home");
    expect(activeCellIndex(container)).toBe("1-0");
    press("End");
    expect(activeCellIndex(container)).toBe("1-1");
    press("PageDown");
    expect(activeCellIndex(container)).toBe("10-1");
    press("PageUp");
    expect(activeCellIndex(container)).toBe("1-1");
    press("ArrowUp");
    press("ArrowUp");
    expect(activeCellIndex(container)).toBe("0-1"); // clamped at the top
  });

  it("activates the row from a focused cell (Enter)", () => {
    const onRowClick = vi.fn();
    const { container } = render(
      <DataGrid
        columns={cols}
        rows={small}
        ariaLabel="nav3"
        keyboardNavigable
        onRowClick={onRowClick}
      />,
    );
    const cell = container.querySelector<HTMLElement>('[data-cell="2-0"]')!;
    fireEvent.focus(cell);
    fireEvent.keyDown(cell, { key: "Enter" });
    expect(onRowClick).toHaveBeenCalledWith(small[2], 2);
  });
});

describe("DataGrid — clipboard copy (L7)", () => {
  it("copies the focused cell on Ctrl+C and the row as TSV on Ctrl+Shift+C", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    const onCopyCell = vi.fn();
    const onCopyRow = vi.fn();
    const { container } = render(
      <DataGrid
        columns={cols}
        rows={small}
        ariaLabel="copy"
        keyboardNavigable
        getCellText={(row, column) =>
          column.key === "px" ? `$${row.px.toFixed(2)}` : row.symbol
        }
        onCopyCell={onCopyCell}
        onCopyRow={onCopyRow}
      />,
    );
    const cell = container.querySelector<HTMLElement>('[data-cell="2-1"]')!;
    fireEvent.focus(cell);
    fireEvent.keyDown(cell, { key: "c", ctrlKey: true });
    expect(writeText).toHaveBeenCalledWith("$102.00");
    expect(onCopyCell).toHaveBeenCalledWith("$102.00", small[2], "px", 2);
    fireEvent.keyDown(cell, { key: "C", ctrlKey: true, shiftKey: true });
    expect(writeText).toHaveBeenCalledWith("AAA2\t$102.00");
    expect(onCopyRow).toHaveBeenCalledWith("AAA2\t$102.00", small[2], 2);
  });

  it("falls back to the raw row value when no clipboard accessor is given", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    const { container } = render(
      <DataGrid columns={cols} rows={small} ariaLabel="copy-raw" keyboardNavigable />,
    );
    const cell = container.querySelector<HTMLElement>('[data-cell="3-1"]')!;
    fireEvent.focus(cell);
    fireEvent.keyDown(cell, { key: "c", ctrlKey: true });
    expect(writeText).toHaveBeenCalledWith("103");
  });
});

describe("DataGrid — column resize (L7)", () => {
  it("resizes via the header handle and resets on double-click", () => {
    const widthCols: DataGridColumn<Row>[] = [
      { key: "symbol", header: "Symbol", width: 100 },
      { key: "px", header: "Price", width: 80 },
    ];
    const { container } = render(
      <DataGrid columns={widthCols} rows={small} ariaLabel="resize" resizable />,
    );
    const firstCol = () => container.querySelectorAll("colgroup col")[0] as HTMLElement;
    expect(firstCol().style.width).toBe("100px");
    const handle = container.querySelector<HTMLElement>('[data-resize-key="symbol"]')!;
    fireEvent.mouseDown(handle, { clientX: 200 });
    fireEvent.mouseMove(window, { clientX: 240 });
    expect(firstCol().style.width).toBe("140px");
    fireEvent.mouseUp(window);
    fireEvent.doubleClick(handle);
    expect(firstCol().style.width).toBe("100px");
  });

  it("clamps resizing at minColumnWidth", () => {
    const widthCols: DataGridColumn<Row>[] = [
      { key: "symbol", header: "Symbol", width: 100 },
    ];
    const { container } = render(
      <DataGrid columns={widthCols} rows={small} ariaLabel="resize-min" resizable minColumnWidth={60} />,
    );
    const handle = container.querySelector<HTMLElement>('[data-resize-key="symbol"]')!;
    fireEvent.mouseDown(handle, { clientX: 200 });
    fireEvent.mouseMove(window, { clientX: -500 });
    const col = container.querySelector("colgroup col") as HTMLElement;
    expect(col.style.width).toBe("60px");
    fireEvent.mouseUp(window);
  });
});
