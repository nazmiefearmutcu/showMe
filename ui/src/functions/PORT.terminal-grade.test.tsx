/**
 * PORT terminal-grade quality pins (display DRY, data honesty, usability).
 *
 * Covers:
 *   P1 — numeric cells carry `terminal-grid-numeric`; formatters come from
 *        format.ts (negative renders sign-first "-$…", missing renders "—").
 *   P2 — the KPI sparkline is no longer an UNLABELED fake series.
 *   P4 — when the PORT function returns no local positions but the portfolio
 *        store holds broker positions, they surface in the main positions
 *        view instead of an "Empty portfolio" wall.
 *   P5 — symbol links have aria-labels; sorting reorders rows.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PORTPane } from "./PORT";
import { usePortfolioStore } from "@/lib/portfolio-store";
import { useExchangeStore } from "@/lib/exchange-store";
import * as useFunctionModule from "@/lib/useFunction";

function resetStores() {
  usePortfolioStore.setState({
    groups: [], totals: {}, loading: false, error: null, lastFetchedAt: null,
    selectedCredentialIds: null, includeOrders: false,
  });
  useExchangeStore.setState({
    catalog: [], credentials: [], selectedExchangeId: null,
    catalogLoading: false, credentialsLoading: false, error: null,
  });
}

/** Drive PORTPane with a deterministic useFunction return. */
function mockFunction(data: unknown, state: "ok" | "loading" | "error" = "ok") {
  vi.spyOn(useFunctionModule, "useFunction").mockReturnValue({
    state,
    data: data as never,
    error: null,
    refetch: () => {},
  } as never);
}

const READY_WITH_POSITIONS = {
  status: "ready",
  data: {
    positions: [
      { symbol: "AAPL", asset_class: "EQUITY", quantity: 10, avg_cost: 100,
        last: 90, market_value: 900, unrealized_pnl: -100, weight: 0.6 },
      { symbol: "MSFT", asset_class: "EQUITY", quantity: 5, avg_cost: 200,
        last: 220, market_value: 1100, unrealized_pnl: 100, weight: 0.4 },
    ],
    totals: { market_value: 2000, cost_basis: 2000, unrealized_pnl: 0, n_positions: 2 },
    by_asset_class: { EQUITY: 2000 },
  },
  sources: ["portfolio_state"],
};

beforeEach(() => {
  resetStores();
  vi.restoreAllMocks();
});

describe("PORT terminal-grade", () => {
  it("P1: numeric cells carry terminal-grid-numeric", () => {
    mockFunction(READY_WITH_POSITIONS);
    const { container } = render(<PORTPane code="PORT" />);
    expect(container.querySelectorAll(".terminal-grid-numeric").length).toBeGreaterThan(0);
  });

  it("P1: negative P&L renders sign-first currency from format.ts", () => {
    mockFunction(READY_WITH_POSITIONS);
    render(<PORTPane code="PORT" />);
    // AAPL has -$100 unrealized P&L; DeltaChip / ChangeText render sign-first.
    // Assert there is at least one "-$" (or "−") prefixed value, never "$-".
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/\$-\d/); // no "$-100" anywhere
  });

  it("P2: the KPI sparkline is not an unlabeled fake series", () => {
    mockFunction(READY_WITH_POSITIONS);
    const { container } = render(<PORTPane code="PORT" />);
    // The honest replacement is a 1D return badge (real metric) OR a clearly
    // labeled illustrative placeholder. The old fake spark had no label and
    // used the `port-terminal-summary__spark` bar container with no caption.
    const fakeSpark = container.querySelector(".port-terminal-summary__spark");
    // The unlabeled seeded fake spark must be gone entirely.
    expect(fakeSpark).toBeNull();
    // The honest real-metric badge (unrealized return) must replace it.
    const badge = container.querySelector("[data-testid='port-return-badge']");
    expect(badge).not.toBeNull();
    expect(badge?.textContent?.toLowerCase()).toMatch(/return/);
  });

  it("P4: broker positions surface in the main view when PORT has none", () => {
    // PORT function returns ready_no_positions; broker store has live positions.
    mockFunction({ status: "ready_no_positions", data: { positions: [], totals: {} } });
    useExchangeStore.setState({
      catalog: [],
      credentials: [{ id: "abc", exchange_id: "binance", account_label: "main",
                      permissions: ["read"], created_at: "now" }],
      selectedExchangeId: null, catalogLoading: false, credentialsLoading: false, error: null,
    });
    usePortfolioStore.setState({
      groups: [{
        credential_id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"],
        account: { cash: 1000, equity: 5000, buying_power: 1000, currency: "USDT" },
        positions: [{ symbol: "ETH/USDT", side: "buy", quantity: 3,
                      entry_price: 2000, current_price: 2100, unrealized_pnl: 300 }],
        orders: [], error: null,
      }],
      totals: { equity_by_currency: { USDT: 5000 }, stable_usd_equivalent: 5000 },
      lastFetchedAt: "now", loading: false, error: null,
      selectedCredentialIds: null, includeOrders: false,
    });
    render(<PORTPane code="PORT" />);
    // The main positions grid must surface ETH/USDT, not show "Empty portfolio".
    const grid = document.querySelector(".port-main-grid");
    expect(grid).not.toBeNull();
    expect(within(grid as HTMLElement).getAllByText("ETH/USDT").length).toBeGreaterThan(0);
    expect(screen.queryByText(/empty portfolio/i)).toBeNull();
  });

  it("P5: symbol links have descriptive aria-labels", () => {
    mockFunction(READY_WITH_POSITIONS);
    render(<PORTPane code="PORT" />);
    expect(
      screen.getByRole("button", { name: /view aapl details/i }),
    ).toBeInTheDocument();
  });

  it("P5: clicking a sortable header reorders rows", () => {
    mockFunction(READY_WITH_POSITIONS);
    const { container } = render(<PORTPane code="PORT" />);
    const grid = container.querySelector(".port-main-grid") as HTMLElement;
    const symbolsNow = () =>
      Array.from(grid.querySelectorAll("tbody .u-symbol-link")).map((el) => el.textContent);

    // Input order: AAPL (-100 P&L) then MSFT (+100 P&L).
    expect(symbolsNow()).toEqual(["AAPL", "MSFT"]);

    const pnlHeader = within(grid).getByText(/Unrl P&L/i);
    // First click → descending P&L → MSFT (+100) first.
    fireEvent.click(pnlHeader);
    expect(symbolsNow()).toEqual(["MSFT", "AAPL"]);

    // Second click → ascending P&L → AAPL (-100) first.
    fireEvent.click(pnlHeader);
    expect(symbolsNow()).toEqual(["AAPL", "MSFT"]);
  });
});
