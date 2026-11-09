/**
 * TAUC model payload - offering sizes are never shown as numbers.
 *
 * The labelled calendar model (reference=true / live_auctions=false) carries
 * no offering sizes (offering_amount null). The pane must render those as
 * "—" and must not total them into "$0", which reads as a real zero.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TAUCPane } from "./TAUC";

const mockFn: { state: string; data: unknown; error: Error | null } = {
  state: "idle",
  data: undefined,
  error: null,
};

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

function modelPayload() {
  return {
    data: {
      data: {
        status: "ok",
        rows: [
          { security_type: "Bill", term: "13-Week", auction_date: "2026-11-11", offering_amount: null },
          { security_type: "Note", term: "2-Year", auction_date: "2026-11-15", offering_amount: null },
        ],
        n: 2,
        by_type: [
          { security_type: "Bill", count: 1, total_offering: null },
          { security_type: "Note", count: 1, total_offering: null },
        ],
        horizon_days: 7,
        summary: { action: "upcoming", horizon_days: 7, auctions: 2, source_mode: "treasury_auction_model", security_filter: "all" },
      },
      sources: ["treasury_auction_model"],
      elapsed_ms: 3,
    },
  };
}

beforeEach(() => {
  mockFn.state = "ok";
  mockFn.data = modelPayload().data;
  mockFn.error = null;
  if (typeof localStorage !== "undefined") localStorage.clear();
});
afterEach(() => {
  cleanup();
});

describe("TAUC pane - model sizes", () => {
  it("shows the total offering as unavailable, not $0", () => {
    render(<TAUCPane code="TAUC" />);
    expect(screen.getByText("SIZES NOT MODELED")).toBeInTheDocument();
    expect(screen.queryByText("$0")).toBeNull();
    expect(screen.queryByText(/\$0\.0B/)).toBeNull();
  });

  it("renders each row offering as a dash, not a zero amount", () => {
    render(<TAUCPane code="TAUC" />);
    expect(screen.queryByText("$0")).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});
