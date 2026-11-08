/**
 * OMON pane — freshness label (OMON#2).
 *
 * A stale option chain (newest trade in a past session) must be shown under its
 * real data_mode and never as "live_yfinance". Mocks and fixture are the same
 * as OMON.test.tsx; kept in a separate file so that suite stays untouched.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { OMONPane } from "./OMON";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[]; metadata?: Record<string, unknown> } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

const refetchMock = vi.fn();
const mockTick = { current: 0 };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => {
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchMock,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

/* ── fixtures: 2 expiries, 4 strikes around spot 100 ───────────────── */

function row(strike: number) {
  return {
    strike,
    moneyness: strike / 100,
    call_bid: 3.1,
    call_ask: 3.3,
    call_oi: 1200,
    call_volume: 300,
    call_iv: 0.31,
    call_delta: 0.55,
    put_bid: 2.9,
    put_ask: 3.1,
    put_oi: 900,
    put_volume: 210,
    put_iv: 0.33,
    put_delta: -0.45,
  };
}

/** Real payload shape (probe 2026-09-12): series carries call/put IV per strike. */
function okPayload() {
  return {
    data: {
      data: {
        status: "ok",
        underlier: "AAPL",
        expiry: "2026-07-17",
        expiries: ["2026-07-17", "2026-08-21"],
        spot: 100.25,
        rows: [row(95), row(100), row(105), row(110)],
        series: [
          { strike: 95, call_iv: 0.35, put_iv: null },
          { strike: 100, call_iv: 0.31, put_iv: 0.33 },
          { strike: 105, call_iv: 0.3, put_iv: 0.34 },
          { strike: 110, call_iv: 0.29, put_iv: 0.36 },
        ],
        summary: {
          underlier: "AAPL",
          expiry: "2026-07-17",
          spot: 100.25,
          atm_iv: 0.32,
          total_call_oi: 4200,
          total_put_oi: 3600,
          strike_count: 4,
        },
      },
      warnings: [] as string[],
      metadata: { data_mode: "live_yfinance" },
      sources: ["yfinance"],
      elapsed_ms: 176,
    },
  };
}

describe("OMON pane — freshness label", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows a stale chain under its real mode, never as live_yfinance", () => {
    const payload = okPayload();
    (payload.data as { metadata?: Record<string, unknown> }).metadata = {
      data_mode: "last_trade_yfinance",
      live: false,
    };
    payload.data.warnings = [
      "Not live: newest option trade is 2026-11-06T21:15:00+00:00 UTC (last session or delayed feed).",
    ];
    setMockFn({ state: "ok", ...payload });
    render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(screen.getAllByText("last_trade_yfinance").length).toBeGreaterThan(0);
    expect(screen.queryByText("live_yfinance")).toBeNull();
  });
});
