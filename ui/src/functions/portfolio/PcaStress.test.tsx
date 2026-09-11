/**
 * PCAS — specialized PCA Stress pane tests.
 *
 * Pins the four render states, the PC/k-σ controls mapped to real backend
 * params, and the MODEL disclosure path for template returns.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({ useFunction: () => mockReturn.current }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PcaStressPane } from "./PcaStress";

function ok(
  payload: Record<string, unknown>,
  envelope: { sources?: string[]; warnings?: string[] } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "PCAS",
      instrument: null,
      data: payload,
      metadata: { live: true },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: envelope.sources ?? ["yfinance"],
      warnings: envelope.warnings ?? [],
      elapsed_ms: 210,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

const LIVE_PAYLOAD = {
  status: "ok",
  pc_index: 0,
  k_sigma: 3,
  explained_variance_ratio: [0.52, 0.18, 0.09, 0.05, 0.03],
  factor_shock_magnitude: 0.041,
  portfolio_return_pct: -7.3,
  portfolio_pnl_dollar: -7300,
  total_notional: 100000,
  samples: 504,
  top_loadings: [
    { symbol: "AAPL", loading: 0.62, pc_index: 0 },
    { symbol: "BTCUSDT", loading: -0.35, pc_index: 0 },
  ],
  asset_returns: [
    { symbol: "AAPL", weight_pct: 62, shock_return_pct: -8.1, pnl: -5022 },
    { symbol: "BTCUSDT", weight_pct: 38, shock_return_pct: -6.0, pnl: -2280 },
  ],
  methodology: "PCA shock projection.",
};

describe("PCAS PCA Stress pane", () => {
  it("renders a loading skeleton", () => {
    mockReturn.current = { state: "loading", data: undefined, error: undefined, refetch: vi.fn() };
    const { container } = render(<PcaStressPane code="PCAS" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    mockReturn.current = { state: "error", data: undefined, error: new Error("pcas boom"), refetch };
    render(<PcaStressPane code="PCAS" />);
    expect(screen.getByText(/pcas boom/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the no-positions empty state", () => {
    ok({ status: "ready_no_positions", rows: [], top_loadings: [], explained_variance_ratio: [] });
    render(<PcaStressPane code="PCAS" />);
    expect(screen.getByText("No portfolio positions")).toBeInTheDocument();
  });

  it("renders the shock P&L hero, variance profile and shock table", () => {
    ok(LIVE_PAYLOAD);
    const { container } = render(<PcaStressPane code="PCAS" />);
    expect(screen.getByText("-$7,300")).toBeInTheDocument();
    expect(screen.getByText("52.00%")).toBeInTheDocument();
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    // Shock table + loading table.
    expect(container.querySelectorAll("table").length).toBe(2);
    expect(screen.queryByTestId("portx-data-badge")).toBeNull();
  });

  it("discloses template returns via the shared badge", () => {
    ok(LIVE_PAYLOAD, { sources: ["portfolio_state_template_returns"] });
    render(<PcaStressPane code="PCAS" />);
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
  });

  it("switches the principal component control", () => {
    ok(LIVE_PAYLOAD);
    render(<PcaStressPane code="PCAS" />);
    const pc2 = screen.getByRole("button", { name: "PC2" });
    expect(pc2).not.toBeDisabled();
    fireEvent.click(pc2);
    expect(screen.getByRole("button", { name: "PC2" })).toBeDisabled();
  });
});
