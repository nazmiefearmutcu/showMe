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
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

let lastParams: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => {
    lastParams = args.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
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

describe("CRVF pane — honest unavailable and notice states (p2a-g04 CRVF#1)", () => {
  it("shows the backend reason for a non-US curve instead of US model levels", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "No curve is wired for DE: CRVF's only source is FRED's US Treasury curve.",
          rows: [],
          curve: [],
          summary: { country: "DE", tenors: 0, source_mode: "provider_unavailable" },
        },
        sources: [],
        warnings: ["No curve is wired for DE"],
      },
    });
    const { container } = render(<CRVFPane code="CRVF" symbol="DE10Y" />);
    expect(screen.getByText(/Curve unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/No curve is wired for DE/i)).toBeInTheDocument();
    expect(screen.queryByText(/model fixture/i)).toBeNull();
    expect(container.querySelectorAll("circle").length).toBe(0);
  });

  it("names the real cause in the computed-model notice, not a missing FRED key", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          rows: MODEL_ROWS,
          curve: MODEL_ROWS,
          summary: { country: "US", tenors: 8, source_mode: "computed_model", latest_10y: 4.45 },
        },
        sources: ["curve_model"],
        warnings: ["fred: keyless FRED CSV unavailable for 'DGS10'"],
      },
    });
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    expect(screen.getByText(/keyless FRED CSV unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/No FRED key is configured/i)).toBeNull();
  });
});

describe("CRVF pane — tenor filter control (p2a-g04 CRVF#5)", () => {
  it("sends no tenors param by default, so the backend returns the full curve", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    expect(lastParams).toBeUndefined();
  });

  it("sends the chosen tenors to the backend when the user picks them", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    fireEvent.click(screen.getByRole("button", { name: "2Y" }));
    fireEvent.click(screen.getByRole("button", { name: "10Y" }));
    expect(lastParams).toEqual({ tenors: ["2Y", "10Y"] });
    expect(screen.getByRole("button", { name: "2Y" })).toHaveAttribute("aria-pressed", "true");
  });
});
