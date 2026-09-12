/**
 * YAS pane — render-contract + model-input tests.
 *
 * The backend YAS solves YTM from user inputs (price, coupon, maturity,
 * frequency, benchmark) and returns duration/convexity metrics plus a
 * ±100bp shock-price ladder. These tests pin:
 *
 *  - the load states (loading / error / empty / ok) render;
 *  - headline cards (YTM, spread bps, durations, convexity) format
 *    correctly from the payload;
 *  - the shock ladder renders price deltas vs the current price;
 *  - every input (bond, price, coupon, benchmark, freq) drives the fetch
 *    params, with percent inputs converted to decimals and persisted
 *    under `showme.yas.*`.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) plus
 * `lastParams`/`lastSymbol` capture.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { YASPane } from "./YAS";
import { downloadGridCsv } from "@/design-system/grid-csv";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    sources?: string[];
    elapsed_ms?: number;
    warnings?: string[];
  };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

let lastParams: Record<string, unknown> | undefined;
let lastSymbol: string | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: {
    code: string;
    symbol?: string;
    params?: Record<string, unknown>;
  }) => {
    lastParams = args.params;
    lastSymbol = args.symbol;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
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

/* ── fixtures: closed-form 10Y 4.25% semiannual @ 99.5 ─────────────── */

const SUMMARY = {
  bond: "US10Y",
  price: 99.5,
  face: 100,
  coupon_rate: 0.0425,
  coupon_pct: 4.25,
  maturity_years: 10,
  frequency: 2,
  benchmark_rate: 0.0445,
  benchmark_pct: 4.45,
  ytm: 0.04312,
  ytm_pct: 4.312,
  spread_vs_benchmark: -0.001379,
  spread_bps: -13.79,
};

const METRIC_ROWS = [
  { metric: "yield_to_maturity", value: 0.04312, display_pct: 4.312, unit: "decimal" },
  {
    metric: "spread_vs_benchmark",
    value: -0.001379,
    display_pct: -0.1379,
    spread_bps: -13.79,
    unit: "decimal",
  },
  { metric: "macaulay_duration", value: 8.244, unit: "years" },
  { metric: "modified_duration", value: 8.087, unit: "years" },
  { metric: "convexity", value: 78.6, unit: "price convexity" },
];

const CURVE = [
  { ytm_pct: 3.312, price: 107.915, shock_bps: -100 },
  { ytm_pct: 3.812, price: 103.611, shock_bps: -50 },
  { ytm_pct: 4.062, price: 101.532, shock_bps: -25 },
  { ytm_pct: 4.312, price: 99.5, shock_bps: 0 },
  { ytm_pct: 4.562, price: 97.517, shock_bps: 25 },
  { ytm_pct: 4.812, price: 95.581, shock_bps: 50 },
  { ytm_pct: 5.312, price: 91.855, shock_bps: 100 },
];

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        rows: METRIC_ROWS,
        curve: CURVE,
        summary: SUMMARY,
        methodology: "Closed-form yield analytics.",
      },
      sources: ["yield_spread_model"],
      elapsed_ms: 3,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
  (downloadGridCsv as ReturnType<typeof vi.fn>).mockClear();
});
afterEach(() => {
  cleanup();
});

describe("YAS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<YASPane code="YAS" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<YASPane code="YAS" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when no curve comes back", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", curve: [] } } });
    render(<YASPane code="YAS" />);
    expect(screen.getByText(/No analytics returned/i)).toBeInTheDocument();
  });
});

describe("YAS pane — headline cards", () => {
  it("renders YTM, spread, durations and convexity", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<YASPane code="YAS" />);
    // YTM appears on the card and in the 0bp ladder row.
    expect(screen.getAllByText("4.312%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("-13.8 bps")).toBeInTheDocument();
    expect(screen.getByText("8.09y")).toBeInTheDocument();
    expect(screen.getByText("78.6")).toBeInTheDocument();
  });

  it("renders the ±100bp shock ladder with price deltas", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<YASPane code="YAS" />);
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(7);
    const first = rows[0].textContent ?? "";
    expect(first).toContain("-100");
    expect(first).toContain("3.312%");
    expect(first).toContain("107.915");
    // 107.915 − 99.5 current price.
    expect(first).toContain("+8.415");
    // The 0bp row has zero delta.
    const flat = rows[3].textContent ?? "";
    expect(flat).toContain("+0.000");
  });
});

describe("YAS pane — model inputs", () => {
  it("sends default inputs (price 99.5, coupon 4.25% → 0.0425, 10y, bench 4.45%)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<YASPane code="YAS" />);
    expect(lastParams).toMatchObject({
      price: 99.5,
      coupon: 0.0425,
      maturity_years: 10,
      freq: 2,
      benchmark_rate: 0.0445,
    });
    expect(lastSymbol).toBe("US10Y");
  });

  it("drives params from the price input and persists it", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<YASPane code="YAS" />);
    fireEvent.change(screen.getByLabelText("Price (per 100 face)"), {
      target: { value: "101.25" },
    });
    expect(lastParams?.price).toBe(101.25);
    expect(localStorage.getItem("showme.yas.price")).toBe("101.25");
  });

  it("converts coupon percent to a decimal and persists it", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<YASPane code="YAS" />);
    fireEvent.change(screen.getByLabelText("Coupon percent"), {
      target: { value: "5.5" },
    });
    expect(lastParams?.coupon).toBe(0.055);
    expect(localStorage.getItem("showme.yas.coupon")).toBe("5.5");
  });

  it("drives the benchmark input and persists it", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<YASPane code="YAS" />);
    fireEvent.change(screen.getByLabelText("Benchmark percent"), {
      target: { value: "4" },
    });
    expect(lastParams?.benchmark_rate).toBe(0.04);
    expect(localStorage.getItem("showme.yas.benchmark")).toBe("4");
  });

  it("switches coupon frequency via the segmented control", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<YASPane code="YAS" />);
    fireEvent.click(screen.getByText("4x"));
    expect(lastParams?.freq).toBe(4);
    expect(localStorage.getItem("showme.yas.freq")).toBe("4");
  });

  it("lets the bond symbol input drive the instrument", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<YASPane code="YAS" />);
    fireEvent.change(screen.getByLabelText("Bond symbol"), {
      target: { value: "UST5Y" },
    });
    expect(lastSymbol).toBe("UST5Y");
  });
});

describe("YAS pane — grid CSV export", () => {
  it("exports the raw shock ladder via the CSV button", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<YASPane code="YAS" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^yas-US10Y-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(csv).toContain("Shock bp,YTM %,Price,Δ vs now");
    // RAW numbers + Δ computed against the summary price (107.915 − 99.5).
    expect(csv).toContain("-100,3.312,107.915,8.415");
    expect(csv).toContain("0,4.312,99.5,0");
  });

  it("disables the CSV button when no ladder is returned", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", curve: [] } } });
    render(<YASPane code="YAS" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
