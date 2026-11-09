/**
 * WHAL#1 — the footer shows the bars actually covered next to the requested
 * lookback, so a thin weekend window is not presented as a full 24h window.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { WHALPane } from "./WHAL";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[] } | undefined;
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

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: mockFn.refetch,
  }),
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

afterEach(() => {
  cleanup();
});

describe("WHAL pane — covered window in the footer (WHAL#1)", () => {
  function equityPayload(window?: Record<string, unknown>) {
    return {
      data: {
        data: {
          status: "ok",
          market: "EQUITY",
          rows: [],
          lookback_hours: 24,
          ...(window ? { window } : {}),
        },
        sources: ["yahoo_chart_public"],
      },
    };
  }

  it("shows the bars actually covered next to the requested lookback", () => {
    setMockFn({
      state: "ok",
      ...equityPayload({ lookback_hours: 24, covered_hours: 16.5 }),
      refetch: vi.fn(),
    });
    render(<WHALPane code="WHAL" symbol="AAPL" />);
    expect(screen.getByText("24h")).toBeInTheDocument();
    expect(screen.getByText("16.5h of bars")).toBeInTheDocument();
  });

  it("omits the covered chip when the backend reports no window", () => {
    setMockFn({ state: "ok", ...equityPayload(), refetch: vi.fn() });
    render(<WHALPane code="WHAL" symbol="AAPL" />);
    expect(screen.queryByText(/of bars/)).toBeNull();
  });
});

describe("WHAL pane — covered unit follows the market (WHAL#2)", () => {
  it("labels the crypto covered window as trades, not bars", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          market: "CRYPTO",
          rows: [],
          lookback_hours: 24,
          window: { lookback_hours: 24, covered_hours: 0.14 },
        },
        sources: ["binance_spot_public"],
      },
      refetch: vi.fn(),
    });
    render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    expect(screen.getByText("0.1h of trades")).toBeInTheDocument();
    expect(screen.queryByText(/of bars/)).toBeNull();
  });
});
