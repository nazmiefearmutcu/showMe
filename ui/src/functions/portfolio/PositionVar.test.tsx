/**
 * PVAR — specialized Position VaR pane tests.
 *
 * Pins the four render states plus the two risk controls wired to real
 * backend params (method / confidence) and the MODEL disclosure path.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({ useFunction: () => mockReturn.current }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PositionVarPane } from "./PositionVar";

function ok(
  payload: Record<string, unknown>,
  envelope: { sources?: string[]; warnings?: string[]; metadata?: Record<string, unknown> } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "PVAR",
      instrument: null,
      data: payload,
      metadata: envelope.metadata ?? { live_risk: true },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: envelope.sources ?? ["yfinance"],
      warnings: envelope.warnings ?? [],
      elapsed_ms: 150,
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
  method: "parametric",
  horizon: "1d",
  confidence_level: 0.95,
  var: 1850,
  expected_shortfall: 2400,
  var_pct: 0.018,
  expected_shortfall_pct: 0.024,
  parametric_var_dollar: 1850,
  historical_var_dollar: 1720,
  portfolio_total_notional: 100000,
  portfolio_annualized_vol: 0.22,
  positions_analyzed: 2,
  samples: 252,
  rows: [
    {
      symbol: "AAPL",
      weight_pct: 62,
      annualized_vol: 0.24,
      component_pct_of_portfolio_risk: 65,
      component_var: 1202,
      marginal_var: 0.018,
      notional_usd: 62000,
    },
    {
      symbol: "BTCUSDT",
      weight_pct: 38,
      annualized_vol: 0.55,
      component_pct_of_portfolio_risk: 35,
      component_var: 647,
      marginal_var: 0.021,
      notional_usd: 38000,
    },
  ],
  series: [
    { pnl: -3000, density: 2 },
    { pnl: -1500, density: 6 },
    { pnl: 0, density: 9 },
    { pnl: 1500, density: 4 },
  ],
  methodology: "Parametric + historical VaR.",
};

describe("PVAR Position VaR pane", () => {
  it("renders a loading skeleton", () => {
    mockReturn.current = { state: "loading", data: undefined, error: undefined, refetch: vi.fn() };
    const { container } = render(<PositionVarPane code="PVAR" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    mockReturn.current = { state: "error", data: undefined, error: new Error("var boom"), refetch };
    render(<PositionVarPane code="PVAR" />);
    expect(screen.getByText(/var boom/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the no-positions empty state", () => {
    ok({ status: "empty", reason: "empty portfolio", rows: [], series: [] });
    render(<PositionVarPane code="PVAR" />);
    expect(screen.getByText("No portfolio positions")).toBeInTheDocument();
  });

  it("renders the VaR hero, component table and histogram", () => {
    ok(LIVE_PAYLOAD);
    const { container } = render(<PositionVarPane code="PVAR" />);
    // VaR shows in the hero and the parametric VaR tile.
    expect(screen.getAllByText("$1,850").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BTCUSDT").length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: /Loss distribution histogram/i })).toBeInTheDocument();
    expect(container.querySelectorAll("table").length).toBe(1);
    expect(screen.queryByTestId("portx-data-badge")).toBeNull();
  });

  it("discloses the modelled template path via the badge + warning strip", () => {
    ok(
      { ...LIVE_PAYLOAD, status: "modeled", data_mode: "modeled" },
      {
        sources: ["portfolio_state", "risk_model"],
        warnings: ["live_risk=false: returns are simulated, not market data."],
      },
    );
    render(<PositionVarPane code="PVAR" />);
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
    expect(screen.getByTestId("portx-warning-strip")).toBeInTheDocument();
  });

  it("switches the confidence control", () => {
    ok(LIVE_PAYLOAD);
    render(<PositionVarPane code="PVAR" />);
    const ninetyNine = screen.getByRole("button", { name: "99%" });
    expect(ninetyNine).not.toBeDisabled();
    fireEvent.click(ninetyNine);
    expect(screen.getByRole("button", { name: "99%" })).toBeDisabled();
  });
});
