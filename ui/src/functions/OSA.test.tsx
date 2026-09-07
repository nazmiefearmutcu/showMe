/**
 * OSA pane — render-contract + interaction tests.
 *
 * The pane is fully parameter-driven (no market feed): the legs editor and
 * strategy presets build the request, the backend returns solved premiums
 * and a 101-point payoff/PnL curve. Tests pin:
 *
 *  - the four load states (loading / error / bad-payload / ok) render;
 *  - the ok state renders the stats strip, the payoff SVG and the legs table;
 *  - breakeven markers appear in the chart for a spread payload;
 *  - clicking a strategy preset swaps the legs AND persists them;
 *  - editing a leg strike updates the persisted strategy.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) so each
 * test drives the pane into a specific branch without the sidecar.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OSAPane } from "./OSA";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function bullCallPayload() {
  const legs = [
    { qty: 1, strike: 100, type: "CALL", expiry: 0.25, vol: 0.25 },
    { qty: -1, strike: 110, type: "CALL", expiry: 0.25, vol: 0.25 },
  ];
  const netDebit = 3.59;
  const pvDebit = netDebit;
  const curve = [];
  for (let i = 0; i <= 100; i += 1) {
    const s = 50 + i;
    const payoff =
      Math.max(s - 100, 0) * 1 + Math.max(s - 110, 0) * -1;
    curve.push({
      spot: s,
      payoff,
      pnl: payoff - pvDebit,
      net_debit: netDebit,
      pv_debit: pvDebit,
    });
  }
  return {
    data: {
      data: {
        status: "ok",
        strategy: "custom",
        spot: 100,
        rate: 0.045,
        rows: [
          {
            leg: 1,
            qty: 1,
            type: "CALL",
            strike: 100,
            expiry_years: 0.25,
            vol: 0.25,
            iv_source: "input",
            premium: 5.54,
            initial_value: 5.54,
          },
          {
            leg: 2,
            qty: -1,
            type: "CALL",
            strike: 110,
            expiry_years: 0.25,
            vol: 0.25,
            iv_source: "input",
            premium: 1.95,
            initial_value: -1.95,
          },
        ],
        legs,
        curve,
        summary: {
          net_debit: netDebit,
          max_gain_visible: 6.41,
          max_loss_visible: -3.59,
          breakeven_count_visible: 1,
        },
      },
    },
  };
}

/* ── harness ───────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("OSA pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<OSAPane code="OSA" symbol="SPY" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<OSAPane code="OSA" symbol="SPY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders an honest bad-payload state when status is not ok", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "calc_error", curve: [], summary: {} } },
    });
    render(<OSAPane code="OSA" symbol="SPY" />);
    expect(
      screen.getByText(/Strategy could not be priced/i),
    ).toBeInTheDocument();
  });

  it("renders stats, chart and legs when ok", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    const { container } = render(<OSAPane code="OSA" symbol="SPY" />);
    // Stats strip carries the signed net debit + max gain/loss.
    expect(screen.getByText("+3.59")).toBeInTheDocument();
    expect(screen.getByText("+6.41")).toBeInTheDocument();
    expect(screen.getByText("-3.59")).toBeInTheDocument();
    // Payoff chart + breakeven marker (P&L crosses 0 at 103.59).
    const chart = container.querySelector('svg[role="img"]');
    expect(chart?.getAttribute("aria-label")).toMatch(/breakeven/i);
    expect(container.querySelectorAll("circle").length).toBeGreaterThan(0);
    // Legs editor renders both legs with their solved premiums.
    expect(screen.getByLabelText(/Leg 1: buy CALL 100/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Leg 2: sell CALL 110/)).toBeInTheDocument();
    expect(screen.getByText("5.54")).toBeInTheDocument();
  });
});

describe("OSA pane — interactions", () => {
  it("clicking a strategy preset swaps the legs and persists them", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    render(<OSAPane code="OSA" symbol="SPY" />);
    fireEvent.click(screen.getByText("STRADDLE"));
    const stored = JSON.parse(localStorage.getItem("showme.osa.legs") ?? "[]");
    expect(stored).toHaveLength(2);
    expect(stored[0].type).toBe("CALL");
    expect(stored[1].type).toBe("PUT");
    expect(stored[0].strike).toBe(100);
    expect(stored[1].strike).toBe(100);
  });

  it("editing a leg strike persists the strategy", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    render(<OSAPane code="OSA" symbol="SPY" />);
    const strike = screen.getByLabelText("Leg 1 strike");
    fireEvent.change(strike, { target: { value: "105" } });
    const stored = JSON.parse(localStorage.getItem("showme.osa.legs") ?? "[]");
    expect(stored[0].strike).toBe(105);
  });

  it("adding a leg appends and persists up to the cap", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    render(<OSAPane code="OSA" symbol="SPY" />);
    fireEvent.click(screen.getByTitle("Add a leg (max 4)"));
    const stored = JSON.parse(localStorage.getItem("showme.osa.legs") ?? "[]");
    expect(stored).toHaveLength(3);
  });
});
