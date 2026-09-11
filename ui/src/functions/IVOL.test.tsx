/**
 * IVOL pane — live/reference honesty + poll-pattern tests (A7 fixes).
 *
 * Pins three shipped defects closed on 2026-09-11:
 *  - the live yfinance surface (`source_mode="live_yfinance"`) must show the
 *    green "live" pill with NO "no live options provider" banner (it used to
 *    be amber "reference" because the backend emitted no source_mode);
 *  - the KPI ribbon reads real `summary.atm_iv_front/skew/term_slope` values
 *    (it used to be permanently "—");
 *  - the visibility tick is a refetch trigger, never a fetch param (a
 *    tick-keyed fetch wiped the pane to the skeleton every 60s poll).
 *
 * `useFunction` is mocked with an opts recorder (WCRS pattern) so the params
 * contract is pinned without the sidecar transport.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number; warnings?: string[] };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const recordedCalls: Array<{ params?: Record<string, unknown>; symbol?: string }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown>; symbol?: string }) => {
    recordedCalls.push(opts);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

import { IVOLPane } from "./IVOL";

function livePayload() {
  return {
    data: {
      status: "ok",
      symbol: "AAPL",
      spot: 190,
      source_mode: "live_yfinance",
      surface: [
        { expiry: "2026-06-19", dte: 30, strike: 180, moneyness: 0.95, iv: 0.35, option_type: "CALL" },
        { expiry: "2026-06-19", dte: 30, strike: 190, moneyness: 1.0, iv: 0.31, option_type: "CALL" },
        { expiry: "2026-06-19", dte: 30, strike: 200, moneyness: 1.05, iv: 0.34, option_type: "PUT" },
      ],
      rows: [{ expiry: "2026-06-19", dte: 30, atm_iv: 0.31 }],
      series: [
        { t: "2026-06-19", v: 0.31 },
        { t: "2026-07-17", v: 0.33 },
      ],
      summary: {
        contracts: 3,
        expiries: 2,
        calls: 2,
        puts: 1,
        source_mode: "live_yfinance",
        atm_iv_front: 0.31,
        atm_iv_back: 0.33,
        skew: 0.04,
        term_slope: 0.02,
      },
      methodology: "Live implied volatility surface from option-chain impliedVolatility.",
    },
    sources: ["yfinance"],
    elapsed_ms: 12,
  };
}

function referencePayload() {
  return {
    data: {
      status: "reference",
      symbol: "AAPL",
      spot: 190,
      series: [{ t: "30d", v: 0.32 }],
      summary: { contracts: 0, expiries: 0, source_mode: "reference" },
    },
    sources: ["black_scholes_reference_formula"],
    elapsed_ms: 3,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  recordedCalls.length = 0;
});

afterEach(() => {
  cleanup();
});

describe("IVOL pane — poll pattern", () => {
  it("polls without putting the visibility tick into the fetch params", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(recordedCalls.length).toBeGreaterThan(0);
    for (const call of recordedCalls) {
      expect(call.params ?? {}).not.toHaveProperty("tick");
      expect(call.params).toEqual({ underlying: "AAPL" });
    }
  });
});

describe("IVOL pane — live vs reference honesty", () => {
  it("shows the live pill and NO reference banner for a live_yfinance surface", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(screen.getByText("live")).toBeInTheDocument();
    expect(screen.queryByText("reference")).toBeNull();
    expect(screen.queryByText(/labelled reference surface/i)).toBeNull();
  });

  it("renders real KPI values from the live summary (never a permanent em-dash)", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    const kpi = screen.getByLabelText("IVOL KPI ribbon");
    expect(within(kpi).getByText("ATM IV (front)")).toBeInTheDocument();
    expect(within(kpi).getByText("31.00%")).toBeInTheDocument();
    expect(within(kpi).getByText("4.00%")).toBeInTheDocument();
    expect(within(kpi).getByText("+2.00%")).toBeInTheDocument();
  });

  it("labels a reference payload with the amber pill and the notice", () => {
    mockFn.state = "ok";
    mockFn.data = referencePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(screen.queryByText("live")).toBeNull();
    expect(screen.queryByText(/labelled reference surface/i)).not.toBeNull();
    expect(screen.getAllByText("reference").length).toBeGreaterThanOrEqual(1);
  });
});
