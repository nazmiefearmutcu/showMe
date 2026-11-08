/**
 * ANR pane - wc1-g22 review fixes.
 *
 * ANR#6: with no symbol the pane shows an empty state and never requests AMZN.
 * ANR#2: the trend card renders the backend's per-period rows and window labels.
 *
 * `useFunction` is mocked so each test drives the pane without the sidecar.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ANRPane } from "./index";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetch = vi.fn();
const requested: Array<{ code?: string; symbol?: string; enabled?: boolean; params?: Record<string, unknown> }> = [];

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { code?: string; symbol?: string; enabled?: boolean; params?: Record<string, unknown> }) => {
    requested.push(args);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

vi.mock("@/lib/veryfinder", () => ({
  fetchVeryfinderQuery: vi.fn(() => new Promise(() => {})),
  recommendedVeryfinderSampleForSymbol: () => 50,
  normalizeVeryfinderSample: (value: string | number, fallback = 50) => {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? Math.round(n) : fallback;
  },
}));

vi.mock("@/lib/symbols", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/symbols")>();
  return {
    ...actual,
    listRecentSymbols: () => [],
  };
});

vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function okPayload(extra: Record<string, unknown>) {
  return {
    data: {
      data: {
        status: "ok",
        symbol: "MSFT",
        summary: {
          label: "Buy-leaning",
          consensus_score: 3.8,
          analyst_count: 31,
          positive_pct: 58.1,
          neutral_pct: 25.8,
          negative_pct: 16.1,
          included_count: 31,
          excluded_stale_count: 0,
          target_price_source: "Live analyst targets",
          consensus_source: "yfinance_recommendations",
        },
        analyst_rows: [],
        bucket_rows: [],
        target_rows: [],
        target_price_source: { mode: "live_analyst_targets", label: "Live analyst targets", not_analyst_target: false },
        stale_rule: { rule_type: "stale_rating", cutoff_date: "2025-11-08", included_count: 31 },
        source_details: [],
        spot: 400,
        ...extra,
      },
      sources: ["yfinance_recommendations"],
      elapsed_ms: 12,
    },
  };
}

beforeEach(() => {
  refetch.mockClear();
  requested.length = 0;
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
});

describe("ANR pane - ANR#6 no silent AMZN default", () => {
  it("shows an empty state and does not request a function call when no symbol is given", () => {
    setMockFn({ state: "ok", ...okPayload({}) });
    render(<ANRPane code="ANR" />);
    expect(screen.getByText("No symbol selected")).toBeInTheDocument();
    expect(requested.every((args) => args.symbol === "" || args.symbol === undefined)).toBe(true);
    // Disabled hook means useFunction issues no request at all.
    expect(requested.every((args) => args.enabled === false)).toBe(true);
    expect(requested.some((args) => args.symbol === "AMZN")).toBe(false);
  });
});

describe("ANR pane - ANR#2 trend window control", () => {
  it("sends the chosen trend window as months (default 12)", () => {
    setMockFn({ state: "ok", ...okPayload({}) });
    render(<ANRPane code="ANR" symbol="AAPL" />);
    expect(requested.at(-1)?.params).toEqual({ months: 12 });
    fireEvent.click(screen.getByTitle("24-month recommendation trend"));
    expect(requested.at(-1)?.params).toEqual({ months: 24 });
  });
});

describe("ANR pane - ANR#2 bucket trend card", () => {
  it("renders each provider period with its window and provider-history pills", () => {
    setMockFn({
      state: "ok",
      ...okPayload({
        trend_months: 3,
        trend_oldest_provider_months_back: 3,
        current_score: 4.1,
        trend: [
          { period: "0m", months_back: 0, strongBuy: 10, buy: 12, hold: 8, sell: 1, strongSell: 0, total: 31, score: 3.9, label: "Buy-leaning", in_consensus: true },
          { period: "-3m", months_back: 3, strongBuy: 8, buy: 10, hold: 10, sell: 2, strongSell: 0, total: 30, score: 3.7, label: "Buy-leaning", in_consensus: false },
        ],
      }),
    });
    render(<ANRPane code="ANR" symbol="MSFT" />);
    expect(screen.getByText("Bucket trend")).toBeInTheDocument();
    expect(screen.getByText("3-month window")).toBeInTheDocument();
    expect(screen.getByText("provider history 3 mo back")).toBeInTheDocument();
    expect(screen.getByText("Current month")).toBeInTheDocument();
    expect(screen.getByText("3 mo back")).toBeInTheDocument();
  });

  it("states the empty window honestly instead of showing a blank table", () => {
    setMockFn({ state: "ok", ...okPayload({ trend_months: 12, trend: [] }) });
    render(<ANRPane code="ANR" symbol="MSFT" />);
    expect(screen.getByText("no provider recommendation period inside the window")).toBeInTheDocument();
  });
});
