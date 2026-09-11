/**
 * FXIP pane — render-contract + data-honesty tests.
 *
 * FXIP mixes a live spot quote with REFERENCE inputs (policy rates, an ATM
 * vol assumption, CIP forwards). When the backend degrades to
 * `reference_model` the pane must say the spot is NOT a live quote. These
 * tests pin:
 *
 *  - the load states (loading / error / ok / empty payload);
 *  - a live payload renders the source_mode pill and KPI cards;
 *  - a reference_model payload renders the explicit "NOT a live quote"
 *    note; a live payload does not;
 *  - the ATM vol card is labelled as an assumption;
 *  - the pair picker switches the bound pair when no symbol is bound.
 *
 * `useFunction` is mocked via mutable shared state (GEX pattern).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { FXIPPane } from "./FXIP";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[] } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetchMock = vi.fn();
const mockTick = { current: 0 };
const recordedCalls: Array<{ params?: Record<string, unknown> }> = [];

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    recordedCalls.push(opts);
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

/* ── fixtures ──────────────────────────────────────────────────────── */

const metricRows = [
  { metric: "spot", value: 1.1628, unit: "USD per EUR", source: "yfinance" },
  { metric: "base_rate", value: 0.035, unit: "decimal annual", source: "reference_policy_rate" },
  { metric: "quote_rate", value: 0.045, unit: "decimal annual", source: "reference_policy_rate" },
  { metric: "1m_forward", value: 1.16378, unit: "rate", source: "covered_interest_parity" },
  {
    metric: "atm_vol_1m_pct",
    value: 8.45,
    unit: "percent",
    source: "reference_vol_assumption",
  },
  {
    metric: "carry_annualized",
    value: 0.01,
    unit: "decimal annual",
    source: "rate_differential",
  },
];

function fxipPayload(sourceMode: string) {
  return {
    data: {
      data: {
        pair: "EURUSD",
        base: "EUR",
        quote: "USD",
        spot: 1.1628,
        daily_change_pct: 0.1198,
        one_month_forward: 1.16378,
        three_month_forward: 1.165721,
        implied_vol_atm_1m: 8.45,
        carry_annualized: 0.01,
        source_mode: sourceMode,
        rows: metricRows,
        history: [
          { date: "2026-05-10", close: 1.1768 },
          { date: "2026-05-11", close: 1.1779 },
        ],
      },
      sources: ["yfinance", "covered_interest_parity_formula"],
      elapsed_ms: 120,
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
  refetchMock.mockReset();
  mockTick.current = 0;
  recordedCalls.length = 0;
});
afterEach(() => {
  cleanup();
});

describe("FXIP pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FXIPPane code="FXIP" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<FXIPPane code="FXIP" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when no metric rows come back", () => {
    setMockFn({
      state: "ok",
      data: { data: { pair: "EURUSD", rows: [], history: [] } },
    });
    render(<FXIPPane code="FXIP" />);
    expect(screen.getByText(/No portal payload/i)).toBeInTheDocument();
  });
});

describe("FXIP pane — live payload", () => {
  it("renders KPI values and the live source_mode pill", () => {
    setMockFn({ state: "ok", ...fxipPayload("live_yfinance_quote") });
    const { container } = render(<FXIPPane code="FXIP" symbol="EURUSD" />);
    expect(container.textContent).toContain("1.1628");
    expect(container.textContent).toContain("1.16378");
    expect(screen.getAllByText(/live_yfinance_quote/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/\+0.120% DAILY/i)).toBeInTheDocument();
  });

  it("does NOT render the reference-spot note for live data", () => {
    setMockFn({ state: "ok", ...fxipPayload("live_yfinance_quote") });
    render(<FXIPPane code="FXIP" symbol="EURUSD" />);
    expect(screen.queryByText(/Reference spot/i)).toBeNull();
  });

  it("labels the ATM vol as an assumption, not a quote", () => {
    setMockFn({ state: "ok", ...fxipPayload("live_yfinance_quote") });
    render(<FXIPPane code="FXIP" symbol="EURUSD" />);
    expect(screen.getByText(/ASSUMPTION — NOT A QUOTE/i)).toBeInTheDocument();
  });
});

describe("FXIP pane — reference honesty", () => {
  it("renders the explicit not-a-live-quote note for reference_model", () => {
    setMockFn({ state: "ok", ...fxipPayload("reference_model") });
    render(<FXIPPane code="FXIP" symbol="EURUSD" />);
    expect(screen.getByText(/NOT a live quote/i)).toBeInTheDocument();
  });
});

describe("FXIP pane — pair picker", () => {
  it("switches the bound pair when no symbol prop is given", () => {
    setMockFn({ state: "ok", ...fxipPayload("live_yfinance_quote") });
    render(<FXIPPane code="FXIP" />);
    fireEvent.click(screen.getByTitle("PAIR USDJPY"));
    expect(screen.getByText(/FX Info Portal — USDJPY/i)).toBeInTheDocument();
  });
});

describe("FXIP pane — visibility poll (live adoption)", () => {
  it("refetches on a visibility tick without feeding it into the params", () => {
    setMockFn({ state: "ok", ...fxipPayload("live_yfinance_quote") });
    const { rerender } = render(<FXIPPane code="FXIP" symbol="EURUSD" />);
    // Mount is useFunction's own initial load — the tick must not double-fetch.
    expect(refetchMock).not.toHaveBeenCalled();
    const snapshot = () =>
      JSON.stringify(recordedCalls[recordedCalls.length - 1]?.params ?? null);

    const before = snapshot();
    mockTick.current = 2;
    rerender(<FXIPPane code="FXIP" symbol="EURUSD" />);
    expect(refetchMock).toHaveBeenCalledTimes(1);
    expect(snapshot()).toBe(before);
    expect(snapshot()).not.toContain("tick");
  });
});

describe("FXIP pane — unit consistency", () => {
  it("renders decimal-annual metric rows as percents, matching the KPI ribbon", () => {
    setMockFn({ state: "ok", ...fxipPayload("live_yfinance_quote") });
    render(<FXIPPane code="FXIP" symbol="EURUSD" />);
    const table = screen.getByRole("table", { name: "FXIP portal metrics" });
    // 0.035 base rate / 0.045 quote rate / 0.01 carry -> percent units.
    expect(within(table).getByText("3.500%")).toBeInTheDocument();
    expect(within(table).getByText("4.500%")).toBeInTheDocument();
    expect(within(table).getByText("+1.000%")).toBeInTheDocument();
  });
});
