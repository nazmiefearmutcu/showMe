/**
 * EXEC pane — load-state + render-contract tests.
 *
 * Mirrors the GEX mock pattern: `useFunction` is mocked via a mutable
 * shared object so each test drives the pane into a specific branch
 * without the real sidecar transport. Pins:
 *  - loading skeleton, error, and ok branches render;
 *  - a provider_unavailable payload (no live bars) renders the honest
 *    "no execution plan" state instead of fabricated slices;
 *  - slice rows carry the benchmark VWAP / slippage columns;
 *  - bps tints follow backend COST semantics (positive IS = paid more on
 *    BUY; slip tints flip with the side);
 *  - one interaction: switching the SIDE control to SELL activates it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { EXECPane } from "./EXEC";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

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
    refetch: vi.fn(),
  }),
}));

/* ── fixtures (shape mirrors a live /api/fn/EXEC action=plan probe) ── */

const okPayload = {
  status: "ok",
  action: "plan",
  symbol: "AAPL",
  algo: "TWAP",
  interval: "5m",
  rows: [
    {
      slice_idx: 0,
      offset_s: 0,
      ts_ms: 1788548700000,
      qty: 8.33333333,
      cum_qty: 8.33333333,
      bar_close: 321.88,
      interval_vwap: 321.76333618,
      benchmark_px: 321.76333618,
      slip_bps: 3.63,
      is_bps: 59.69,
      pace_pct: 8.33,
    },
    {
      slice_idx: 1,
      offset_s: 300,
      ts_ms: 1788549000000,
      qty: 8.33333333,
      cum_qty: 16.66666667,
      bar_close: 321.5,
      interval_vwap: 321.61,
      benchmark_px: 321.61,
      slip_bps: -3.42,
      is_bps: 11.2,
      pace_pct: 16.67,
    },
  ],
  orders: [
    {
      parent_id: "PLAN-AAPL-TWAP",
      symbol: "AAPL",
      side: "BUY",
      algo: "TWAP",
      target_qty: 100,
      filled_qty: 100,
      avg_fill_px: 321.7,
      arrival_price: 321.5,
      is_bps: 36.88,
      pace_pct: 100,
      status: "planned",
    },
  ],
  cards: {
    open_parents: 1,
    needs_close: 0,
    avg_is_bps: 36.88,
    worst_slippage_bps: -7.98,
    data_mode: "live_exchange",
    as_of: 1788552000000,
  },
};

function okResult() {
  return { data: { data: okPayload } };
}

beforeEach(() => {
  // Controls persist under showme.exec.* — clear so a click in one test
  // cannot leak a persisted side/algo into the next render.
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("EXEC pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<EXECPane code="EXEC" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<EXECPane code="EXEC" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state for provider_unavailable (no fabricated slices)", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "no intraday bars returned for AAPL from yfinance",
          rows: [],
          orders: [],
        },
      },
    });
    render(<EXECPane code="EXEC" symbol="AAPL" />);
    expect(screen.getByText(/No execution plan/i)).toBeInTheDocument();
    expect(
      screen.getByText(/no intraday bars returned for AAPL/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Benchmark VWAP/i)).toBeNull();
  });

  it("renders slice rows + headline cards when ok", () => {
    setMockFn({ state: "ok", ...okResult() });
    const { container } = render(<EXECPane code="EXEC" symbol="AAPL" />);
    // Both slice indices appear in the table.
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    // Headline cards carry backend aggregates: +36.9 avg IS, -8.0 worst slip.
    expect(screen.getByText("+36.9")).toBeInTheDocument();
    expect(screen.getByText("-8.0")).toBeInTheDocument();
    // Parent id lands in the footer.
    expect(container.textContent).toContain("PLAN-AAPL-TWAP");
  });
});

describe("EXEC pane — cost-tone semantics", () => {
  it("tints positive IS bps as a cost on BUY (paying above arrival is bad)", () => {
    setMockFn({ state: "ok", ...okResult() });
    const { container } = render(<EXECPane code="EXEC" symbol="AAPL" />);
    const negative = container.querySelector(".stat-card--negative");
    expect(negative).not.toBeNull();
    expect(negative?.textContent).toContain("+36.9");
    // Negative slip on BUY = filled below the interval VWAP = favourable.
    const positive = container.querySelector(".stat-card--positive");
    expect(positive?.textContent).toContain("-8.0");
  });

  it("flips the slippage tint on SELL (selling below the benchmark is a cost)", () => {
    setMockFn({ state: "ok", ...okResult() });
    const { container } = render(<EXECPane code="EXEC" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: "SELL" }));
    const negative = Array.from(
      container.querySelectorAll(".stat-card--negative"),
    );
    expect(negative.some((el) => el.textContent?.includes("-8.0"))).toBe(true);
  });
});

describe("EXEC pane — interaction", () => {
  it("activates the SELL side control when clicked", () => {
    setMockFn({ state: "ok", ...okResult() });
    render(<EXECPane code="EXEC" symbol="AAPL" />);
    const sell = screen.getByRole("button", { name: "SELL" });
    expect(sell).not.toBeDisabled();
    fireEvent.click(sell);
    expect(sell).toBeDisabled();
    expect(sell.className).toContain("fn-segmented__opt--active");
    const buy = screen.getByRole("button", { name: "BUY" });
    expect(buy).not.toBeDisabled();
  });

  it("activates the VWAP algo control when clicked", () => {
    setMockFn({ state: "ok", ...okResult() });
    render(<EXECPane code="EXEC" symbol="AAPL" />);
    const vwap = screen.getByRole("button", { name: "VWAP" });
    fireEvent.click(vwap);
    expect(vwap).toBeDisabled();
    expect(vwap.className).toContain("fn-segmented__opt--active");
  });
});
