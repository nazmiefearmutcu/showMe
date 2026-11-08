/**
 * EREV pane — method label and empty coverage.
 *
 * Split out of EREV.test.tsx (base 4ea6d2d) so the original test file is unchanged.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?:
    | {
        data?: unknown;
        status?: string;
        sources?: string[];
        elapsed_ms?: number;
        metadata?: Record<string, unknown>;
      }
    | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { EREVPane } from "./EREV";

function liveData() {
  return {
    status: "ok",
    data: {
      status: "ok",
      symbol: "AAPL",
      trend: [
        {
          period: "2026-03",
          score: 5,
          n: 10,
          avg: 0.5,
          strongBuy: 3,
          buy: 2,
          hold: 5,
          sell: 0,
          strongSell: 0,
        },
      ],
      rows: [],
      revisions: [],
      velocity_avg: 0.1,
      data_mode: "live_official",
    },
    sources: ["finnhub"],
    metadata: { live: true, data_mode: "live_official" },
    elapsed_ms: 5,
  };
}

function unavailableData() {
  return {
    status: "provider_unavailable",
    data: {
      status: "provider_unavailable",
      symbol: "AAPL",
      rows: [],
      trend: [],
      revisions: [],
      velocity_avg: null,
      current_score: null,
      reason: "finnhub provider not wired (no API key configured)",
      warnings: [
        "No Finnhub key wired; analyst recommendation buckets unavailable.",
      ],
      next_actions: [
        "Configure a Finnhub API key so analyst recommendation buckets can load.",
      ],
      data_mode: "not_configured",
    },
    sources: [],
    metadata: { live: false, fallback: true, data_mode: "not_configured" },
    elapsed_ms: 3,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});


describe("EREV pane — method label and empty coverage", () => {
  it("labels the pane as recommendation momentum, not earnings revisions", () => {
    mockFn.state = "ok";
    mockFn.data = liveData();
    render(<EREVPane code="EREV" symbol="AAPL" />);
    expect(
      screen.getByText(/Analyst Recommendation Momentum/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Earnings Revisions/)).toBeNull();
  });

  it("never shows live when no period has analysts (status empty)", () => {
    mockFn.state = "ok";
    mockFn.data = {
      status: "ok",
      data: {
        status: "empty",
        symbol: "AAPL",
        trend: [
          { period: "2026-08", score: 0, n: 0, avg: null, strongBuy: 0, buy: 0, hold: 0, sell: 0, strongSell: 0 },
        ],
        rows: [],
        revisions: [],
        velocity_avg: null,
        current_score: null,
        warnings: ["zero analysts in every period"],
      },
      sources: ["finnhub"],
      metadata: { live: false, data_mode: "empty_coverage" },
      elapsed_ms: 2,
    };
    render(<EREVPane code="EREV" symbol="AAPL" />);
    expect(screen.queryByText("live")).toBeNull();
    expect(screen.queryByText("+0.000")).toBeNull();
  });
});
