/**
 * DES#1: a crypto profile has no trailing 52-week range. The backend now sends
 * fiftyTwoWeekHigh/Low as null instead of the all-time extremes, so the pane
 * must not show a "52w" range for it, and the real all-time values stay.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DESPane } from "./DES";

vi.mock("@/chart/Chart", () => ({
  Chart: () => <div data-testid="chart-engine" />,
}));

vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return {
    ...actual,
    useLiveQuote: () => ({
      transportState: "idle",
      lastTick: null,
      lastTickAt: null,
      snapshot: null,
      freshnessMs: null,
      stale: false,
      refreshing: false,
    }),
    useLiveQuotes: () => ({ snapshots: {}, ticks: {} }),
  };
});

const useFunctionMock = vi.fn();
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => useFunctionMock(),
}));

const BTC = {
  symbol: "BTC",
  name: "Bitcoin",
  longName: "Bitcoin",
  asset_class: "CRYPTO",
  exchange: "CRYPTO",
  currency: "USD",
  regularMarketPrice: 75737,
  currentPrice: 75737,
  market_cap: 1_500_000_000_000,
  fiftyTwoWeekHigh: null,
  fiftyTwoWeekLow: null,
  all_time_high: 126080,
  all_time_high_date: "2025-10-06T00:00:00.000Z",
  all_time_low: 67.81,
  all_time_low_date: "2013-07-05T00:00:00.000Z",
  circulating_supply: 19_700_000,
  max_supply: 21_000_000,
  source: "coingecko",
};

function payload(profile: Record<string, unknown>) {
  return {
    state: "ok",
    data: {
      status: "ok",
      data: { status: "ok", ...profile },
      sources: ["coingecko"],
      elapsed_ms: 12,
    },
    error: null,
    refetch: vi.fn(),
  };
}

beforeEach(() => {
  useFunctionMock.mockReturnValue(payload(BTC));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DES 52-week honesty for crypto", () => {
  it("does not render a 52w range built from all-time extremes", () => {
    render(<DESPane code="DES" symbol="BTC" />);
    expect(screen.queryByText("52w high")).toBeNull();
    expect(screen.queryByText("52w low")).toBeNull();
    expect(screen.queryByText("52w range")).toBeNull();
  });

  it("keeps the true all-time high and low labelled as all-time", () => {
    render(<DESPane code="DES" symbol="BTC" />);
    expect(screen.getAllByText(/All-time high/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/All-time low/i).length).toBeGreaterThanOrEqual(1);
  });
});
