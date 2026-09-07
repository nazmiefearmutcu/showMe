/**
 * OVME pane — render-contract + interaction tests.
 *
 * Pure Black-Scholes model pane. Tests pin:
 *
 *  - the four load states (loading / error / bad-payload / ok) render;
 *  - the ok state renders price + 5 greeks, the value-curve SVG and the
 *    sampled sensitivity grid with the current-spot row highlighted;
 *  - CALL/PUT toggle persists and re-labels the pane;
 *  - editing an input persists it under `showme.ovme.*`.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OVMEPane } from "./OVME";

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
  const curve = [];
  for (let i = 0; i < 51; i += 1) {
    const s = 75 + i; // 75 .. 125, spot 100 at index 25
    const intrinsic = Math.max(s - 100, 0);
    curve.push({
      spot: s,
      price: intrinsic + 4.5,
      intrinsic,
      time_value: 4.5,
      delta: s >= 100 ? 0.6 : 0.3,
    });
  }
  return {
    data: {
      data: {
        status: "ok",
        spot: 100,
        strike: 100,
        T: 0.25,
        vol: 0.3,
        rate: 0.045,
        div_yield: 0,
        type: "CALL",
        price: 4.263,
        delta: 0.4228,
        gamma: 0.026,
        theta: -0.0356,
        vega: 0.1953,
        rho: 0.0951,
        d1: 0.21,
        d2: 0.06,
        curve,
        sensitivity: curve,
        summary: { price: 4.263 },
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

describe("OVME pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<OVMEPane code="OVME" symbol="SPY" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders an honest bad-payload state for invalid model inputs", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "error",
          summary: { error: "invalid_inputs: S and K must be > 0 (got S=-5, K=100)" },
          curve: [],
        },
      },
    });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    expect(screen.getByText(/Model needs valid inputs/i)).toBeInTheDocument();
    expect(screen.getByText(/invalid_inputs/i)).toBeInTheDocument();
  });

  it("renders price, greeks, curve and sensitivity grid when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OVMEPane code="OVME" symbol="SPY" />);
    // Price + greeks cards (formatted to fixed digits). The price shows in
    // both the stat card and the chart header — assert presence, not count.
    expect(screen.getAllByText("4.263").length).toBeGreaterThan(0);
    expect(screen.getByText("0.4228")).toBeInTheDocument();
    expect(screen.getByText("-0.0356")).toBeInTheDocument();
    expect(screen.getByText("0.1953")).toBeInTheDocument();
    expect(screen.getByText("0.0951")).toBeInTheDocument();
    // Value curve SVG present with an aria-label.
    const chart = container.querySelector('svg[role="img"]');
    expect(chart?.getAttribute("aria-label")).toMatch(/value from spot/i);
    // Sensitivity grid: 51 points sampled every 5th = 11 rows.
    const rows = container.querySelectorAll('table[aria-label="Value sensitivity to spot"] tbody tr');
    expect(rows.length).toBe(11);
    // The current-spot row (spot 100) is highlighted.
    const highlighted = Array.from(rows).find((r) => r.getAttribute("style")?.includes("accent-soft"));
    expect(highlighted?.textContent).toContain("100");
  });
});

describe("OVME pane — interactions", () => {
  it("toggling CALL/PUT persists the type and relabels the pane", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    expect(screen.getByText(/Option Valuation — CALL/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("PUT"));
    expect(localStorage.getItem("showme.ovme.type")).toBe("PUT");
    expect(screen.getByText(/Option Valuation — PUT/)).toBeInTheDocument();
  });

  it("editing the spot input persists it", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    const spot = screen.getByLabelText("Underlying spot price");
    fireEvent.change(spot, { target: { value: "112.5" } });
    expect(localStorage.getItem("showme.ovme.spot")).toBe("112.5");
  });
});
