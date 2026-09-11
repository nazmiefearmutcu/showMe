/**
 * PFA — specialized Performance Attribution pane tests.
 *
 * Pins the four render states. PFA's backend serves a labelled sample when no
 * weight maps are passed, so the success case also pins the honesty badge.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const mockArgs: {
  current: { code?: string; params?: Record<string, unknown> } | null;
} = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    mockArgs.current = args as (typeof mockArgs)["current"];
    return mockReturn.current;
  },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PerformanceAttributionPane, parseSectorMap } from "./PerformanceAttribution";

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
  mockArgs.current = null;
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

describe("PFA custom weights editor (G3)", () => {
  const fillAll = () => {
    fireEvent.change(screen.getByLabelText("Port weights"), {
      target: { value: "Technology: 45, Financials: 20" },
    });
    fireEvent.change(screen.getByLabelText("Port returns"), {
      target: { value: "Technology: 18, Financials: 5" },
    });
    fireEvent.change(screen.getByLabelText("Bench weights"), {
      target: { value: "Technology: 30, Financials: 18" },
    });
    fireEvent.change(screen.getByLabelText("Bench returns"), {
      target: { value: "Technology: 12, Financials: 4" },
    });
  };

  it("sends no params until the editor is applied (default sample preserved)", () => {
    ok(SAMPLE_PAYLOAD);
    render(<PerformanceAttributionPane code="PFA" />);
    expect(mockArgs.current?.code).toBe("PFA");
    expect(mockArgs.current?.params).toBeUndefined();
  });

  it("applies all four maps converted from percent to fraction", () => {
    ok(SAMPLE_PAYLOAD);
    render(<PerformanceAttributionPane code="PFA" />);
    fireEvent.click(screen.getByTestId("pfa-editor-toggle"));
    fillAll();
    fireEvent.click(screen.getByTestId("pfa-editor-apply"));
    expect(mockArgs.current?.params).toEqual({
      port_weights: { Technology: 0.45, Financials: 0.2 },
      port_returns: { Technology: 0.18, Financials: 0.05 },
      bench_weights: { Technology: 0.3, Financials: 0.18 },
      bench_returns: { Technology: 0.12, Financials: 0.04 },
    });
    // Applied state is disclosed in the editor head.
    expect(screen.getByText(/custom inputs applied/i)).toBeInTheDocument();
  });

  it("keeps Apply disabled until all four maps parse", () => {
    ok(SAMPLE_PAYLOAD);
    render(<PerformanceAttributionPane code="PFA" />);
    fireEvent.click(screen.getByTestId("pfa-editor-toggle"));
    const apply = screen.getByTestId("pfa-editor-apply");
    expect(apply).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Port weights"), { target: { value: "Technology: 45" } });
    fireEvent.change(screen.getByLabelText("Port returns"), { target: { value: "Technology: 18" } });
    fireEvent.change(screen.getByLabelText("Bench weights"), { target: { value: "Technology: 30" } });
    expect(apply).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Bench returns"), { target: { value: "Technology: 12" } });
    expect(apply).toBeEnabled();
    // Garbage-only input never counts as a complete map.
    fireEvent.change(screen.getByLabelText("Bench returns"), { target: { value: "not a map" } });
    expect(apply).toBeDisabled();
  });

  it("Reset returns to the backend sample (params undefined)", () => {
    ok(SAMPLE_PAYLOAD);
    render(<PerformanceAttributionPane code="PFA" />);
    fireEvent.click(screen.getByTestId("pfa-editor-toggle"));
    fillAll();
    fireEvent.click(screen.getByTestId("pfa-editor-apply"));
    expect(mockArgs.current?.params).toBeDefined();
    fireEvent.click(screen.getByTestId("pfa-editor-reset"));
    expect(mockArgs.current?.params).toBeUndefined();
    expect(screen.getByText(/sample runs until applied/i)).toBeInTheDocument();
  });

  it("parseSectorMap skips unparseable fragments and converts percents", () => {
    expect(parseSectorMap("Tech: 45, nope, Energy:-4\nHealth: 1.5")).toEqual({
      Tech: 0.45,
      Energy: -0.04,
      Health: 0.015,
    });
    expect(parseSectorMap("")).toEqual({});
  });
});
