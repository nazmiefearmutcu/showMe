/**
 * ANR pane — ANR#1 no fabricated as-of date for an undated consensus.
 *
 * yfinance recommendations_summary carries only period labels (0m, -1m, ...),
 * so the consensus has no provider date. The header must not stamp an AS OF
 * pill for it; it may show the newest dated broker action under its own label.
 *
 * `useFunction` is mocked via mutable shared state so each test drives the pane
 * into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ANRPane } from "./index";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetch = vi.fn();

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
    refetch,
  }),
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

// The Veryfinder transport never resolves in tests; render assertions only.
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

function okPayload(summary: Record<string, unknown>) {
  return {
    data: {
      data: {
        status: "ok",
        symbol: "AMZN",
        summary: {
          label: "Buy",
          consensus_score: 3.8,
          analyst_count: 31,
          positive_pct: 58.1,
          neutral_pct: 25.8,
          negative_pct: 16.1,
          included_count: 31,
          excluded_stale_count: 0,
          target_price_source: "Live analyst targets",
          consensus_source: "yfinance_recommendations",
          ...summary,
        },
        analyst_rows: [],
        bucket_rows: [],
        target_rows: [],
        target_price_source: { mode: "derived", label: "Derived from spot", not_analyst_target: true },
        stale_rule: { rule_type: "stale_rating", cutoff_date: "2025-06-09", included_count: 31 },
        source_details: [],
        spot: 185.4,
      },
      sources: ["yfinance_recommendations"],
      elapsed_ms: 14,
    },
  };
}

beforeEach(() => {
  refetch.mockClear();
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
});

describe("ANR pane — ANR#1 no fabricated as-of date for undated consensus", () => {
  it("shows the newest dated broker action instead of an AS OF pill when the consensus is undated", () => {
    setMockFn({
      state: "ok",
      ...okPayload({
        last_updated: null,
        consensus_period: "0m",
        latest_rating_action_date: "2026-11-04",
      }),
    });
    render(<ANRPane code="ANR" symbol="AMZN" />);
    expect(screen.getByText("LAST BROKER ACTION 2026-11-04")).toBeInTheDocument();
    expect(screen.queryByText(/^AS OF/)).toBeNull();
  });

  it("shows no as-of pill at all when neither a consensus date nor a broker action date exists", () => {
    setMockFn({
      state: "ok",
      ...okPayload({
        last_updated: null,
        consensus_period: "0m",
        latest_rating_action_date: null,
      }),
    });
    render(<ANRPane code="ANR" symbol="AMZN" />);
    expect(screen.queryByText(/^AS OF/)).toBeNull();
    expect(screen.queryByText(/^LAST BROKER ACTION/)).toBeNull();
  });
});
