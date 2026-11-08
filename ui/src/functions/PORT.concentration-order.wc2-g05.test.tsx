/**
 * WC2-G05 / UI-9 residual: the Concentration rail must never rank a position
 * with no reported weight as if its weight were 0%. A missing weight sorts
 * after every reported weight, including negative (short) ones, and an
 * unpriced row never shows a real 0.00% weight.
 */
import { render } from "@testing-library/react";
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

describe("PORT concentration order (WC2-G05 UI-9 residual)", () => {
  it("ranks a missing weight after a short (negative) weight, never as 0%", () => {
    mockFunction({
      status: "ready",
      data: {
        positions: [
          { symbol: "SHRT", asset_class: "EQUITY", quantity: -3, avg_cost: 100,
            last: 100, market_value: -300, unrealized_pnl: 0, weight: -1.0 },
          { symbol: "NONE", asset_class: "EQUITY", quantity: 2, avg_cost: 50,
            last: null, market_value: null, unrealized_pnl: null, weight: null },
          { symbol: "LONG", asset_class: "EQUITY", quantity: 5, avg_cost: 10,
            last: 120, market_value: 600, unrealized_pnl: 500, weight: 2.0 },
        ],
        totals: { market_value: 300, cost_basis: 100, unrealized_pnl: 500,
                  n_positions: 3, cash: 0 },
        by_asset_class: { EQUITY: 300 },
      },
      sources: ["portfolio_state"],
    });

    const { container } = render(<PORTPane code="PORT" />);

    const rows = Array.from(container.querySelectorAll(".port-concentration-row"));
    const order = rows.map((el) => el.querySelector("span")?.textContent);
    expect(order).toEqual(["LONG", "SHRT", "NONE"]);
    const noneRow = rows.find((el) => el.querySelector("span")?.textContent === "NONE");
    expect(noneRow?.textContent).not.toMatch(/0\.00%/);
  });
});
