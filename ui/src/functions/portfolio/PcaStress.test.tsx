/**
 * PCAS — specialized PCA Stress pane tests.
 *
 * Pins the four render states, the PC/k-σ controls mapped to real backend
 * params, and the MODEL disclosure path for template returns.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const recordedCalls: Array<{ params?: Record<string, unknown> }> = [];
vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    recordedCalls.push(opts);
    return mockReturn.current;
  },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PcaStressPane, deriveCumulativeVariance } from "./PcaStress";

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
  recordedCalls.length = 0;
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

describe("PCAS cumulative variance curve (real derivation)", () => {
  it("builds a monotone cumulative curve from the real ratios", () => {
    const points = deriveCumulativeVariance([0.52, 0.18, 0.09, 0.05, 0.03]);
    expect(points.map((entry) => entry.pc)).toEqual([1, 2, 3, 4, 5]);
    expect(points[0].cumulative).toBeCloseTo(0.52, 10);
    expect(points[4].cumulative).toBeCloseTo(0.87, 10);
    for (let i = 1; i < points.length; i += 1) {
      expect(points[i].cumulative).toBeGreaterThanOrEqual(points[i - 1].cumulative);
    }
  });

  it("skips non-finite entries and stays empty when nothing is usable", () => {
    const points = deriveCumulativeVariance([0.5, Number.NaN, "x", Infinity, 0.25]);
    expect(points.map((entry) => entry.cumulative)).toEqual([0.5, 0.75]);
    expect(deriveCumulativeVariance(undefined)).toEqual([]);
    expect(deriveCumulativeVariance([])).toEqual([]);
  });

  it("renders the cumulative curve and the exact readout", () => {
    ok(LIVE_PAYLOAD);
    render(<PcaStressPane code="PCAS" />);
    expect(
      screen.getByRole("img", { name: /Cumulative explained variance across 5 components/ }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("pcas-cumulative").textContent).toContain("87.00%");
    expect(screen.getByTestId("pcas-cumulative").textContent).toContain("5 component(s)");
  });

  it("renders a readout without a curve when only one component is returned", () => {
    ok({ ...LIVE_PAYLOAD, explained_variance_ratio: [0.52], asset_returns: [] });
    render(<PcaStressPane code="PCAS" />);
    expect(screen.queryByRole("img", { name: /Cumulative explained variance/ })).toBeNull();
    expect(screen.getByTestId("pcas-cumulative").textContent).toContain("52.00%");
    expect(screen.getByTestId("pcas-cumulative").textContent).toContain("1 component(s)");
  });

  it("discloses a truncated spectrum against the real asset count", () => {
    ok({
      ...LIVE_PAYLOAD,
      explained_variance_ratio: [0.6, 0.3],
      asset_returns: [
        { symbol: "AAPL" },
        { symbol: "MSFT" },
        { symbol: "GLD" },
        { symbol: "BTCUSDT" },
      ],
    });
    render(<PcaStressPane code="PCAS" />);
    expect(screen.getByTestId("pcas-cumulative").textContent).toContain(
      "first 2 of up to 4 components returned",
    );
  });

  it("omits live_prices on the MODEL path so the backend serves template returns", () => {
    ok(LIVE_PAYLOAD);
    render(<PcaStressPane code="PCAS" />);
    fireEvent.click(screen.getByRole("button", { name: "LIVE" }));
    const latest = recordedCalls[recordedCalls.length - 1].params ?? {};
    expect("live_prices" in latest).toBe(false);
    expect(latest.live).toBe(true);
    expect(screen.getByRole("button", { name: "MODEL" })).toBeInTheDocument();
  });

  it("keeps live_prices=true on the LIVE path", () => {
    ok(LIVE_PAYLOAD);
    render(<PcaStressPane code="PCAS" />);
    expect(recordedCalls.some((call) => call.params?.live_prices === true)).toBe(true);
  });
});
