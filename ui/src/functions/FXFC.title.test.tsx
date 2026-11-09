/**
 * FXFC#2: the pane title names the output as a CIP forward, not a forecast.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FXFCPane } from "./FXFC";

const mockFn = {
  state: "ok" as const,
  data: {
    warnings: [] as string[],
    sources: ["yfinance"],
    elapsed_ms: 1,
    data: {
      pair: "USDJPY",
      spot: 154.324,
      forecast: [
        {
          pair: "USDJPY",
          horizon: "3M",
          tenor_years: 0.25,
          spot: 154.324,
          forecast: 153.1,
          lower_band: null,
          upper_band: null,
          forward_points: -1.2,
          vol_annualized: null,
          source_mode: "live_yfinance_quote",
        },
      ],
    },
  },
};

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

afterEach(() => {
  cleanup();
});

describe("FXFC pane title", () => {
  it("titles the pane as a CIP forward, not an FX forecast", () => {
    render(<FXFCPane code="FXFC" symbol="USDJPY" />);
    expect(screen.getByText("CIP Forward — USDJPY")).toBeInTheDocument();
    expect(screen.queryByText(/FX Forecasts/)).toBeNull();
  });
});
