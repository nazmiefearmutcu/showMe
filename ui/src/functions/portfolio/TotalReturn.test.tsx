/**
 * TRA — specialized Total Return pane tests.
 *
 * Pins the four render states plus the two controls that map to real backend
 * params: the symbol input and the LIVE/MODEL (`reference`) toggle.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({ useFunction: () => mockReturn.current }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { TotalReturnPane } from "./TotalReturn";

function ok(
  payload: Record<string, unknown>,
  envelope: { sources?: string[]; warnings?: string[] } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "TRA",
      instrument: null,
      data: payload,
      metadata: { live: true },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: envelope.sources ?? ["yfinance"],
      warnings: envelope.warnings ?? [],
      elapsed_ms: 88,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

const LIVE_SERIES = {
  status: "ok",
  price_return_total: 0.5,
  twr_total: 0.5,
  irr_annualized: 0.22,
  cagr: 0.18,
  dividends_count: 4,
  dividends_total: 12.5,
  n_observations: 4,
  first_date: "2022-01-03",
  last_date: "2026-09-10",
  series: [
    { date: "2022-01-03", close: 100, growth_of_1: 1 },
    { date: "2024-01-03", close: 140, growth_of_1: 1.4 },
    { date: "2025-06-02", close: 130, growth_of_1: 1.3 },
    { date: "2026-09-10", close: 150, growth_of_1: 1.5 },
  ],
  methodology: "Compounded daily returns.",
};

describe("TRA Total Return pane", () => {
  it("renders a loading skeleton", () => {
    mockReturn.current = { state: "loading", data: undefined, error: undefined, refetch: vi.fn() };
    const { container } = render(<TotalReturnPane code="TRA" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    mockReturn.current = { state: "error", data: undefined, error: new Error("tra boom"), refetch };
    render(<TotalReturnPane code="TRA" />);
    expect(screen.getByText(/tra boom/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the empty state when no series is returned", () => {
    ok({ status: "ok", series: [] });
    render(<TotalReturnPane code="TRA" />);
    expect(screen.getByText("No data available")).toBeInTheDocument();
  });

  it("renders the growth chart, KPI row and observation tail", () => {
    ok(LIVE_SERIES);
    render(<TotalReturnPane code="TRA" />);
    expect(screen.getByText("1.500×")).toBeInTheDocument();
    expect(screen.getAllByText("+50.00%").length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: /Growth of 1 for AAPL/i })).toBeInTheDocument();
    expect(screen.getAllByText("2026-09-10").length).toBeGreaterThan(0);
    // Live payload → no disclosure badge.
    expect(screen.queryByTestId("portx-data-badge")).toBeNull();
  });

  it("discloses the labelled template fallback via the shared badge", () => {
    ok(LIVE_SERIES, { sources: ["total_return_model"] });
    render(<TotalReturnPane code="TRA" />);
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
  });

  it("toggles the MODEL (reference) control state", () => {
    ok(LIVE_SERIES);
    render(<TotalReturnPane code="TRA" />);
    const liveButton = screen.getByRole("button", { name: "LIVE" });
    fireEvent.click(liveButton);
    expect(screen.getByRole("button", { name: "MODEL" })).toBeInTheDocument();
  });
});
