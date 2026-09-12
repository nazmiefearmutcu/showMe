/**
 * HVT pane — render-contract + data-honesty tests (options-family redesign
 * 2026-09-12: rolling-RV sparkline from the REAL history[] + single window
 * DataGrid with built-in sort).
 *
 * Realized-vol term structure from live yfinance closes. Tests pin:
 *
 *  - the load states (loading / error / provider_unavailable / ok);
 *  - the SEEDED reference rows that ship with a `provider_unavailable`
 *    payload are NOT rendered as if they were measured data;
 *  - the ok state renders exactly 4 KPI cards (no mini trend spark), the
 *    rolling-RV sparkline and the window table;
 *  - the window table sorts by window length (default ascending) and has
 *    no constant Formula column;
 *  - the reference template is labeled exactly once (pill + one note);
 *  - the lookback control persists under `showme.hvt.days`.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
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

const FORMULA = "stdev(daily close returns) * sqrt(252)";

function envelope(payload: Record<string, unknown>) {
  return {
    data: {
      data: payload,
      sources: ["yfinance"],
      elapsed_ms: 182,
    },
  };
}

function okPayload() {
  const history = [];
  for (let i = 0; i < 73; i += 1) {
    history.push({
      date: `2026-06-${String(1 + (i % 28)).padStart(2, "0")}`,
      vol: (20 + (i % 7) * 0.5) / 100,
      vol_pct: 20 + (i % 7) * 0.5,
      window_days: 30,
    });
  }
  return envelope({
    status: "ok",
    symbol: "AAPL",
    spot: 319.97,
    lookback_days: 365,
    // Deliberately out of order — the built-in default sort must present
    // the shortest window first.
    rows: [
      { metric: "365D realized vol", window_days: 365, realized_vol: 0.25, realized_vol_pct: 25.0, samples: 252, formula: FORMULA },
      { metric: "90D realized vol", window_days: 90, realized_vol: 0.27, realized_vol_pct: 27.0, samples: 90, formula: FORMULA },
      { metric: "30D realized vol", window_days: 30, realized_vol: 0.296, realized_vol_pct: 29.6, samples: 30, formula: FORMULA },
      { metric: "60D realized vol", window_days: 60, realized_vol: 0.28, realized_vol_pct: 28.0, samples: 60, formula: FORMULA },
    ],
    history,
    summary: {
      current_realized_vol: 0.296,
      current_realized_vol_pct: 29.6,
      observations: 269,
      history_window_days: 30,
    },
    methodology: "Annualized realized volatility = stdev(daily close-to-close returns) * sqrt(252).",
  });
}

function unavailablePayload() {
  return envelope({
    status: "provider_unavailable",
    reason: "yfinance: no daily close history returned",
    symbol: "AAPL",
    spot: 100,
    rows: [
      { metric: "RV30D", window_days: 30, realized_vol: 0.22, realized_vol_pct: 22.0, samples: 0, formula: FORMULA },
    ],
    history: [],
    summary: {},
  });
}

function referencePayload() {
  return envelope({
    status: "reference",
    symbol: "AAPL",
    spot: 100,
    rows: [
      { metric: "RV_30D", window_days: 30, realized_vol: 0.226, realized_vol_pct: 22.6, samples: 0, formula: FORMULA },
      { metric: "RV_60D", window_days: 60, realized_vol: 0.246, realized_vol_pct: 24.6, samples: 0, formula: FORMULA },
      { metric: "RV_90D", window_days: 90, realized_vol: 0.266, realized_vol_pct: 26.6, samples: 0, formula: FORMULA },
      { metric: "RV_252D", window_days: 252, realized_vol: 0.296, realized_vol_pct: 29.6, samples: 0, formula: FORMULA },
    ],
    history: [],
    summary: { source_mode: "reference", windows: 4 },
    methodology: "Reference realized-volatility windows generated from a deterministic per-symbol seed; not live data.",
  });
}

/* ── harness ───────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
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
    const { container } = render(<HVTPane code="HVT" symbol="AAPL" />);
    expect(
      screen.getByText(/Realized-vol history unavailable/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/no daily close history/i)).toBeInTheDocument();
    // The seeded 22.0% reference value and its label must NOT appear anywhere.
    expect(screen.queryByText("22.0%")).toBeNull();
    expect(screen.queryByText("RV30D")).toBeNull();
    expect(container.querySelectorAll(".stat-card").length).toBe(0);
  });

  it("renders 4 KPI cards, the rolling-RV sparkline and the window table when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<HVTPane code="HVT" symbol="AAPL" />);
    expect(screen.getByText(/319\.97/)).toBeInTheDocument();
    expect(screen.getAllByText("29.6%").length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".stat-card").length).toBe(4);
    // The KPI ribbon keeps no sparkline of its own — the curve below is
    // the single rolling-RV visual (removed decoration).
    expect(
      container.querySelectorAll('section[aria-label="HVT KPI ribbon"] svg')
        .length,
    ).toBe(0);
    // History min/max are real measurements with their dates.
    expect(screen.getByText("20.0%")).toBeInTheDocument();
    expect(screen.getByText("23.0%")).toBeInTheDocument();
    expect(screen.getByText("History min")).toBeInTheDocument();
    expect(screen.getByText("History max")).toBeInTheDocument();
    const spark = container.querySelector(
      'section[aria-label="Rolling realized volatility curve"] svg[role="img"]',
    );
    expect(spark?.getAttribute("aria-label")).toMatch(/realized volatility/i);
    expect(screen.getAllByText("30D realized vol").length).toBeGreaterThan(0);
    expect(screen.getAllByText("365D realized vol").length).toBeGreaterThan(0);
  });
});

describe("HVT pane — window table (DataGrid)", () => {
  it("sorts by window length (default ascending) without a constant Formula column", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<HVTPane code="HVT" symbol="AAPL" />);
    const grid = screen.getByRole("grid", {
      name: /volatility term structure/i,
    });
    expect(
      within(grid).getByRole("columnheader", { name: /realized vol/i }),
    ).toBeInTheDocument();
    expect(
      within(grid).getByRole("columnheader", { name: /samples/i }),
    ).toBeInTheDocument();
    // The constant Formula column is gone (methodology lives in the note).
    expect(
      within(grid).queryByRole("columnheader", { name: /formula/i }),
    ).toBeNull();
    // Default sort: shortest window first, header reports it.
    const rows = within(grid).getAllByRole("row");
    expect(rows[1].textContent).toContain("30D realized vol");
    expect(rows[1].textContent).toContain("29.6%");
    expect(
      within(grid)
        .getByRole("columnheader", { name: /window/i })
        .getAttribute("aria-sort"),
    ).toBe("ascending");
  });

  it("offers a CSV export of the visible window rows", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<HVTPane code="HVT" symbol="AAPL" />);
    const csv = screen.getByTitle("Download CSV");
    expect(csv).not.toBeDisabled();
    expect(csv.getAttribute("aria-label")).toMatch(/4 realized-vol windows/i);
  });

  it("renders the reference template labeled exactly once (pill + one note)", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    render(<HVTPane code="HVT" symbol="AAPL" />);
    expect(screen.getByText("reference")).toBeInTheDocument();
    expect(screen.getAllByTestId("hvt-ref-note").length).toBe(1);
    expect(
      screen.getAllByText(/NOT measured from live closes/i).length,
    ).toBe(1);
    // Reference rows ARE renderable — but only under the reference label.
    expect(screen.getByText("22.6%")).toBeInTheDocument();
    // No fabricated rolling series: the sparkline is replaced by an honest
    // note instead of an empty chart.
    expect(screen.getByText(/No rolling history returned/i)).toBeInTheDocument();
  });
});

describe("HVT pane — responsive sparkline (FIX R2-#2)", () => {
  it("fills the measured card width instead of a fixed 560px", () => {
    setMockFn({ state: "ok", ...okPayload() });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 912,
      height: 88,
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 912,
      bottom: 88,
      toJSON: () => ({}),
    } as DOMRect);
    render(<HVTPane code="HVT" symbol="AAPL" />);
    const svg = screen
      .getByTestId("hvt-spark-measure")
      .querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("912");
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
