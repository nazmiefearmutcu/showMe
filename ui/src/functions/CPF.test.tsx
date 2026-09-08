/**
 * CPF pane — render-contract + model-honesty tests (CRVF/GEX pattern).
 *
 * The backend CPF serves a live actual series (Yahoo futures proxy) plus a
 * trend-extrapolated forecast leg with a vintage stamp. Pins:
 *
 *  - the load states (loading / error / empty / ok) render;
 *  - the ok payload renders cards, actual+forecast curve and the forecast
 *    table with Δ-vs-actual deltas;
 *  - the trend-model honesty notice + pill always render for ok payloads;
 *  - data_mode is surfaced verbatim (live_official → positive pill);
 *  - the horizon segmented control interaction.
 *
 * `useFunction` is mocked via a mutable shared state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CPFPane } from "./CPF";

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

/* ── fixtures: shape mirrors commodity/_funcs.py CPFFunction ───────── */

function livePayload() {
  const actual = Array.from({ length: 6 }, (_, i) => ({
    date: `2026-09-0${i + 1}`,
    value: 90 + i * 0.5,
  }));
  const forecast = [
    { date: "2026-10-07", value: 92.5 },
    { date: "2026-11-06", value: 91.0 },
  ];
  return {
    data: {
      data: {
        status: "ok",
        series_id: "WTISPLC",
        commodity: "WTI crude oil",
        unit: "USD/bbl",
        horizon: "1Y",
        actual,
        forecast,
        forecast_vintage: "2026-09-06",
        as_of: "2026-09-06",
        data_mode: "live_official",
      },
      sources: ["yfinance"],
      elapsed_ms: 40,
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

describe("CPF pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<CPFPane code="CPF" symbol="CL=F" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<CPFPane code="CPF" symbol="CL=F" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state when the feed returns nothing", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "The live Yahoo futures feed for the actual price leg was unreachable.",
          actual: [],
          forecast: [],
        },
      },
    });
    render(<CPFPane code="CPF" symbol="CL=F" />);
    expect(screen.getByText(/Forecast feed unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/was unreachable/i)).toBeInTheDocument();
  });
});

describe("CPF pane — ok payload", () => {
  it("renders latest actual, endpoint forecast and implied move cards", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<CPFPane code="CPF" symbol="CL=F" />);
    // Latest actual = 90 + 5*0.5 = 92.500; endpoint forecast = 91.0.
    expect(container.textContent).toContain("92.500");
    expect(container.textContent).toContain("91.0");
    // Implied move: 91/92.5 − 1 = −1.62%.
    expect(container.textContent).toContain("-1.62%");
    expect(container.textContent).toContain("WTI crude oil");
    expect(screen.getAllByText(/VINTAGE 2026-09-06/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the actual + forecast curve with forecast dots", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<CPFPane code="CPF" symbol="CL=F" />);
    const svg = container.querySelector('svg[role="img"]');
    expect(svg?.getAttribute("aria-label")).toMatch(
      /6 actual and 2 forecast points/i,
    );
    expect(container.querySelectorAll("polyline").length).toBe(2);
    expect(container.querySelectorAll("circle").length).toBe(3);
  });

  it("renders the forecast table with Δ-vs-actual deltas", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<CPFPane code="CPF" symbol="CL=F" />);
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(2);
    // 92.5 / 92.5 − 1 = 0.00%; 91 / 92.5 − 1 = −1.62%.
    expect(rows[0].textContent).toContain("92.500");
    expect(rows[1].textContent).toContain("-1.62%");
  });
});

describe("CPF pane — model honesty", () => {
  it("always shows the trend-model notice + pill for ok payloads", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<CPFPane code="CPF" symbol="CL=F" />);
    expect(screen.getByText(/NOT analyst consensus/i)).toBeInTheDocument();
    expect(screen.getByText("trend model")).toBeInTheDocument();
    // data_mode surfaced verbatim via the positive live pill.
    expect(screen.getAllByText(/live actual/i).length).toBeGreaterThanOrEqual(1);
  });
});

describe("CPF pane — interaction", () => {
  it("switches the horizon via the segmented control", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<CPFPane code="CPF" symbol="CL=F" />);
    const group = screen.getByLabelText("HORIZON");
    const opt1y = group.querySelector('button[title="HORIZON 1Y"]');
    const opt2y = group.querySelector('button[title="HORIZON 2Y"]');
    expect(opt1y?.className).toContain("fn-segmented__opt--active");
    if (opt2y) fireEvent.click(opt2y);
    expect(opt2y?.className).toContain("fn-segmented__opt--active");
    expect(opt1y?.className).not.toContain("fn-segmented__opt--active");
  });
});
