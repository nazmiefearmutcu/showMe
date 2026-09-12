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

import { PositionVarPane, deriveVarExceptions } from "./PositionVar";

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

const EXCEPTION_SERIES = [
  { pnl: -3000, density: 2 },
  { pnl: -1500, density: 6 },
  { pnl: 0, density: 9 },
  { pnl: 1500, density: 4 },
];

describe("PVAR VaR exception read (real derivation)", () => {
  it("counts a bin fully beyond the line exactly (line on a bin edge)", () => {
    // Bin centers 1500 apart => edges at -3750/-2250/-750/750/2250.
    const read = deriveVarExceptions(EXCEPTION_SERIES, 2250);
    expect(read).not.toBeNull();
    expect(read!.breaches).toBe(2);
    expect(read!.periods).toBe(21);
    expect(read!.straddle).toBe(false);
    expect(read!.breachBins).toEqual([0]);
  });

  it("drops a bin cut by the line and reports a lower bound instead", () => {
    const read = deriveVarExceptions(EXCEPTION_SERIES, 1850);
    expect(read!.breaches).toBe(2);
    expect(read!.straddle).toBe(true);
    expect(read!.breachBins).toEqual([0]);
  });

  it("reports zero breaches when the line sits beyond every realized loss", () => {
    const read = deriveVarExceptions(EXCEPTION_SERIES, 10000);
    expect(read!.breaches).toBe(0);
    expect(read!.straddle).toBe(false);
    expect(read!.periods).toBe(21);
  });

  it("honest-drop when VaR is absent or the histogram is too short", () => {
    expect(deriveVarExceptions(EXCEPTION_SERIES, null)).toBeNull();
    expect(deriveVarExceptions(EXCEPTION_SERIES, Number.NaN)).toBeNull();
    expect(deriveVarExceptions([{ pnl: -3000, density: 2 }], 1850)).toBeNull();
  });

  it("renders the exact breach strip and marks the VaR line in the histogram", () => {
    ok({ ...LIVE_PAYLOAD, var: 2250 });
    render(<PositionVarPane code="PVAR" />);
    const strip = screen.getByTestId("pvar-exceptions");
    expect(strip.textContent).toContain("2 of 21 periods beyond the 95% VaR line");
    expect(strip.textContent).toContain("expected ≈ 1");
    expect(strip.textContent).not.toContain("≥");
    expect(
      screen.getByRole("img", { name: /Loss distribution histogram.*VaR line/ }),
    ).toBeInTheDocument();
  });

  it("flags the boundary bin as a lower bound in the strip", () => {
    ok({ ...LIVE_PAYLOAD, var: 1850 });
    render(<PositionVarPane code="PVAR" />);
    const strip = screen.getByTestId("pvar-exceptions");
    expect(strip.textContent).toContain("≥ 2 of 21 periods beyond the 95% VaR line");
    expect(strip.textContent).toContain("boundary bin spans the line");
  });

  it("omits the exception strip when the backend sends no VaR value", () => {
    ok({ ...LIVE_PAYLOAD, var: null });
    render(<PositionVarPane code="PVAR" />);
    expect(screen.queryByTestId("pvar-exceptions")).toBeNull();
    expect(screen.getByRole("img", { name: /Loss distribution histogram/i })).toBeInTheDocument();
  });
});
