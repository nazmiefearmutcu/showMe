/**
 * PFA — specialized Performance Attribution pane tests.
 *
 * Pins the four render states. PFA's backend serves a labelled sample when no
 * weight maps are passed, so the success case also pins the honesty badge.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({ useFunction: () => mockReturn.current }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PerformanceAttributionPane } from "./PerformanceAttribution";

function ok(
  payload: Record<string, unknown>,
  envelope: { sources?: string[]; warnings?: string[] } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "PFA",
      instrument: null,
      data: payload,
      metadata: { live: false },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: envelope.sources ?? ["brinson_model"],
      warnings: envelope.warnings ?? [],
      elapsed_ms: 12,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

const SAMPLE_PAYLOAD = {
  status: "ok",
  rows: [
    {
      sector: "Technology",
      port_weight: 0.45,
      bench_weight: 0.3,
      port_return: 0.18,
      bench_return: 0.12,
      allocation_effect: 0.006,
      selection_effect: 0.018,
      interaction_effect: 0.0042,
      total_effect: 0.0282,
    },
    {
      sector: "Energy",
      port_weight: 0.1,
      bench_weight: 0.08,
      port_return: -0.04,
      bench_return: -0.06,
      allocation_effect: -0.0004,
      selection_effect: 0.0016,
      interaction_effect: 0.0004,
      total_effect: 0.0016,
    },
  ],
  totals: {
    portfolio_return: 0.1,
    benchmark_return: 0.06,
    active_return: 0.04,
    allocation: 0.0056,
    selection: 0.0196,
    interaction: 0.0046,
  },
  summary: { active_return: 0.04, sectors: 2 },
  methodology: "Brinson-Hood-Beebower attribution.",
};

describe("PFA Performance Attribution pane", () => {
  it("renders a loading skeleton", () => {
    mockReturn.current = { state: "loading", data: undefined, error: undefined, refetch: vi.fn() };
    const { container } = render(<PerformanceAttributionPane code="PFA" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    mockReturn.current = { state: "error", data: undefined, error: new Error("pfa boom"), refetch };
    render(<PerformanceAttributionPane code="PFA" />);
    expect(screen.getByText(/pfa boom/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the empty state when no sector rows are returned", () => {
    ok({ status: "ok", rows: [], totals: {} });
    render(<PerformanceAttributionPane code="PFA" />);
    expect(screen.getByText("No data available")).toBeInTheDocument();
  });

  it("renders the active-return hero, sector table and effect ladder", () => {
    ok(SAMPLE_PAYLOAD);
    const { container } = render(<PerformanceAttributionPane code="PFA" />);
    expect(screen.getByText("+4.00%")).toBeInTheDocument();
    // Sector names appear in both the table and the effect ladder.
    expect(screen.getAllByText("Technology").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Energy").length).toBeGreaterThan(0);
    // 3 effect bars + 2 sector bars.
    expect(container.querySelectorAll(".portfolio-ladder__row").length).toBe(5);
    expect(container.querySelectorAll("table").length).toBe(1);
  });

  it("keeps the sample-data disclosure visible for the modelled payload", () => {
    ok(SAMPLE_PAYLOAD);
    render(<PerformanceAttributionPane code="PFA" />);
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
  });
});
