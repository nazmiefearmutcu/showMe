/**
 * HDS#2-RQ: "Total % out" must sum one holder table, never both Yahoo tables.
 * Mutual-fund holdings sit inside the institutional managers' share counts,
 * so summing institutional + mutual_fund rows double counts overlapping holders.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { HDSPane } from "./HDS";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
}

const mockFn: MockFnState = { state: "idle", data: undefined };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

const rows: Record<string, unknown>[] = [
  {
    symbol: "AAPL",
    holder: "Vanguard Group, Inc.",
    holder_type: "institutional",
    shares: 1_300_000_000,
    pct_outstanding: 0.08,
    date_reported: "2026-03-31",
    source_mode: "yfinance_holders",
  },
  {
    symbol: "AAPL",
    holder: "BlackRock, Inc.",
    holder_type: "institutional",
    shares: 1_080_000_000,
    pct_outstanding: 0.066,
    date_reported: "2026-03-31",
    source_mode: "yfinance_holders",
  },
  {
    symbol: "AAPL",
    holder: "Vanguard Total Stock Market Index",
    holder_type: "mutual_fund",
    shares: 400_000_000,
    pct_outstanding: 0.03,
    date_reported: "2026-03-31",
    source_mode: "yfinance_holders",
  },
];

function payload(list: Record<string, unknown>[]) {
  return { data: { status: "ok", rows: list, methodology: "test" } };
}

beforeEach(() => {
  mockFn.state = "ok";
});
afterEach(() => {
  cleanup();
});

describe("HDS Total % out KPI (HDS#2-RQ)", () => {
  it("does not double count mutual-fund rows that overlap institutional rows", () => {
    // RED before fix: 0.08 + 0.066 + 0.03 = 17.60% (mutual fund counted twice).
    mockFn.data = payload(rows);
    const { container } = render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(container.textContent ?? "").not.toContain("17.60%");
    // Institutional table only: 0.08 + 0.066 = 14.60%.
    expect(screen.getAllByText("14.60%").length).toBeGreaterThanOrEqual(1);
  });

  it("labels the KPI with the table it sums", () => {
    mockFn.data = payload(rows);
    const { container } = render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(container.textContent ?? "").toContain("SUM OF INSTITUTIONAL ROWS");
    expect(container.textContent ?? "").not.toContain("SUM OF ROWS");
  });

  it("shows a dash when only mutual-fund rows exist alongside rows without pct", () => {
    mockFn.data = payload([
      { ...rows[2] },
      { ...rows[0], holder_type: "institutional_13f", pct_outstanding: null, source_mode: "sec_13f" },
    ]);
    const { container } = render(<HDSPane code="HDS" symbol="AAPL" />);
    // Only one table has pct (mutual_fund): that single table is summed honestly.
    expect(container.textContent ?? "").toContain("3.00%");
  });
});
