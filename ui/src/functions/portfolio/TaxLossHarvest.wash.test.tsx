/**
 * TLH — wash-sale check status and savings basis labels (TLH#2, TLH#3, TLH#5).
 *
 * A window is an observation, not a clearance: rows the backend could not
 * check must read NOT CHECKED, blocked rows BLOCKED, and the savings total
 * must say whether it is netted or a gross upper bound.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { TaxLossHarvestPane } from "./TaxLossHarvest";

function ok(payload: Record<string, unknown>) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "TLH",
      instrument: null,
      data: payload,
      metadata: { live: true },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: ["portfolio_state", "yfinance"],
      warnings: [],
      elapsed_ms: 120,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

const WINDOW = ["2020-01-01", "2099-12-31"];

const BASE_ROW = {
  asset_class: "EQUITY",
  quantity: 10,
  avg_cost: 200,
  current_price: 180,
  unrealized_pnl: -200,
  held_days: 400,
  long_term: true,
  tax_rate_applied: 0.15,
  estimated_tax_savings: 30,
  sector: "Technology",
  replacement_etf: "VGT",
  wash_sale_window: WINDOW,
  wash_sale_checked: false,
};

describe("TLH wash-sale check status", () => {
  it("labels a row the backend could not check as NOT CHECKED", () => {
    ok({
      status: "ok",
      wash_sale_checked: false,
      wash_sale_rule_respected: null,
      candidates: [
        {
          ...BASE_ROW,
          symbol: "AAPL",
          wash_sale_safe: null,
          wash_sale_status: "not_checked",
          wash_sale_reason: "Broker buy history is not checked.",
        },
      ],
      rows: [],
      total_estimated_tax_savings: 30,
      n_loss_positions: 1,
      savings_basis: "gross_upper_bound_no_gains_supplied",
    });
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByText("NOT CHECKED")).toBeInTheDocument();
    expect(screen.queryByText("BLOCKED")).toBeNull();
    expect(
      screen.getByText(/Wash-sale check not run against broker buy history/),
    ).toBeInTheDocument();
  });

  it("labels a row blocked by an in-window open date as BLOCKED", () => {
    ok({
      status: "ok",
      wash_sale_checked: false,
      candidates: [
        {
          ...BASE_ROW,
          symbol: "MSFT",
          held_days: 10,
          long_term: false,
          wash_sale_safe: false,
          wash_sale_status: "blocked_open_date_in_window",
          wash_sale_reason: "Position was opened inside the window.",
        },
      ],
      rows: [],
      total_estimated_tax_savings: 0,
      n_loss_positions: 1,
      savings_basis: "gross_upper_bound_no_gains_supplied",
    });
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByText("BLOCKED")).toBeInTheDocument();
    expect(screen.queryByText("NOT CHECKED")).toBeNull();
  });

  it("renders no wash-check pill when the row carries no status (no guessed label)", () => {
    ok({
      status: "ok",
      candidates: [{ ...BASE_ROW, symbol: "XOM" }],
      rows: [],
      total_estimated_tax_savings: 30,
      n_loss_positions: 1,
    });
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.queryByText("NOT CHECKED")).toBeNull();
    expect(screen.queryByText("BLOCKED")).toBeNull();
  });
});

describe("TLH savings basis label", () => {
  it("says the total is a gross upper bound when no gains were supplied", () => {
    ok({
      status: "ok",
      candidates: [{ ...BASE_ROW, symbol: "AAPL", wash_sale_status: "not_checked" }],
      rows: [],
      total_estimated_tax_savings: 30,
      n_loss_positions: 1,
      savings_basis: "gross_upper_bound_no_gains_supplied",
    });
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByText("Estimated tax savings (gross, not netted)")).toBeInTheDocument();
  });

  it("says the total is netted when realized gains were supplied", () => {
    ok({
      status: "ok",
      candidates: [{ ...BASE_ROW, symbol: "AAPL", wash_sale_status: "not_checked" }],
      rows: [],
      total_estimated_tax_savings: 20,
      n_loss_positions: 1,
      savings_basis: "netted_against_supplied_realized_gains",
    });
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByText("Estimated tax savings (netted)")).toBeInTheDocument();
  });
});
