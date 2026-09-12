/**
 * WACC pane — render-contract + CSV export tests.
 *
 * Pins:
 *  - the load states (error / ok) render;
 *  - the ok payload renders the component table + headline WACC card;
 *  - the CSV export ships the RAW decimal component values (0.0842, not
 *    the formatted "8.42%" string) and a dated honest filename;
 *  - the CSV button is disabled when the table has no rows.
 *
 * `useFunction` is mocked with a mutable shared state + an args recorder.
 * `downloadGridCsv` is mocked around the real builder so the export payload
 * can be asserted (jsdom has no Blob download).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WACCPane } from "./WACC";
import { downloadGridCsv } from "@/design-system/grid-csv";

/* ── mocks ─────────────────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[]; sources?: string[] } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetchMock = vi.fn();

interface RecordedArgs {
  code: string;
  symbol?: string;
  params?: Record<string, unknown>;
}

const lastArgs: RecordedArgs[] = [];

function lastCall(): RecordedArgs | undefined {
  return lastArgs[lastArgs.length - 1];
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: RecordedArgs) => {
    lastArgs.push(args);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchMock,
    };
  },
}));

// Keep the real CSV builder, but capture the download call so the export
// payload can be asserted (jsdom has no Blob download).
vi.mock("@/design-system/grid-csv", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/design-system/grid-csv")>();
  return { ...actual, downloadGridCsv: vi.fn(() => true) };
});

/* ── fixtures ──────────────────────────────────────────────────────── */

function surfaceCell(beta: number, rd: number, wacc: number) {
  return { bucket: `β ${beta} / Rd ${rd}`, beta, rd, wacc };
}

function okPayload() {
  return {
    data: {
      status: "ok",
      wacc: 0.0842,
      re_capm: 0.096,
      rf: 0.041,
      beta: 1.1,
      erp: 0.05,
      rd: 0.055,
      tax_rate: 0.21,
      equity_weight: 0.8,
      debt_weight: 0.2,
      rows: [
        { component: "Risk-free rate (rf)", value: 0.041, formula: "FRED DGS10" },
        { component: "Beta (β)", value: 1.1, formula: "BetaFunction 2Y" },
        {
          component: "Equity risk premium",
          value: 0.05,
          formula: "Damodaran ERP",
        },
        {
          component: "Cost of equity (Re)",
          value: 0.096,
          formula: "rf + β × ERP",
        },
        {
          component: "WACC",
          value: 0.0842,
          formula: "(E/V × Re) + (D/V × Rd × (1 − T))",
        },
      ],
      surface: [
        surfaceCell(0.9, 0.045, 0.0788),
        surfaceCell(1.0, 0.045, 0.0833),
        surfaceCell(1.1, 0.045, 0.0878),
        surfaceCell(0.9, 0.055, 0.08),
        surfaceCell(1.0, 0.055, 0.0845),
        surfaceCell(1.1, 0.055, 0.089),
        surfaceCell(0.9, 0.065, 0.0812),
        surfaceCell(1.0, 0.065, 0.0857),
        surfaceCell(1.1, 0.065, 0.0902),
      ],
      beta_source: "yfinance",
      beta_window: "2Y",
      data_state: "live",
      methodology: "WACC = (E/V × Re) + (D/V × Rd × (1 − T))",
    },
    sources: ["fred", "yfinance"],
    warnings: [],
    elapsed_ms: 42,
  };
}

beforeEach(() => {
  lastArgs.length = 0;
  refetchMock.mockClear();
  (downloadGridCsv as ReturnType<typeof vi.fn>).mockClear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});

/* ── tests ─────────────────────────────────────────────────────────── */

describe("WACC pane — render contract", () => {
  it("renders the headline WACC and the component table when ok", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    expect(container.textContent).toContain("8.42%");
    // 5 component rows.
    expect(container.querySelectorAll("tbody tr").length).toBe(5);
    expect(container.textContent).toContain("Equity risk premium");
    expect(lastCall()?.symbol).toBe("AAPL");
  });

  it("renders the error state when the fetch errors", () => {
    mockFn.state = "error";
    mockFn.error = new Error("sidecar exploded");
    render(<WACCPane code="WACC" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });
});

describe("WACC pane — grid CSV export", () => {
  it("exports the raw component table via the CSV button", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<WACCPane code="WACC" symbol="AAPL" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^wacc-AAPL-\d{4}-\d{2}-\d{2}\.csv$/);
    // Header + RAW decimals (0.0842, never the formatted "8.42%" string).
    expect(csv).toContain("Component,Value,Formula");
    expect(csv).toContain("WACC,0.0842,");
    expect(csv).not.toContain("8.42%");
  });

  it("disables the CSV button when the component table is empty", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "ok",
        wacc: 0.0842,
        rows: [],
        surface: [],
      },
      warnings: [],
    };
    render(<WACCPane code="WACC" symbol="AAPL" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
