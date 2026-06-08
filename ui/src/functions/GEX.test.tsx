/**
 * GEX pane — data-honesty + render-contract tests.
 *
 * The backend GEX function silently degrades to a synthetic 3-strike
 * reference model (hardcoded OI, constant IV) when the live yfinance
 * options chain is unavailable. Before the honesty fix the pane showed a
 * subtle "reference" pill that did NOT tell the user the curve was
 * fabricated, not real dealer positioning. These tests pin:
 *
 *  - the four load states (loading / empty / error / ok) render;
 *  - a SYNTHETIC payload renders a prominent warning badge + inline note;
 *  - a LIVE payload does NOT render that warning and shows "live chain";
 *  - numeric values come from `@/lib/format` (compact "$" + price);
 *  - chart rows carry descriptive aria-labels for screen readers.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { GEXPane } from "./GEX";

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

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

const liveSummary = {
  net_gex: -1.5e9,
  call_gex_total: 2.4e8,
  put_gex_total: -1.74e9,
  gamma_flip: 600,
  call_wall: 620,
  put_wall: 580,
  n_strikes: 3,
  source_mode: "live_chain",
  synthetic: false,
  degraded: false,
};

const liveRows = [
  { strike: 580, gex: -8.0e8, value: -8.0e8 },
  { strike: 600, gex: 1.2e8, value: 1.2e8 },
  { strike: 620, gex: 2.4e8, value: 2.4e8 },
];

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        symbol: "SPY",
        spot: 612.34,
        expiries: ["2026-07-17"],
        rows: liveRows,
        curve: liveRows,
        summary: liveSummary,
        call_wall: { strike: 620, gex: 2.4e8 },
        put_wall: { strike: 580, gex: -8.0e8 },
      },
    },
  };
}

function syntheticPayload() {
  return {
    data: {
      data: {
        status: "ok",
        symbol: "SPY",
        spot: 612.34,
        expiries: ["30d"],
        rows: liveRows,
        curve: liveRows,
        summary: {
          ...liveSummary,
          source_mode: "synthetic_reference_chain",
          synthetic: true,
          degraded: true,
        },
        warning:
          "Live options chain unavailable — showing a synthetic reference model, NOT real dealer positioning.",
        reason:
          "Live options chain unavailable — showing a synthetic reference model, NOT real dealer positioning.",
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("GEX pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the empty state when there are no rows", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "empty", rows: [], curve: [], summary: {} } },
    });
    render(<GEXPane code="GEX" symbol="SPY" />);
    expect(screen.getByText(/No options chain/i)).toBeInTheDocument();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<GEXPane code="GEX" symbol="SPY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the chart rows when ok", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    expect(container.querySelectorAll(".gex-chart__row").length).toBe(3);
  });
});

describe("GEX pane — data honesty", () => {
  it("renders a prominent synthetic warning badge + inline note for synthetic payloads", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    render(<GEXPane code="GEX" symbol="SPY" />);
    // Prominent badge wording.
    expect(screen.getByText(/Synthetic model/i)).toBeInTheDocument();
    // Inline note states the data is NOT real dealer positioning.
    expect(
      screen.getByText(/NOT real dealer positioning/i),
    ).toBeInTheDocument();
    // The deceptive subtle "reference" pill is gone for synthetic data.
    expect(screen.queryByText(/^reference$/i)).toBeNull();
  });

  it("does NOT render the synthetic warning for a live payload", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<GEXPane code="GEX" symbol="SPY" />);
    expect(screen.queryByText(/Synthetic model/i)).toBeNull();
    expect(screen.queryByText(/NOT real dealer positioning/i)).toBeNull();
    // Live indicator is present.
    expect(screen.getByText(/live chain/i)).toBeInTheDocument();
  });
});

describe("GEX pane — formatting + accessibility", () => {
  it("formats net GEX with compact currency from @/lib/format", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<GEXPane code="GEX" symbol="SPY" />);
    // formatCurrency(-1.5e9, {compact:true,fractionDigits:2}) => "-$1.5B"
    expect(screen.getByText("-$1.5B")).toBeInTheDocument();
  });

  it("formats strike KPIs as prices (no raw locale fmtStrike)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    // Spot 612.34 appears in the subtitle via formatPrice.
    expect(container.textContent).toContain("612.34");
  });

  it("gives every chart row a descriptive aria-label", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const rows = Array.from(container.querySelectorAll(".gex-chart__row"));
    expect(rows.length).toBe(3);
    for (const row of rows) {
      const label = row.getAttribute("aria-label");
      expect(label).toBeTruthy();
      expect(label).toMatch(/gamma/i);
    }
    // The call-gamma row (positive) names "call"; the put-gamma row "put".
    const callRow = rows.find((r) =>
      (r.getAttribute("aria-label") ?? "").includes("620"),
    );
    expect(callRow?.getAttribute("aria-label")).toMatch(/call gamma/i);
    const putRow = rows.find((r) =>
      (r.getAttribute("aria-label") ?? "").includes("580"),
    );
    expect(putRow?.getAttribute("aria-label")).toMatch(/put gamma/i);
  });

  it("marks decorative legend swatches aria-hidden", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const swatches = container.querySelectorAll(".gex-chart__sw");
    expect(swatches.length).toBeGreaterThan(0);
    for (const sw of swatches) {
      expect(sw.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("gives the chart container an accessible role + label", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const chart = container.querySelector(".gex-chart__rows");
    expect(chart?.getAttribute("aria-label")).toBeTruthy();
  });
});
