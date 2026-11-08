/**
 * DCFS pane — negative-value honesty (wb1-g20, DCFS#1).
 *
 * A negative base fair value is not a live valuation. The pane must not show
 * the live pill for it, even when an older payload still says status "ok", and
 * it must explain the negative value instead of claiming "Needs provider input".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DCFSPane } from "./DCFS";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[] } | undefined;
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

vi.mock("@/lib/market-data", () => ({
  useLiveQuote: () => ({ price: 12.5, transportState: "ok", stale: false, loading: false }),
}));

function negativePayload(status: string) {
  return {
    data: {
      status,
      base_fair_value: -23.218,
      wacc_range: [0.09],
      g_range: [0.02],
      grid: [
        {
          wacc: 0.09,
          g_terminal: 0.02,
          fair_value_per_share: -28.29,
          bucket: "WACC 9.0% / g 2.0%",
        },
      ],
      tornado: [],
    },
    warnings: ["free_cash_flow: provider reported negative free cash flow."],
    sources: ["yfinance"],
    elapsed_ms: 10,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "ok";
  mockFn.error = null;
});
afterEach(() => {
  cleanup();
});

describe("DCFS pane — negative base fair value", () => {
  it("never shows the live pill for a negative base value", () => {
    mockFn.data = negativePayload("ok");
    render(<DCFSPane code="DCFS" symbol="RIVN" />);
    expect(screen.queryByText("live", { exact: true })).toBeNull();
  });

  it("explains the negative value instead of blaming provider input", () => {
    mockFn.data = negativePayload("negative_value");
    render(<DCFSPane code="DCFS" symbol="RIVN" />);
    expect(screen.getByText("Negative fair value")).toBeInTheDocument();
    expect(screen.queryByText("Needs provider input")).toBeNull();
    expect(screen.queryByRole("grid", { name: /fair value heatmap/i })).toBeNull();
  });
});
