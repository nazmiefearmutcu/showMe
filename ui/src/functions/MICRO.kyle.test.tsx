/**
 * MICRO — Kyle's lambda and depth-bucket rendering.
 *
 * The backend estimates Kyle's lambda as the OLS slope of 1-interval log
 * returns on signed dollar taker flow, reported in bps per $1M of net flow,
 * and emits cumulative depth buckets (depth_table). The pane must show both,
 * and must show an honest empty value when the fit is unavailable.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

const mockFn = {
  state: "ok" as "idle" | "loading" | "ok" | "error" | "refreshing",
  data: undefined as unknown,
  refetch: vi.fn(),
};

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: null,
    refetch: mockFn.refetch,
  }),
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

import { MICROPane } from "./MICRO";

function payload(extra: Record<string, unknown>) {
  return {
    data: {
      status: "ok",
      data_mode: "live_exchange",
      as_of: "2026-09-11T00:00:00+00:00",
      symbol: "BTCUSDT",
      asset_class: "CRYPTO",
      best_bid: 60000,
      best_ask: 60001,
      mid: 60000.5,
      spread: 1,
      spread_bps: 0.17,
      microprice: 60000.6,
      imbalance: 0.12,
      top10_imbalance: 0.1,
      bids: [{ price: 60000, size: 2 }],
      asks: [{ price: 60001, size: 1 }],
      rows: [
        { side: "bid", price: 60000, size: 2, cum_size: 2, notional: 120000 },
        { side: "ask", price: 60001, size: 1, cum_size: 1, notional: 60001 },
      ],
      ...extra,
    },
    sources: ["binance"],
    warnings: [],
  };
}

beforeEach(() => {
  mockFn.state = "ok";
  mockFn.refetch = vi.fn();
});

afterEach(() => {
  cleanup();
});

describe("MICRO pane — Kyle lambda", () => {
  it("shows Kyle lambda in bps per $1M of net flow with its fit statistics", () => {
    mockFn.data = payload({
      kyle_lambda_proxy: 8.2e-11,
      kyle_lambda_bps_per_1m_usd: 0.82,
      kyle_lambda_r2: 0.31,
      kyle_lambda_points: 199,
    });
    render(<MICROPane code="MICRO" symbol="BTCUSDT" />);
    expect(screen.getByText("Kyle λ")).toBeInTheDocument();
    expect(screen.getByText("0.82 bps")).toBeInTheDocument();
    expect(screen.getByText(/per \$1M net flow/)).toBeInTheDocument();
    expect(screen.getByText(/R² 0\.31/)).toBeInTheDocument();
  });

  it("shows an honest empty Kyle value when the flow fit is unavailable", () => {
    mockFn.data = payload({
      kyle_lambda_proxy: null,
      kyle_lambda_bps_per_1m_usd: null,
      kyle_lambda_r2: null,
      kyle_lambda_points: 0,
    });
    render(<MICROPane code="MICRO" symbol="BTCUSDT" />);
    expect(screen.getByText("Kyle λ")).toBeInTheDocument();
    expect(screen.getByText("insufficient flow data")).toBeInTheDocument();
    expect(screen.queryByText(/0\.82 bps/)).toBeNull();
  });
});

describe("MICRO pane — depth buckets", () => {
  it("renders the cumulative depth buckets with signed imbalance", () => {
    mockFn.data = payload({
      depth_table: [
        { bucket: "Top 5", levels: 5, bid_qty: 10, ask_qty: 8, imbalance: 0.111 },
        { bucket: "Top 10", levels: 10, bid_qty: 20, ask_qty: 25, imbalance: -0.111 },
      ],
    });
    render(<MICROPane code="MICRO" symbol="BTCUSDT" />);
    const table = screen.getByRole("table", { name: "Depth buckets" });
    expect(within(table).getByText("Top 5")).toBeInTheDocument();
    expect(within(table).getByText("Top 10")).toBeInTheDocument();
    expect(within(table).getByText("+11.1%")).toBeInTheDocument();
    expect(within(table).getByText("-11.1%")).toBeInTheDocument();
  });
});
