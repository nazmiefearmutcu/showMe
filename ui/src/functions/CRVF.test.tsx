/**
 * CRVF pane — render-contract + data-honesty tests.
 *
 * The backend CRVF serves a labelled computed-model curve unless a FRED
 * key is configured (live=true). These tests pin:
 *
 *  - the load states (loading / error / empty / ok) render;
 *  - the SVG maturity curve renders one dot per tenor with tooltips;
 *  - the tenor table shows spread-vs-10Y in bps with signed formatting;
 *  - a computed_model payload shows the prominent MODEL FIXTURE pill +
 *    inline honesty note, and a fred payload does not;
 *  - the 2s10s slope card computes from the payload.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CRVFPane } from "./CRVF";

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

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

/* ── fixtures: model curve shape mirrors bond/crvf.py ──────────────── */

const MODEL_ROWS = [
  { country: "US", tenor: "1M", tenor_years: 0.0833, yield: 5.32, as_of: "2026-09-07" },
  { country: "US", tenor: "3M", tenor_years: 0.25, yield: 5.28, as_of: "2026-09-07" },
  { country: "US", tenor: "6M", tenor_years: 0.5, yield: 5.15, as_of: "2026-09-07" },
  { country: "US", tenor: "1Y", tenor_years: 1, yield: 4.92, as_of: "2026-09-07" },
  { country: "US", tenor: "2Y", tenor_years: 2, yield: 4.62, as_of: "2026-09-07" },
  { country: "US", tenor: "5Y", tenor_years: 5, yield: 4.38, as_of: "2026-09-07" },
  { country: "US", tenor: "10Y", tenor_years: 10, yield: 4.45, as_of: "2026-09-07" },
  { country: "US", tenor: "30Y", tenor_years: 30, yield: 4.67, as_of: "2026-09-07" },
];

function modelPayload() {
  return {
    data: {
      data: {
        rows: MODEL_ROWS,
        curve: MODEL_ROWS,
        summary: {
          country: "US",
          tenors: 8,
          source_mode: "computed_model",
          latest_10y: 4.45,
        },
        methodology: "CRVF returns a sovereign yield curve ordered by maturity.",
      },
      sources: ["curve_model"],
      elapsed_ms: 2,
    },
  };
}

function fredPayload() {
  const payload = modelPayload();
  payload.data.data.summary.source_mode = "fred";
  payload.data.sources = ["fred"];
  return payload;
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("CRVF pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<CRVFPane code="CRVF" symbol="US10Y" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when no tenor points come back", () => {
    setMockFn({
      state: "ok",
      data: { data: { rows: [], curve: [], summary: {} } },
    });
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    expect(screen.getByText(/No curve returned/i)).toBeInTheDocument();
  });
});

describe("CRVF pane — curve chart + table", () => {
  it("renders the maturity curve with one dot per tenor", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    const { container } = render(<CRVFPane code="CRVF" symbol="US10Y" />);
    const svg = container.querySelector('svg[role="img"]');
    expect(svg?.getAttribute("aria-label")).toMatch(/8 tenor points/i);
    expect(container.querySelectorAll("circle").length).toBe(8);
  });

  it("gives each curve dot a tenor tooltip title", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    const { container } = render(<CRVFPane code="CRVF" symbol="US10Y" />);
    const titles = Array.from(container.querySelectorAll("circle title"));
    expect(titles.length).toBe(8);
    expect(titles[0].textContent).toContain("1M");
    expect(titles[0].textContent).toContain("5.320%");
  });

  it("renders the tenor table with spread-vs-10Y in bps", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    const { container } = render(<CRVFPane code="CRVF" symbol="US10Y" />);
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(8);
    // 2Y: 4.62 − 4.45 = +17.0 bps (front yields sit ABOVE the 10Y reference
    // on this inverted fixture curve).
    expect(rows[4].textContent).toContain("+17.0 bps");
    // 30Y: 4.67 − 4.45 = +22.0 bps.
    expect(rows[7].textContent).toContain("+22.0 bps");
    // The 10Y reference row itself is zero.
    expect(rows[6].textContent).toContain("+0.0 bps");
  });
});

describe("CRVF pane — data honesty", () => {
  it("shows the MODEL FIXTURE pill + notice for computed_model payloads", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    expect(screen.getByText(/model fixture/i)).toBeInTheDocument();
    expect(
      screen.getByText(/NOT live market yields/i),
    ).toBeInTheDocument();
  });

  it("does NOT show the fixture notice for a fred payload", () => {
    setMockFn({ state: "ok", ...fredPayload() });
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    expect(screen.getByText(/FRED live/i)).toBeInTheDocument();
    expect(screen.queryByText(/model fixture/i)).toBeNull();
    expect(screen.queryByText(/NOT live market yields/i)).toBeNull();
  });
});

describe("CRVF pane — headline stats", () => {
  it("computes the 2s10s slope from the payload", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    // 10Y 4.45 − 2Y 4.62 = −17.0 bps (inverted). The same number also shows
    // on the 2Y table row, hence getAllByText.
    expect(
      screen.getAllByText("-17.0 bps").length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/INVERTED/i)).toBeInTheDocument();
  });

  it("computes the 30Y − 1M long-short slope", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    // 4.67 − 5.32 = −65.0 bps.
    expect(screen.getByText("-65.0 bps")).toBeInTheDocument();
  });
});
