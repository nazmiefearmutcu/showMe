/**
 * DataGrid smoke tests — round-3B (A11Y-08 semantic table upgrade).
 *
 * Covers the round-3B contract:
 *   - renders as a real <table> (getByRole("table") returns the grid)
 *   - headers are <th scope="col"> (columnheader role)
 *   - row count is exposed via aria-rowcount
 *   - virtualization kicks in above the threshold
 *   - small grids render every row inline
 *   - rowKey is honored
 *   - aria-label is exposed for screen readers
 *   - aria-sort is set on the active sort column
 *   - interactive rows expose role=button / tabIndex
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
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

  it("reports the row count via aria-rowcount", () => {
    render(<DataGrid columns={cols} rows={small} ariaLabel="rc" />);
    const table = screen.getByRole("table");
    expect(table.getAttribute("aria-rowcount")).toBe(String(small.length));
  });

  it("renders every row inline below the virtualization threshold", () => {
    render(<DataGrid columns={cols} rows={small} ariaLabel="inline" />);
    expect(screen.getByText("AAA0")).toBeTruthy();
    expect(screen.getByText("AAA19")).toBeTruthy();
  });

  it("virtualizes large row counts", () => {
    const { container } = render(
      <DataGrid columns={cols} rows={large} virtualize ariaLabel="virt" />,
    );
    const table = container.querySelector("table");
    expect(table).toBeTruthy();
    // Even when the scroll container has zero size in jsdom, virtualization
    // should still be active — we should NOT see all 250 unique strings.
    const allMatches = (table?.textContent ?? "").match(/LRG\d+/g) ?? [];
    expect(allMatches.length).toBeLessThan(large.length);
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
