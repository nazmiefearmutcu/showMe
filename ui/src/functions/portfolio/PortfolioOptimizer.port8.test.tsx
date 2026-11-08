/**
 * PORT_OPT — metric strip shows every mode (PORT_OPT#8).
 *
 * Kept separate from PortfolioOptimizer.test.tsx so the base suite stays
 * untouched. Three modes x three metrics must all render; the strip used to
 * slice to six tiles, which cut off the Risk Parity group.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioOptimizerPane } from "./PortfolioOptimizer";

function ok(payload: Record<string, unknown>) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "PORT_OPT",
      instrument: null,
      data: payload,
      metadata: { mode: "all" },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: ["yfinance"],
      warnings: [],
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

describe("PORT_OPT metric strip (PORT_OPT#8)", () => {
  it("renders a Sharpe, return and vol tile for every returned mode", () => {
    ok(LIVE_PAYLOAD);
    const { container } = render(<PortfolioOptimizerPane code="PORT_OPT" />);
    // Three modes x three metrics: the Risk Parity group must not be cut off.
    expect(screen.getByText("Risk Parity Sharpe")).toBeInTheDocument();
    expect(screen.getByText("Risk Parity Ret")).toBeInTheDocument();
    expect(screen.getByText("Risk Parity Vol")).toBeInTheDocument();
    expect(container.querySelectorAll(".portfolio-analytics-metric").length).toBe(9);
  });
});
