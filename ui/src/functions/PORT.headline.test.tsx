/**
 * PORT#2 headline: the summary number is labelled for what it actually is.
 * Total equity (cash + market value) when the backend reports it; otherwise
 * market value, explicitly labelled as excluding cash.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PORTPane } from "./PORT";
import { usePortfolioStore } from "@/lib/portfolio-store";
import { useExchangeStore } from "@/lib/exchange-store";
import * as useFunctionModule from "@/lib/useFunction";

function mockFunction(data: unknown) {
  vi.spyOn(useFunctionModule, "useFunction").mockReturnValue({
    state: "ok",
    data: data as never,
    error: null,
    refetch: () => {},
  } as never);
}

const POSITIONS = [
  { symbol: "AAPL", asset_class: "EQUITY", quantity: 10, avg_cost: 100,
    last: 90, market_value: 900, unrealized_pnl: -100, weight: 0.45 },
  { symbol: "MSFT", asset_class: "EQUITY", quantity: 5, avg_cost: 200,
    last: 220, market_value: 1100, unrealized_pnl: 100, weight: 0.55 },
];

beforeEach(() => {
  usePortfolioStore.setState({
    groups: [], totals: {}, loading: false, error: null, lastFetchedAt: null,
    selectedCredentialIds: null, includeOrders: false,
  });
  useExchangeStore.setState({
    catalog: [], credentials: [], selectedExchangeId: null,
    catalogLoading: false, credentialsLoading: false, error: null,
  });
  vi.restoreAllMocks();
});

describe("PORT headline (PORT#2)", () => {
  it("labels the headline as total equity when the backend reports it", () => {
    mockFunction({
      status: "ready",
      data: {
        positions: POSITIONS,
        totals: { market_value: 2000, cost_basis: 2000, unrealized_pnl: 0,
                  n_positions: 2, cash: 220, total_equity: 2220 },
        by_asset_class: { EQUITY: 2000 },
      },
      sources: ["portfolio_state"],
    });

    render(<PORTPane code="PORT" />);

    expect(screen.getAllByText("Total equity").length).toBeGreaterThan(0);
    expect(screen.queryByText("Market value (excl. cash)")).toBeNull();
  });

  it("says market value excludes cash when total equity is not reported", () => {
    mockFunction({
      status: "ready",
      data: {
        positions: POSITIONS,
        totals: { market_value: 2000, cost_basis: 2000, unrealized_pnl: 0,
                  n_positions: 2, total_equity: null },
        by_asset_class: { EQUITY: 2000 },
      },
      sources: ["portfolio_state"],
    });

    render(<PORTPane code="PORT" />);

    expect(screen.getAllByText("Market value (excl. cash)").length).toBeGreaterThan(0);
    expect(screen.queryByText("Total equity")).toBeNull();
  });
});
