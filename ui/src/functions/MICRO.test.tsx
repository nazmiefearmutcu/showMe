/**
 * MICRO — order-book microstructure pane tests.
 *
 * Pins the canonical refresh pattern (UA-HIGH-16): `tick` is kept OUT of the
 * `params` object and drives `refetch()` from an effect, so the 5s poll never
 * wipes the ladder to a skeleton. Also pins the honesty branch (non-crypto →
 * explicit_unavailable, never a fabricated ladder).
 *
 * `useFunction` is mocked via mutable shared state, following the FORM4
 * pattern, so each spec drives a branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MICROPane } from "./MICRO";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; warnings?: string[] } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  if (next.refetch) mockFn.refetch = next.refetch;
}

const mockTick = { current: 0 };
let lastFnArgs: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: mockFn.refetch,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        data_mode: "live_exchange",
        as_of: "2026-09-11T00:00:00+00:00",
        symbol: "BTCUSDT",
        asset_class: "CRYPTO",
        best_bid: 60000,
        best_ask: 60001,
        mid: 60000.5,
        spread: 1,
        spread_bps: 0.17,
        microprice: 60000.6,
        imbalance: 0.12,
        top10_imbalance: 0.1,
        kyle_lambda_proxy: 0.5,
        bids: [
          { price: 60000, size: 2 },
          { price: 59999, size: 3 },
        ],
        asks: [
          { price: 60001, size: 1 },
          { price: 60002, size: 4 },
        ],
        rows: [
          { side: "bid", price: 60000, size: 2, cum_size: 2, notional: 120000 },
          { side: "ask", price: 60001, size: 1, cum_size: 1, notional: 60001 },
        ],
      },
      sources: ["binance_depth"],
      warnings: [],
    },
  };
}

beforeEach(() => {
  mockTick.current = 0;
  lastFnArgs = undefined;
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("MICRO pane — render contract", () => {
  it("renders the live ladder + mid KPI for a crypto payload", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<MICROPane code="MICRO" symbol="BTCUSDT" />);
    expect(screen.getByLabelText("Order-book depth ladder")).toBeInTheDocument();
    expect(screen.getByText("Mid")).toBeInTheDocument();
    // 60,000.50 formatted with adaptive decimals (KPI card + ladder seam).
    expect(screen.getAllByText("60,000.50").length).toBeGreaterThanOrEqual(1);
  });

  it("renders an honest unavailable empty state for non-crypto symbols", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          data_mode: "explicit_unavailable",
          symbol: "AAPL",
          asset_class: "EQUITY",
          reason: "no configured L2 depth provider",
          bids: [],
          asks: [],
          rows: [],
        },
      },
    });
    render(<MICROPane code="MICRO" symbol="AAPL" />);
    expect(screen.getByText(/Order book unavailable/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Order-book depth ladder")).toBeNull();
  });
});

describe("MICRO pane — visibility poll (live adoption)", () => {
  it("refetches on a visibility tick but not on mount", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...livePayload(), refetch });
    const { rerender } = render(<MICROPane code="MICRO" symbol="BTCUSDT" />);
    expect(refetch).not.toHaveBeenCalled();

    mockTick.current = 1;
    rerender(<MICROPane code="MICRO" symbol="BTCUSDT" />);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("keeps the depth params stable across ticks (no tick key → no skeleton flash)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { rerender } = render(<MICROPane code="MICRO" symbol="BTCUSDT" />);
    const before = JSON.stringify(lastFnArgs?.params ?? null);
    expect(before).toContain("depth_levels");
    expect(before).not.toContain("tick");

    mockTick.current = 7;
    rerender(<MICROPane code="MICRO" symbol="BTCUSDT" />);
    expect(JSON.stringify(lastFnArgs?.params ?? null)).toBe(before);
  });
});
