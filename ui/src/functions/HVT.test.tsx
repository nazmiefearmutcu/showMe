/**
 * HVT pane — render-contract + data-honesty tests.
 *
 * Realized-vol term structure from live yfinance closes. Tests pin:
 *
 *  - the four load states (loading / error / provider_unavailable / ok);
 *  - the SEEDED reference rows that ship with a provider_unavailable
 *    payload are NOT rendered as if they were measured data;
 *  - the ok state renders KPI cards, the rolling-RV sparkline and the
 *    window table;
 *  - the lookback control persists under `showme.hvt.days`.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { HVTPane } from "./HVT";

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

function okPayload() {
  const history = [];
  for (let i = 0; i < 73; i += 1) {
    history.push({
      date: `2026-06-${String(1 + (i % 28)).padStart(2, "0")}`,
      vol: 0.2 + (i % 7) * 0.005,
      vol_pct: 20 + (i % 7) * 0.5,
      window_days: 30,
    });
  }
  return {
    data: {
      data: {
        status: "ok",
        symbol: "AAPL",
        spot: 319.97,
        lookback_days: 365,
        rows: [
          { metric: "30D realized vol", window_days: 30, realized_vol: 0.296, realized_vol_pct: 29.6, samples: 30, formula: "stdev(daily close returns) * sqrt(252)" },
          { metric: "60D realized vol", window_days: 60, realized_vol: 0.28, realized_vol_pct: 28.0, samples: 60, formula: "stdev(daily close returns) * sqrt(252)" },
          { metric: "90D realized vol", window_days: 90, realized_vol: 0.27, realized_vol_pct: 27.0, samples: 90, formula: "stdev(daily close returns) * sqrt(252)" },
          { metric: "365D realized vol", window_days: 365, realized_vol: 0.25, realized_vol_pct: 25.0, samples: 252, formula: "stdev(daily close returns) * sqrt(252)" },
        ],
        history,
        summary: {
          current_realized_vol: 0.296,
          current_realized_vol_pct: 29.6,
          observations: 269,
          history_window_days: 30,
        },
        methodology: "Annualized realized volatility = stdev(daily close-to-close returns) * sqrt(252).",
      },
    },
  };
}

function unavailablePayload() {
  return {
    data: {
      data: {
        status: "provider_unavailable",
        reason: "yfinance: no daily close history returned",
        symbol: "AAPL",
        spot: 100,
        rows: [
          { metric: "RV30D", window_days: 30, realized_vol: 0.22, realized_vol_pct: 22.0, samples: 0 },
        ],
        history: [],
        summary: {},
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

describe("HVT pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<HVTPane code="HVT" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<HVTPane code="HVT" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("refuses to render seeded rows for a provider_unavailable payload", () => {
    setMockFn({ state: "ok", ...unavailablePayload() });
    render(<HVTPane code="HVT" symbol="AAPL" />);
    expect(
      screen.getByText(/Realized-vol history unavailable/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/no daily close history/i)).toBeInTheDocument();
    // The seeded 22.0% reference value must NOT appear anywhere.
    expect(screen.queryByText("22.0%")).toBeNull();
  });

  it("renders KPI cards, sparkline and window table when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<HVTPane code="HVT" symbol="AAPL" />);
    expect(screen.getByText("319.97")).toBeInTheDocument();
    // Current RV shows in the subtitle, the KPI card and possibly the
    // spark header — assert presence, not count.
    expect(screen.getAllByText("29.6%").length).toBeGreaterThan(0);
    // Rolling RV curve sparkline with an aria-label (the KPI trend
    // sparklines also carry role="img" — scope to the curve section).
    const spark = container.querySelector(
      'section[aria-label="Rolling realized volatility curve"] svg[role="img"]',
    );
    expect(spark?.getAttribute("aria-label")).toMatch(/realized volatility/i);
    // 4 window rows (the long window also labels a KPI card — presence).
    expect(screen.getAllByText("30D realized vol").length).toBeGreaterThan(0);
    expect(screen.getAllByText("365D realized vol").length).toBeGreaterThan(0);
  });
});

describe("HVT pane — window table (DataGrid migration)", () => {
  it("renders the term structure as a keyboard-navigable DataGrid with an ariaLabel", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<HVTPane code="HVT" symbol="AAPL" />);
    const grid = screen.getByRole("grid", { name: /volatility term structure/i });
    expect(grid).toBeInTheDocument();
    expect(
      within(grid).getByRole("columnheader", { name: /realized vol/i }),
    ).toBeInTheDocument();
    expect(
      within(grid).getByRole("columnheader", { name: /samples/i }),
    ).toBeInTheDocument();
  });

  it("offers a CSV export of the visible window rows", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<HVTPane code="HVT" symbol="AAPL" />);
    const csv = screen.getByTitle("Download CSV");
    expect(csv).not.toBeDisabled();
    expect(csv.getAttribute("aria-label")).toMatch(/4 realized-vol windows/i);
  });
});

describe("HVT pane — interactions", () => {
  it("changing the lookback persists it", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<HVTPane code="HVT" symbol="AAPL" />);
    fireEvent.click(screen.getByText("180d"));
    expect(localStorage.getItem("showme.hvt.days")).toBe("180");
  });
});
