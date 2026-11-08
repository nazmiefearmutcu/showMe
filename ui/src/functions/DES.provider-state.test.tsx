/**
 * DES provider-state footer (wc1-g46, DES#2): when no provider answered, the
 * footer must not say "pending" (a request still in flight) and the sources
 * row must be empty, not a list of providers that never responded.
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

function unavailablePayload() {
  return {
    state: "ok",
    data: {
      status: "provider_unavailable",
      data: {
        status: "provider_unavailable",
        symbol: "AAPL",
        name: "Apple Inc.",
        reason: "Reference data providers returned no usable company description within the latency budget.",
        next_actions: ["Retry DES after the reference data providers recover."],
      },
      sources: [],
      elapsed_ms: 12,
    },
    error: null,
    refetch: vi.fn(),
  };
}

beforeEach(() => {
  useFunctionMock.mockReturnValue(unavailablePayload());
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DES provider-state footer", () => {
  it("does not label an exhausted provider chain as pending", () => {
    render(<DESPane code="DES" symbol="AAPL" />);
    expect(screen.queryByText("pending")).toBeNull();
    expect(screen.getAllByText("unavailable").length).toBeGreaterThanOrEqual(1);
  });
});
