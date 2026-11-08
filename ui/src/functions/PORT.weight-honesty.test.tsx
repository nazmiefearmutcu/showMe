/**
 * WC2-G05 / UI-9: portfolio weights must show the real value.
 *  - a weight above 100% (leverage or short-heavy book) is labelled with its
 *    real value, not the clamped bar maximum "100.0%";
 *  - a position with no reported weight is never the "Largest" position at 0.00%.
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

describe("PORT weight honesty (UI-9)", () => {
  it("labels a 120% weight with its real value, not the clamped 100.0%", () => {
    mockFunction({
      status: "ready",
      data: {
        positions: [
          { symbol: "LEV", asset_class: "EQUITY", quantity: 10, avg_cost: 100,
            last: 120, market_value: 1200, unrealized_pnl: 200, weight: 1.2 },
          { symbol: "CASH", asset_class: "EQUITY", quantity: 1, avg_cost: 0,
            last: 0, market_value: -200, unrealized_pnl: 0, weight: -0.2 },
        ],
        totals: { market_value: 1000, cost_basis: 1000, unrealized_pnl: 200,
                  n_positions: 2, cash: 0 },
        by_asset_class: { EQUITY: 1000 },
      },
      sources: ["portfolio_state"],
    });

    render(<PORTPane code="PORT" />);

    // Scope to the weight column labels (the asset-class share also reads 100.0%).
    const labels = Array.from(document.querySelectorAll(".port-weight__label")).map(
      (el) => el.textContent,
    );
    expect(labels).toContain("120.0%");
    expect(labels).not.toContain("100.0%");
  });

  it("does not show a missing weight as 0.00% or name it the largest position", () => {
    mockFunction({
      status: "ready",
      data: {
        positions: [
          { symbol: "NOW", asset_class: "EQUITY", quantity: 2, avg_cost: 50,
            last: 55, market_value: 110, unrealized_pnl: 10, weight: null },
        ],
        totals: { market_value: 110, cost_basis: 100, unrealized_pnl: 10,
                  n_positions: 1, cash: 0 },
        by_asset_class: { EQUITY: 110 },
      },
      sources: ["portfolio_state"],
    });

    render(<PORTPane code="PORT" />);

    expect(screen.queryByText("NOW 0.00%")).toBeNull();
  });
});
