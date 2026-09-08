/**
 * BOIL pane — render-contract + data-honesty tests (CRVF/GEX pattern).
 *
 * The backend BOIL serves live CL=F + BZ=F front-month snapshots plus the
 * computed Brent−WTI spread. Pins:
 *
 *  - the load states (loading / error / empty / ok) render;
 *  - both contract cards render with their own units;
 *  - the spread card renders the computed Brent − WTI value;
 *  - the history window segmented control interaction.
 *
 * `useFunction` is mocked via a mutable shared state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BOILPane } from "./BOIL";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
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

/* ── fixtures: shape mirrors commodity/_funcs.py BOILFunction ──────── */

function oilRow(symbol: string, name: string, last: number, changePct: number) {
  return {
    symbol,
    name,
    unit: "USD/bbl",
    exchange: symbol === "CL=F" ? "NYMEX" : "ICE",
    last,
    prev: last - 0.4,
    change: 0.4,
    change_pct: changePct,
    open: last - 0.2,
    high: last + 0.6,
    low: last - 0.9,
    volume: 120000,
    source: "yfinance",
    source_mode: "live_yfinance",
    as_of: "2026-09-07T22:20:00+00:00",
  };
}

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        market: "oil",
        source_mode: "live_yfinance",
        rows: [
          oilRow("CL=F", "WTI Crude Oil", 91.48, 0.71),
          oilRow("BZ=F", "Brent Crude Oil", 96.28, 0.5),
        ],
        history: [
          { date: "2026-09-01", close: 90.1 },
          { date: "2026-09-02", close: 90.9 },
          { date: "2026-09-03", close: 91.2 },
          { date: "2026-09-04", close: 91.48 },
        ],
        spread: 4.8,
        methodology: "BOIL reports front-month WTI and Brent futures.",
      },
      sources: ["yfinance_futures"],
      elapsed_ms: 21,
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

describe("BOIL pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<BOILPane code="BOIL" symbol="CL=F" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<BOILPane code="BOIL" symbol="CL=F" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest provider-unavailable empty state", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "WTI/Brent futures quote provider returned no usable live oil rows.",
          rows: [],
          history: [],
        },
      },
    });
    render(<BOILPane code="BOIL" symbol="CL=F" />);
    expect(screen.getByText(/No live quote returned/i)).toBeInTheDocument();
    expect(screen.getByText(/no usable live oil rows/i)).toBeInTheDocument();
  });
});

describe("BOIL pane — ok payload", () => {
  it("renders both contract cards with prices and units", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<BOILPane code="BOIL" symbol="CL=F" />);
    expect(screen.getByText("CL=F")).toBeInTheDocument();
    expect(screen.getByText("BZ=F")).toBeInTheDocument();
    expect(screen.getAllByText("91.480").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("96.280")).toBeInTheDocument();
    expect(container.textContent).toContain("USD/bbl");
    expect(container.textContent).toContain("+0.71");
  });

  it("renders the computed Brent − WTI spread card", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<BOILPane code="BOIL" symbol="CL=F" />);
    expect(screen.getByText("Brent − WTI")).toBeInTheDocument();
    expect(screen.getByText("+4.800")).toBeInTheDocument();
    expect(screen.getByText(/BRENT ABOVE WTI/i)).toBeInTheDocument();
  });

  it("renders the history chart", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<BOILPane code="BOIL" symbol="CL=F" />);
    const svg = container.querySelector('svg[role="img"]');
    expect(svg?.getAttribute("aria-label")).toMatch(/4 points/i);
  });
});

describe("BOIL pane — interaction", () => {
  it("switches the history window via the segmented control", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<BOILPane code="BOIL" symbol="CL=F" />);
    const group = screen.getByLabelText("HISTORY");
    const opt1y = group.querySelector('button[title="HISTORY 1y"]');
    const opt3y = group.querySelector('button[title="HISTORY 3y"]');
    expect(opt1y?.className).toContain("fn-segmented__opt--active");
    if (opt3y) fireEvent.click(opt3y);
    expect(opt3y?.className).toContain("fn-segmented__opt--active");
    expect(opt1y?.className).not.toContain("fn-segmented__opt--active");
  });
});
