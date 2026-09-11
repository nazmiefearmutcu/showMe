/**
 * GLCO pane — real-vs-synthetic "5d" sparkline honesty.
 *
 * The backend can ship a per-row history series (`_contract_snapshot(...,
 * include_history=True)`, the BOIL/BGAS convention). When it does, the "5d"
 * cell renders it solid + marked data-synthetic="false". When it does not,
 * the procedural fallback must be de-emphasized and marked synthetic — never
 * an unlabeled fake history line. KPI cards only ever draw real series.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const recordedCalls: Array<{ params?: Record<string, unknown> }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    recordedCalls.push(opts);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { GLCOPane } from "./GLCO";

function okData(rows: unknown[]) {
  return {
    data: { status: "ok", source_mode: "live_yfinance", rows },
    sources: ["yfinance_futures"],
    elapsed_ms: 9,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  recordedCalls.length = 0;
});

afterEach(() => {
  cleanup();
});

describe("GLCO pane — 5d sparkline honesty", () => {
  it("polls without putting the visibility tick into the fetch params (R2-F2)", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { symbol: "GC=F", name: "Gold", sector: "metals", last: 2000, change_pct: -0.5 },
    ]);
    render(<GLCOPane code="GLCO" />);
    expect(recordedCalls.length).toBeGreaterThan(0);
    for (const call of recordedCalls) {
      // A changing param key would re-key useFunction and flash the skeleton
      // on every 60s poll — the tick must stay out of the params object.
      expect(call.params ?? {}).not.toHaveProperty("tick");
    }
  });
  it("marks a procedural fallback line synthetic with an explanatory title", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { symbol: "GC=F", name: "Gold", sector: "metals", last: 2000, change_pct: -0.5 },
    ]);
    const { container } = render(<GLCOPane code="GLCO" />);

    const synthetic = container.querySelectorAll('[data-synthetic="true"]');
    expect(synthetic.length).toBeGreaterThanOrEqual(1);
    synthetic.forEach((el) => {
      expect(el.getAttribute("title")).toBe(
        "Illustrative trend — no real history available",
      );
      expect(el.querySelector("svg")).not.toBeNull();
    });
  });

  it("renders a real per-row history series as data-synthetic=false", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { symbol: "CL=F", name: "WTI Crude", sector: "energy", last: 70, change_pct: 1.2, history: [1, 2, 3, 4, 5, 6] },
    ]);
    const { container } = render(<GLCOPane code="GLCO" />);

    const real = container.querySelectorAll('[data-synthetic="false"]');
    expect(real.length).toBeGreaterThanOrEqual(1);
    real.forEach((el) => {
      expect(el.getAttribute("title")).toBe("Daily close history from the payload");
      expect(el.querySelector("svg")).not.toBeNull();
    });
    // The real row must not simultaneously render a synthetic marker.
    expect(container.querySelectorAll('[data-synthetic="true"]').length).toBe(0);
  });

  it("keeps the synthetic/real distinction on a mixed payload", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { symbol: "CL=F", name: "WTI Crude", sector: "energy", last: 70, change_pct: 1.2, history: [1, 2, 3, 4, 5, 6] },
      { symbol: "GC=F", name: "Gold", sector: "metals", last: 2000, change_pct: -0.5 },
    ]);
    render(<GLCOPane code="GLCO" />);

    const table = screen.getByRole("table");
    const realRow = within(table).getByText("CL=F").closest("tr")!;
    const synthRow = within(table).getByText("GC=F").closest("tr")!;
    expect(realRow.querySelector('[data-synthetic="false"]')).not.toBeNull();
    expect(synthRow.querySelector('[data-synthetic="true"]')).not.toBeNull();
  });
});
