/**
 * TRA#2 / TRA#3 pane contract: the TWR label follows total_return_basis, and the
 * max-drawdown tile shows the backend's full-series max_drawdown instead of a
 * client-side figure computed from sampled chart points.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({ useFunction: () => mockReturn.current }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { TotalReturnPane } from "./TotalReturn";

function ok(payload: Record<string, unknown>) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "TRA",
      instrument: null,
      data: payload,
      metadata: { live: true },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: ["yfinance"],
      warnings: [],
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

const BASE = {
  status: "ok",
  price_return_total: 0.2,
  twr_total: 0.33,
  irr_annualized: 0.05,
  cagr: 0.06,
  dividends_count: 4,
  dividends_total: 12.5,
  n_observations: 3,
  first_date: "2022-01-03",
  last_date: "2026-09-10",
  series: [
    { date: "2022-01-03", close: 100, growth_of_1: 1 },
    { date: "2026-09-10", close: 120, growth_of_1: 1.2 },
  ],
  methodology: "Total return.",
};

describe("TRA basis labels and max drawdown", () => {
  it("labels TWR as total return when dividends were reinvested", () => {
    ok({ ...BASE, total_return_basis: "dividends_reinvested", max_drawdown: -0.25 });
    render(<TotalReturnPane code="TRA" />);
    expect(screen.getByText("TWR (total return)")).toBeInTheDocument();
    expect(screen.getByText("CAGR (total return)")).toBeInTheDocument();
  });

  it("labels TWR and CAGR as price only when no dividend series was available", () => {
    ok({ ...BASE, total_return_basis: "price_only_dividends_unavailable", dividends_total: null });
    render(<TotalReturnPane code="TRA" />);
    expect(screen.getByText("TWR (price only)")).toBeInTheDocument();
    expect(screen.getByText("CAGR (price only)")).toBeInTheDocument();
    expect(screen.queryByText("TWR (total return)")).toBeNull();
  });

  it("shows the backend max drawdown rather than one computed from sampled points", () => {
    // Sampled points are flat (no drawdown); the backend full-series figure is -25%.
    ok({ ...BASE, total_return_basis: "dividends_reinvested", max_drawdown: -0.25 });
    render(<TotalReturnPane code="TRA" />);
    expect(screen.getByText("-25.00%")).toBeInTheDocument();
  });

  it("shows an honest dash when the backend did not return a max drawdown", () => {
    ok({ ...BASE, total_return_basis: "dividends_reinvested" });
    render(<TotalReturnPane code="TRA" />);
    const tile = screen.getByText("Max drawdown").closest("div");
    expect(tile?.textContent ?? "").toContain("—");
  });
});

describe("TRA growth-of-1 readouts are labelled price only", () => {
  it("labels the hero, chart and observation column as price basis, whatever the TWR basis", () => {
    // TRA#2 residual: series growth_of_1 is compounded from closes only, so beside
    // "TWR (total return)" it must not read as the total-return growth figure.
    ok({ ...BASE, total_return_basis: "dividends_reinvested", max_drawdown: -0.25 });
    render(<TotalReturnPane code="TRA" />);
    expect(screen.getByText("AAPL · growth of 1 (price only)")).toBeInTheDocument();
    expect(screen.getByText("Growth of $1 (price only)")).toBeInTheDocument();
    expect(screen.getByText("Growth of 1 (price)")).toBeInTheDocument();
  });
});
