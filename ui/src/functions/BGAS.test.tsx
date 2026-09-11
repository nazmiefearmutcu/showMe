/**
 * BGAS pane — render-contract + data-honesty tests (CRVF/GEX pattern).
 *
 * The backend BGAS serves a live NG=F snapshot when yfinance works, a
 * labelled deterministic reference row when live=false, and an honest
 * provider_unavailable envelope when the provider returns nothing. Pins:
 *
 *  - the load states (loading / error / empty / ok) render;
 *  - an ok payload renders the price card, change and history chart;
 *  - a reference_model payload shows the reference-model pill + notice;
 *  - a live payload shows the "live quote" pill and no model notice;
 *  - the history-window segmented control interaction (3m → 6m).
 *
 * `useFunction` is mocked via a mutable shared state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BGASPane } from "./BGAS";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    sources?: string[];
    elapsed_ms?: number;
  };
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

/* ── fixtures: shape mirrors commodity/_funcs.py BGASFunction ──────── */

const SPOT_ROW = {
  symbol: "NG=F",
  name: "Henry Hub Natural Gas",
  unit: "USD/MMBtu",
  exchange: "NYMEX",
  last: 2.975,
  prev: 3.05,
  change: -0.075,
  change_pct: -2.459,
  open: 3.01,
  high: 2.998,
  low: 2.921,
  volume: 34220,
  source: "yfinance",
  source_mode: "live_yfinance",
  as_of: "2026-09-07T22:15:56+00:00",
};

function history(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    date: `2026-0${(i % 9) + 1}-1${i % 9}`,
    close: 2.8 + i * 0.01,
  }));
}

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        symbol: "NG=F",
        source_mode: "live_yfinance",
        rows: [SPOT_ROW],
        history: history(6),
        methodology: "BGAS reads the selected natural-gas futures contract.",
      },
      sources: ["yfinance_futures"],
      elapsed_ms: 12,
    },
  };
}

function modelPayload() {
  const p = livePayload();
  p.data.data.source_mode = "model";
  p.data.data.status = "reference_model";
  p.data.data.history = [];
  p.data.sources = ["commodity_reference_model"];
  return p;
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("BGAS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<BGASPane code="BGAS" symbol="NG=F" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<BGASPane code="BGAS" symbol="NG=F" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest provider-unavailable empty state", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "Natural gas quote provider returned no usable live quote.",
          rows: [],
          history: [],
        },
      },
    });
    render(<BGASPane code="BGAS" symbol="NG=F" />);
    expect(screen.getByText(/No live quote returned/i)).toBeInTheDocument();
    expect(
      screen.getByText(/returned no usable live quote/i),
    ).toBeInTheDocument();
  });
});

describe("BGAS pane — ok payload", () => {
  it("renders the price card, change and day range from the snapshot", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<BGASPane code="BGAS" symbol="NG=F" />);
    // Price card: last 2.975, change −2.46%.
    expect(screen.getByText("2.975")).toBeInTheDocument();
    expect(container.textContent).toContain("-2.459");
    // Day-range card low/high.
    expect(container.textContent).toContain("2.921");
    expect(container.textContent).toContain("2.998");
    // Contract label + unit caption.
    expect(screen.getByText("NG=F")).toBeInTheDocument();
    expect(container.textContent).toContain("USD/MMBtu");
  });

  it("renders the history chart with one point per close", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<BGASPane code="BGAS" symbol="NG=F" />);
    const svg = container.querySelector('svg[role="img"]');
    expect(svg?.getAttribute("aria-label")).toMatch(/6 points/i);
    expect(container.querySelectorAll("polyline").length).toBe(1);
  });

  it("falls back to the cards-only layout when history is empty", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    const { container } = render(<BGASPane code="BGAS" symbol="NG=F" />);
    expect(container.querySelector('svg[role="img"]')).toBeNull();
    expect(screen.getByText("2.975")).toBeInTheDocument();
  });
});

describe("BGAS pane — data honesty", () => {
  it("shows the reference-model pill + notice for model payloads", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<BGASPane code="BGAS" symbol="NG=F" />);
    // Both the header pill and the inline notice label the model data.
    expect(screen.getAllByText(/reference model/i).length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText(/NOT a live market price/i),
    ).toBeInTheDocument();
  });

  it("shows the live-quote pill and no model notice for live payloads", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<BGASPane code="BGAS" symbol="NG=F" />);
    expect(screen.getByText(/live quote/i)).toBeInTheDocument();
    expect(screen.queryByText(/reference model/i)).toBeNull();
    expect(screen.queryByText(/NOT a live market price/i)).toBeNull();
  });
});

describe("BGAS pane — interaction", () => {
  it("switches the history window via the segmented control", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<BGASPane code="BGAS" symbol="NG=F" />);
    const group = screen.getByLabelText("HISTORY");
    const opt1y = group.querySelector('button[title="HISTORY 1y"]');
    const opt3m = group.querySelector('button[title="HISTORY 3m"]');
    // Default window is 1y (365 days) until the user picks another one.
    expect(opt1y?.className).toContain("fn-segmented__opt--active");
    expect(opt3m?.className).not.toContain("fn-segmented__opt--active");
    if (opt3m) fireEvent.click(opt3m);
    expect(opt3m?.className).toContain("fn-segmented__opt--active");
    expect(opt1y?.className).not.toContain("fn-segmented__opt--active");
  });
});

describe("commodity-spot shared body — audit fixes (BGAS)", () => {
  it("stamps the % unit on the change caption (audit A1-M)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<BGASPane code="BGAS" symbol="NG=F" />);
    // "-2.459" alone reads as a price change; the backend value is a percent.
    expect(container.textContent).toContain("-2.459%");
  });

  it("gives a missing change a neutral tone instead of green (audit A3-L)", () => {
    const p = livePayload();
    delete (p.data.data.rows[0] as unknown as Record<string, unknown>).change_pct;
    setMockFn({ state: "ok", ...p });
    render(<BGASPane code="BGAS" symbol="NG=F" />);
    const card = screen.getByText("NG=F").closest(".stat-card");
    expect(card?.className).toContain("stat-card--neutral");
    expect(card?.className).not.toContain("stat-card--positive");
  });

  it("renders EIA value/period rows instead of dropping them (audit A3-H)", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          symbol: "HENRYHUB",
          source_mode: "live_eia",
          rows: [
            {
              symbol: "HENRYHUB",
              name: "Henry Hub Natural Gas",
              unit: "USD/MMBtu",
              value: 3.11,
              period: "2026-09-10",
              change_pct: 0.65,
            },
          ],
          history: [
            { date: "2026-09-08", close: 3.05 },
            { date: "2026-09-09", close: 3.09 },
            { date: "2026-09-10", close: 3.11 },
          ],
        },
        sources: ["eia"],
        elapsed_ms: 6,
      },
    });
    render(<BGASPane code="BGAS" symbol="NG=F" />);
    // The old `last`-only filter dropped every EIA row -> empty grid.
    expect(screen.queryByText(/No spot rows returned/i)).toBeNull();
    expect(screen.getAllByText("3.110").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/live quote/i)).toBeInTheDocument();
    expect(screen.getByText(/AS OF 2026-09-10/)).toBeInTheDocument();
    // The percent caption survived the value/period normalization.
    expect(screen.getByText(/\+0.650%/)).toBeInTheDocument();
  });
});
