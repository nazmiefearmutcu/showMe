/**
 * ACCT — specialized Account Overview pane tests.
 *
 * Pins the four render states (loading / error / empty / success) plus the
 * honesty badge surviving an empty payload, using the repo's standard
 * mutable-holder useFunction mock.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const mockArgs: {
  current: { code?: string; params?: Record<string, unknown> } | null;
} = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    mockArgs.current = args as (typeof mockArgs)["current"];
    return mockReturn.current;
  },
}));
// G3 — CONN jump spies (hoisted so the module mocks can close over them).
const { setFocusedTargetSpy, navigateSpy } = vi.hoisted(() => ({
  setFocusedTargetSpy: vi.fn(),
  navigateSpy: vi.fn(),
}));
vi.mock("@/lib/router", () => ({ navigate: navigateSpy }));
vi.mock("@/lib/workspace", () => ({
  useWorkspace: (
    selector: (s: { setFocusedTarget: typeof setFocusedTargetSpy }) => unknown,
  ) => selector({ setFocusedTarget: setFocusedTargetSpy }),
}));

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
  mockArgs.current = null;
  setFocusedTargetSpy.mockReset();
  navigateSpy.mockReset();
  vi.useRealTimers();
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

  it("auto-refreshes on the visibility tick WITHOUT a params change", () => {
    vi.useFakeTimers();
    const refetch = vi.fn();
    mockReturn.current = {
      state: "ok",
      data: {
        code: "ACCT",
        instrument: null,
        data: LIVE_COMPOSITE,
        metadata: { live: true },
        fetched_at: "2026-09-11T00:00:00Z",
        sources: ["yfinance"],
        warnings: [],
        elapsed_ms: 42,
      },
      error: undefined,
      refetch,
    };
    render(<AccountOverviewPane code="ACCT" />);
    // Initial mount is useFunction's own load — the tick must not double-fetch.
    expect(refetch).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(refetch).toHaveBeenCalledTimes(1);
    // The tick drives refetch() only: the fetch key stays { code } — a tick in
    // params would wipe the table to a skeleton every cycle.
    expect(mockArgs.current?.code).toBe("ACCT");
    expect(mockArgs.current?.params).toBeUndefined();
  });
});

describe("ACCT G3 — CONN jump + honest cash/margin gating", () => {
  it("jumps from an account row to CONN (focus + route)", () => {
    ok(LIVE_COMPOSITE);
    render(<AccountOverviewPane code="ACCT" />);
    fireEvent.click(screen.getByTestId("acct-open-main"));
    expect(setFocusedTargetSpy).toHaveBeenCalledWith("CONN");
    expect(navigateSpy).toHaveBeenCalledWith("/fn/CONN");
  });

  it("hides cash/margin and shows the 'not in payload' note for the shipped acct.py payload", () => {
    ok(LIVE_COMPOSITE);
    render(<AccountOverviewPane code="ACCT" />);
    // acct.py emits no cash/margin — honest note, no fabricated columns.
    expect(screen.getByTestId("acct-cash-margin-note")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "ACCT account roll-up" });
    expect(within(table).queryByText("Cash")).toBeNull();
    expect(within(table).queryByText("Margin")).toBeNull();
  });

  it("renders cash/margin columns when a payload actually carries them", () => {
    ok({
      ...LIVE_COMPOSITE,
      rows: [{ ...LIVE_COMPOSITE.rows[0], cash: 25000, margin: 12000 }],
    });
    render(<AccountOverviewPane code="ACCT" />);
    expect(screen.queryByTestId("acct-cash-margin-note")).toBeNull();
    const table = screen.getByRole("table", { name: "ACCT account roll-up" });
    expect(within(table).getByText("Cash")).toBeInTheDocument();
    expect(within(table).getByText("Margin")).toBeInTheDocument();
    expect(within(table).getByText("$25,000")).toBeInTheDocument();
    expect(within(table).getByText("$12,000")).toBeInTheDocument();
  });
});
