/**
 * FXH pane — render-contract + data-honesty tests.
 *
 * The backend FXH builds a forward-overlay hedge book from a live spot
 * and refuses to fabricate rows when spot is unavailable. These tests
 * pin:
 *
 *  - the load states (loading / error / data_unavailable / ok) render;
 *  - the hedge book renders notional/forward/carry/scenario values;
 *  - the scenario SVG is present with an accessible label;
 *  - the HEDGE / HORIZON / SHOCK knobs change the fetch params and are
 *    persisted under `showme.fxh.*`;
 *  - an explicit FX-pair symbol overrides the stored pair.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) plus a
 * `lastParams` capture.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FXHPane } from "./FXH";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    sources?: string[];
    elapsed_ms?: number;
    warnings?: string[];
  };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

let lastParams: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { code: string; params?: Record<string, unknown> }) => {
    lastParams = args.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

/* ── fixtures: live-probed EURUSD hedge book ───────────────────────── */

const BOOK_ROW = {
  currency: "EUR",
  home_currency: "USD",
  notional_foreign: 1_000_000,
  spot_rate: 1.1624,
  forward_rate: 1.166178,
  home_value_now: 1_162_400,
  hedge_ratio: 0.75,
  hedged_notional_foreign: 750_000,
  unhedged_notional_foreign: 250_000,
  days_to_maturity: 90,
  carry_pnl_home: 2833.586,
  scenario_usd_strengthens_pct: 5.0,
  spot_if_home_strengthens: 1.10428,
  spot_if_home_weakens: 1.22052,
  pnl_if_home_strengthens: -11696.414,
  pnl_if_home_weakens: 17363.586,
};

const CURVE = [
  { shock_pct: -10.0, total_pnl: -26226.41, unhedged_pnl: -116240.0 },
  { shock_pct: -5.0, total_pnl: -11696.41, unhedged_pnl: -58120.0 },
  { shock_pct: 0.0, total_pnl: 2833.59, unhedged_pnl: 0.0 },
  { shock_pct: 5.0, total_pnl: 17363.59, unhedged_pnl: 58120.0 },
  { shock_pct: 10.0, total_pnl: 31893.59, unhedged_pnl: 116240.0 },
];

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        rows: [BOOK_ROW],
        exposures: [BOOK_ROW],
        curve: CURVE,
        total_carry_pnl: 2833.586,
        total_home_value: 1_162_400,
        total_pnl_if_home_strengthens: -11696.414,
        total_pnl_if_home_weakens: 17363.586,
        hedge_ratio: 0.75,
        days_to_maturity: 90,
        source_mode: "live_yfinance_quote",
        methodology: "Forward overlay.",
      },
      sources: ["live_yfinance_quote", "yfinance"],
      elapsed_ms: 240,
      warnings: [],
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("FXH pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FXHPane code="FXH" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<FXHPane code="FXH" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the data_unavailable empty state with the backend reason", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "data_unavailable",
          reason: "No exposure has a usable spot rate",
          rows: [],
        },
      },
    });
    render(<FXHPane code="FXH" />);
    expect(screen.getByText(/Hedge book unavailable/i)).toBeInTheDocument();
    expect(
      screen.getByText(/No exposure has a usable spot rate/i),
    ).toBeInTheDocument();
  });
});

describe("FXH pane — hedge book", () => {
  it("renders the book row with notional, forward and carry", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<FXHPane code="FXH" />);
    const row = container.querySelector("tbody tr");
    expect(row).not.toBeNull();
    const text = row?.textContent ?? "";
    expect(text).toContain("EUR");
    expect(text).toContain("1,000,000.00");
    expect(text).toContain("750,000.00");
    expect(text).toContain("250,000.00");
    expect(text).toContain("+$2.83K");
  });

  it("renders the KPI ribbon with home value and scenario cards", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<FXHPane code="FXH" />);
    expect(screen.getByText("Home value")).toBeInTheDocument();
    expect(screen.getByText("$1.16M")).toBeInTheDocument();
    // "Carry P&L" appears as a KPI card AND as the book column header.
    expect(screen.getAllByText("Carry P&L").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("If home −5%")).toBeInTheDocument();
    expect(screen.getByText("If home +5%")).toBeInTheDocument();
  });

  it("renders the scenario SVG with hedged vs unhedged lines", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<FXHPane code="FXH" />);
    const fig = container.querySelector('figure[role="img"]');
    expect(fig?.getAttribute("aria-label")).toMatch(/scenario curve/i);
    const lines = fig?.querySelectorAll("polyline");
    expect(lines?.length).toBe(2);
    // Zero P&L baseline.
    expect(fig?.querySelector("line")).not.toBeNull();
  });
});

describe("FXH pane — knobs", () => {
  it("sends the default knobs (75% hedge, 90d, ±5% shock)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<FXHPane code="FXH" />);
    expect(lastParams).toMatchObject({
      pair: "EURUSD",
      hedge_ratio: 0.75,
      days: 90,
      usd_shock_pct: 0.05,
    });
  });

  it("persists the hedge ratio knob", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<FXHPane code="FXH" />);
    fireEvent.click(screen.getByText("100%"));
    expect(lastParams?.hedge_ratio).toBe(1);
    expect(localStorage.getItem("showme.fxh.ratio")).toBe("1");
  });

  it("persists the horizon knob", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<FXHPane code="FXH" />);
    fireEvent.click(screen.getByText("180d"));
    expect(lastParams?.days).toBe(180);
    expect(localStorage.getItem("showme.fxh.days")).toBe("180");
  });

  it("persists the shock knob and re-labels the scenario columns", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<FXHPane code="FXH" />);
    fireEvent.click(screen.getByText("±10%"));
    expect(lastParams?.usd_shock_pct).toBe(0.1);
    expect(localStorage.getItem("showme.fxh.shock")).toBe("0.1");
    expect(screen.getByText("If home −10%")).toBeInTheDocument();
    expect(screen.getByText("If home +10%")).toBeInTheDocument();
  });

  it("lets an explicit FX-pair symbol override the stored pair", () => {
    localStorage.setItem("showme.fxh.pair", "EURUSD");
    setMockFn({ state: "ok", ...livePayload() });
    render(<FXHPane code="FXH" symbol="USDJPY" />);
    expect(lastParams?.pair).toBe("USDJPY");
  });
});
