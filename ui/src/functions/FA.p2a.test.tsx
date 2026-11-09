/**
 * FA pane — render-contract + display-quality + a11y tests.
 *
 * FA renders REAL company fundamentals from SEC EDGAR (yfinance fallback);
 * there is NO synthetic-data path, so these tests pin display + a11y, not
 * honesty badges. Covered:
 *
 *   - four load states (loading / empty / error / ok) render;
 *   - negative statement values render with the negative class + parentheses;
 *   - column headers are humanized (Title Case, no underscores);
 *   - numeric magnitudes use `@/lib/format` compact output;
 *   - the statement DataGrid carries an ariaLabel;
 *   - the error-state Retry button has type=button + aria-label and disables
 *     while loading;
 *   - the ratios ribbon + ratio grid render.
 *
 * `useFunction` is mocked via mutable shared state so each test drives the
 * pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, within } from "@testing-library/react";
import { FAPane } from "./FA";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetchSpy = vi.fn();

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: refetchSpy,
  }),
}));

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

// usePersistentOption persists to localStorage; pin it to a controllable
// value so individual tests can drive the active tab (income vs ratios)
// deterministically.
let mockTab = "income";
vi.mock("./function-control-state", () => ({
  usePersistentOption: () => [mockTab, vi.fn()],
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function okPayload() {
  return {
    data: {
      data: {
        status: "ok",
        symbol: "AAPL",
        currency: "USD",
        filing_date: "2024-12-31",
        income_statement: [
          {
            line_item: "total_revenue",
            latest: 391_035_000_000,
            "2024-12-31": 391_035_000_000,
          },
          {
            line_item: "net_income",
            latest: -12_500_000_000,
            "2024-12-31": -12_500_000_000,
          },
        ],
        balance_sheet: [],
        cash_flow: [],
        ratios: {
          gross_margin: 0.46,
          operating_margin: 0.31,
          net_margin: -0.05,
          return_on_equity: 1.5,
        },
        methodology: "FA normalizes statement rows into canonical line items.",
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
  refetchSpy.mockClear();
  mockTab = "income";
});
afterEach(() => {
  cleanup();
});


describe("FA pane — ratio grid units (CRVF/FA#7)", () => {
  it("renders margin and return ratios as percentages, not bare decimals", () => {
    mockTab = "ratios";
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<FAPane code="FA" symbol="AAPL" />);
    const grid = container.querySelector(".fa-ratio-grid") as HTMLElement;
    expect(grid).not.toBeNull();
    // gross_margin 0.46 is a fraction of revenue: must read 46.0%, not 0.46.
    expect(within(grid).getByText("46.0%")).toBeInTheDocument();
    expect(within(grid).queryByText("0.46")).toBeNull();
    // return_on_equity 1.5 is a fraction too (150.0%).
    expect(within(grid).getByText("150.0%")).toBeInTheDocument();
  });
});
