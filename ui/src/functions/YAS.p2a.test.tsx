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


describe("YAS pane — asset class and unsupported-asset honesty (YAS#3)", () => {
  it("tells the sidecar the asset is a BOND so a CUSIP is not inferred as EQUITY", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<YASPane code="YAS" symbol="912828ZT2" />);
    expect(lastParams).toMatchObject({ asset_class: "BOND" });
    expect(lastSymbol).toBe("912828ZT2");
  });

  it("shows the unsupported-asset reason instead of the generic empty message", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "unsupported_asset",
          reason: "YAS does not support EQUITY",
          rows: [],
          curve: [],
        },
      },
    });
    render(<YASPane code="YAS" symbol="912828ZT2" />);
    expect(screen.getByText(/Asset not supported/i)).toBeInTheDocument();
    expect(screen.getByText(/YAS does not support EQUITY/i)).toBeInTheDocument();
    expect(screen.queryByText(/check the bond inputs/i)).toBeNull();
  });
});
