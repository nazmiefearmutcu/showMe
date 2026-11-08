/**
 * DARK#4 — a request with no symbol is an input_required state, not a FINRA
 * outage. The empty state must say so instead of "FINRA ATS data unavailable".
 * The pane must not substitute a default ticker, and a flagged ratio (the
 * withheld over-100% week) must reach the operator on an ok payload.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DARKPane } from "./DARK";

const mockFn: { data?: unknown; state: string } = { state: "ok", data: undefined };
const calls: Array<{ code: string; symbol?: string | null }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { code: string; symbol?: string | null }) => {
    calls.push({ code: args.code, symbol: args.symbol });
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: null,
      refetch: vi.fn(),
    };
  },
}));

afterEach(() => {
  cleanup();
  mockFn.state = "ok";
  mockFn.data = undefined;
  calls.length = 0;
});

describe("DARK input_required empty state", () => {
  it("names the missing symbol rather than blaming FINRA", () => {
    mockFn.state = "ok";
    mockFn.data = {
      warnings: [],
      data: {
        status: "input_required",
        reason: "DARK requires an equity or ETF symbol (instrument or params.symbol).",
        venues: [],
        by_venue: [],
        rows: [],
        by_week: [],
        cards: {},
        summary: {},
        next_actions: ["Provide an equity or ETF ticker in the symbol field or Params JSON."],
      },
    };
    render(<DARKPane code="DARK" symbol="AAPL" />);
    expect(screen.getByText("Symbol needed")).toBeTruthy();
    expect(screen.queryByText("FINRA ATS data unavailable")).toBeNull();
  });
});

describe("DARK symbol handling", () => {
  it("never substitutes a default ticker when no symbol is linked", () => {
    mockFn.state = "ok";
    mockFn.data = undefined;
    render(<DARKPane code="DARK" />);
    const last = calls[calls.length - 1];
    expect(last.code).toBe("DARK");
    expect(last.symbol ?? "").toBe("");
  });
});

describe("DARK warnings on an ok payload", () => {
  it("shows the backend warning when a ratio was withheld", () => {
    mockFn.state = "ok";
    mockFn.data = {
      warnings: [
        "ATS volume exceeds the yfinance weekly total for 1 week(s) (2026-10-26); dark-pool % is withheld for those weeks.",
      ],
      data: {
        status: "ok",
        symbol: "AAPL",
        total_shares_off_exchange: 1000,
        venues: [
          {
            venue: "ALL_ATS",
            ats_share_volume: 1000,
            ats_trade_count: 10,
            share_of_ats_pct: 100,
            dark_pool_pct: null,
            weekStartDate: "2026-10-26",
          },
        ],
        by_venue: [],
        rows: [],
        by_week: [],
        cards: { venue_count: 1, latest_dark_pool_pct: null, data_mode: "delayed_reference" },
        summary: {},
      },
    };
    render(<DARKPane code="DARK" symbol="AAPL" />);
    expect(screen.getByText(/exceeds the yfinance weekly total/)).toBeTruthy();
  });
});
