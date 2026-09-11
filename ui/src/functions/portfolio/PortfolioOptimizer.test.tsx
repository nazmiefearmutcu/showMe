/**
 * PORT_OPT — specialized Portfolio Optimizer pane tests.
 *
 * Pins the four render states, the frontier chart, the weight matrix built
 * from max-Sharpe / min-vol / risk-parity results, and the mode control.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({ useFunction: () => mockReturn.current }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioOptimizerPane } from "./PortfolioOptimizer";

function ok(
  payload: Record<string, unknown>,
  envelope: { sources?: string[]; warnings?: string[] } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "PORT_OPT",
      instrument: null,
      data: payload,
      metadata: { mode: "all" },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: envelope.sources ?? ["yfinance"],
      warnings: envelope.warnings ?? [],
      elapsed_ms: 320,
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
  symbols: ["SPY", "QQQ"],
  samples: 756,
  efficient_frontier: [
    { label: "vol 8%", return: 0.05, vol: 0.08, sharpe: 0.4, weights: {} },
    { label: "vol 12%", return: 0.09, vol: 0.12, sharpe: 0.75, weights: {} },
    { label: "vol 16%", return: 0.12, vol: 0.16, sharpe: 0.6, weights: {} },
  ],
  max_sharpe: { weights: { SPY: 0.6, QQQ: 0.4 }, return: 0.09, vol: 0.12, sharpe: 0.75 },
  min_volatility: { weights: { SPY: 0.85, QQQ: 0.15 }, return: 0.05, vol: 0.08, sharpe: 0.4 },
  risk_parity: { weights: { SPY: 0.5, QQQ: 0.5 }, return: 0.075, vol: 0.1, sharpe: 0.55 },
  summary: { mode: "all", symbols: 2, samples: 756, risk_free: 0.04, allow_short: false },
  methodology: "Mean-variance optimization.",
};

describe("PORT_OPT Portfolio Optimizer pane", () => {
  it("renders a loading skeleton", () => {
    mockReturn.current = { state: "loading", data: undefined, error: undefined, refetch: vi.fn() };
    const { container } = render(<PortfolioOptimizerPane code="PORT_OPT" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    mockReturn.current = { state: "error", data: undefined, error: new Error("opt boom"), refetch };
    render(<PortfolioOptimizerPane code="PORT_OPT" />);
    expect(screen.getByText(/opt boom/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the empty state when no optimizer results are returned", () => {
    ok({ status: "ok" });
    render(<PortfolioOptimizerPane code="PORT_OPT" />);
    expect(screen.getByText("No data available")).toBeInTheDocument();
  });

  it("renders the frontier and the per-symbol weight matrix", () => {
    ok(LIVE_PAYLOAD);
    const { container } = render(<PortfolioOptimizerPane code="PORT_OPT" />);
    expect(screen.getByRole("img", { name: /Efficient frontier/i })).toBeInTheDocument();
    // Best frontier Sharpe (0.75) surfaces in the hero + mode summary.
    expect(screen.getAllByText("0.75").length).toBeGreaterThan(0);
    expect(screen.getByText("Max Sharpe Wt")).toBeInTheDocument();
    expect(screen.getAllByText("SPY").length).toBeGreaterThan(0);
    // Weight matrix + mode summary.
    expect(container.querySelectorAll("table").length).toBe(2);
    // Live payload → no disclosure badge.
    expect(screen.queryByTestId("portx-data-badge")).toBeNull();
  });

  it("discloses template returns via the shared badge", () => {
    ok(LIVE_PAYLOAD, { sources: ["computed_return_model"] });
    render(<PortfolioOptimizerPane code="PORT_OPT" />);
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
  });

  it("switches the MODE control", () => {
    ok(LIVE_PAYLOAD);
    render(<PortfolioOptimizerPane code="PORT_OPT" />);
    const frontier = screen.getByRole("button", { name: "FRONTIER" });
    expect(frontier).not.toBeDisabled();
    fireEvent.click(frontier);
    expect(screen.getByRole("button", { name: "FRONTIER" })).toBeDisabled();
  });
});
