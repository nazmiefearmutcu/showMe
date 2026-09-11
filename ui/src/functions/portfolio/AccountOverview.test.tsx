/**
 * ACCT — specialized Account Overview pane tests.
 *
 * Pins the four render states (loading / error / empty / success) plus the
 * honesty badge surviving an empty payload, using the repo's standard
 * mutable-holder useFunction mock.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({ useFunction: () => mockReturn.current }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { AccountOverviewPane } from "./AccountOverview";

function ok(
  payload: Record<string, unknown>,
  envelope: { sources?: string[]; warnings?: string[]; metadata?: Record<string, unknown> } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "ACCT",
      instrument: null,
      data: payload,
      metadata: envelope.metadata ?? { live: true },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: envelope.sources ?? ["yfinance"],
      warnings: envelope.warnings ?? [],
      elapsed_ms: 42,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

const LIVE_COMPOSITE = {
  status: "ok",
  accounts: [
    {
      account: "main",
      n_positions: 2,
      total_mv: 175000,
      total_unrealized_pnl: 2500,
      by_asset_class: { EQUITY: 150000, CRYPTO: 25000 },
      positions: [
        {
          symbol: "AAPL",
          asset_class: "EQUITY",
          quantity: 500,
          avg_cost: 180,
          last: 200,
          market_value: 100000,
          unrealized_pnl: 10000,
        },
        {
          symbol: "BTCUSDT",
          asset_class: "CRYPTO",
          quantity: 0.5,
          avg_cost: 60000,
          last: 150000,
          market_value: 75000,
          unrealized_pnl: -7500,
        },
      ],
    },
  ],
  rows: [
    { account: "main", positions: 2, market_value: 175000, unrealized_pnl: 2500, top_asset_class: "EQUITY" },
  ],
  cross: {
    total_mv: 175000,
    by_asset_class: { EQUITY: 150000, CRYPTO: 25000 },
    by_symbol: { AAPL: 100000, BTCUSDT: 75000 },
  },
  summary: { accounts: 1, positions: 2, total_market_value: 175000 },
  methodology: "Group positions by account.",
};

describe("ACCT Account Overview pane", () => {
  it("renders a loading skeleton", () => {
    mockReturn.current = { state: "loading", data: undefined, error: undefined, refetch: vi.fn() };
    const { container } = render(<AccountOverviewPane code="ACCT" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    mockReturn.current = { state: "error", data: undefined, error: new Error("sidecar down"), refetch };
    render(<AccountOverviewPane code="ACCT" />);
    expect(screen.getByText(/sidecar down/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the no-positions empty state with broker actions", () => {
    ok({
      status: "ready_no_positions",
      accounts: [],
      rows: [],
      cross: { total_mv: 0, by_asset_class: {}, by_symbol: {} },
      next_actions: ["Add real positions through the portfolio state surface."],
    });
    render(<AccountOverviewPane code="ACCT" />);
    expect(screen.getByText("No portfolio positions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Connect Broker/i })).toBeInTheDocument();
  });

  it("keeps the honesty badge visible in the empty branch", () => {
    ok(
      { status: "ready_no_positions", accounts: [], rows: [], cross: { total_mv: 0 } },
      { sources: ["portfolio_state_template"] },
    );
    render(<AccountOverviewPane code="ACCT" />);
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
  });

  it("renders the exposure view from the live payload", () => {
    ok(LIVE_COMPOSITE);
    const { container } = render(<AccountOverviewPane code="ACCT" />);
    // Total market value shows in the hero + the account row.
    expect(screen.getAllByText("$175,000").length).toBeGreaterThan(0);
    expect(screen.getAllByText("main").length).toBeGreaterThan(0);
    // Position detail grid carries the real symbols.
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BTCUSDT").length).toBeGreaterThan(0);
    // Two tables: account roll-up + position detail.
    expect(container.querySelectorAll("table").length).toBe(2);
    // Live payload → no disclosure badge.
    expect(screen.queryByTestId("portx-data-badge")).toBeNull();
  });
});
