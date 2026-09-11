/**
 * WCRS pane — cross-rate change + "5d" sparkline honesty.
 *
 * Pins three rules:
 *  - a missing / placeholder change_pct renders the em-dash, never a
 *    fabricated "+0.00%" (the backend used to hardcode 0.0 with no series);
 *  - a real per-row history series renders data-synthetic="false", the
 *    procedural fallback is marked synthetic;
 *  - the KPI basket Δ is an em-dash (not "+0.000%") when no real change
 *    data exists in the payload.
 *
 * Plus the terminal-grade fixes: the "live" pill is reserved for live_*
 * source modes (envelope warnings render), spread pips come from the
 * backend's JPY-aware field, the pair cell navigates to FXIP, and the grid
 * carries an accessible name.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
const recordedCalls: Array<{ params?: Record<string, unknown> }> = [];
const setFocusedTargetSpy = vi.fn();

// jsdom ships no ResizeObserver — stub it so ResizableChartFrame mounts.
class FakeResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;

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

vi.mock("@/lib/workspace", () => ({
  useWorkspace: (
    selector: (s: { setFocusedTarget: typeof setFocusedTargetSpy }) => unknown,
  ) => selector({ setFocusedTarget: setFocusedTargetSpy }),
}));

vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { WCRSPane } from "./WCRS";

function okData(rows: unknown[], surface?: unknown) {
  return {
    data: {
      status: "ok",
      source_mode: "live_official",
      rows,
      ...(surface ? { surface } : {}),
      methodology: "test",
    },
    sources: ["frankfurter"],
    elapsed_ms: 4,
  };
}

function referenceData(rows: unknown[]) {
  return {
    data: {
      status: "ok",
      source_mode: "reference_cross_rate_matrix",
      rows,
      methodology: "test",
    },
    sources: ["reference_cross_rates"],
    warnings: [
      "live cross-rate provider unavailable; using labelled reference matrix",
    ],
    elapsed_ms: 3,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  recordedCalls.length = 0;
  setFocusedTargetSpy.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("WCRS pane — change honesty", () => {
  it("polls without putting the visibility tick into the fetch params (R2-F2)", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { base: "USD", quote: "EUR", pair: "USDEUR", rate: 0.9, bid: 0.89, ask: 0.91, change_pct: 0.1 },
    ]);
    render(<WCRSPane code="WCRS" />);
    expect(recordedCalls.length).toBeGreaterThan(0);
    for (const call of recordedCalls) {
      expect(call.params ?? {}).not.toHaveProperty("tick");
    }
  });
  it("renders an em-dash (not +0.00%) for missing / placeholder changes", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { base: "USD", quote: "EUR", pair: "USDEUR", rate: 0.9, bid: 0.89, ask: 0.91, change_pct: 0.0 },
      { base: "USD", quote: "GBP", pair: "USDGBP", rate: 0.78, bid: 0.77, ask: 0.79, change_pct: null },
    ]);
    const { container } = render(<WCRSPane code="WCRS" />);

    const missing = container.querySelectorAll(
      '[title="No change data in this payload"]',
    );
    expect(missing.length).toBe(2);
    missing.forEach((el) => expect(el.textContent).toBe("—"));
    // No fabricated +0.00% chip anywhere in the table.
    expect(screen.queryByText("+0.00%")).toBeNull();
  });

  it("shows the KPI basket Δ as an em-dash when no real change data exists", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { base: "USD", quote: "EUR", pair: "USDEUR", rate: 0.9, change_pct: 0.0 },
    ]);
    render(<WCRSPane code="WCRS" />);
    expect(screen.getByText(/NO CHANGE DATA · 1 pairs/)).toBeInTheDocument();
    expect(screen.queryByText(/\+0\.000%/)).toBeNull();
  });

  it("uses the real history series when the payload ships one", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { base: "USD", quote: "JPY", pair: "USDJPY", rate: 150, change_pct: 0.5, history: [1, 2, 3, 4, 5, 6] },
      { base: "USD", quote: "EUR", pair: "USDEUR", rate: 0.9, change_pct: null },
    ]);
    const { container } = render(<WCRSPane code="WCRS" />);

    const table = screen.getByRole("table");
    const realRow = within(table).getByText("USDJPY").closest("tr")!;
    const synthRow = within(table).getByText("USDEUR").closest("tr")!;
    expect(realRow.querySelector('[data-synthetic="false"]')).not.toBeNull();
    expect(synthRow.querySelector('[data-synthetic="true"]')).not.toBeNull();
    expect(synthRow.querySelector('[data-synthetic="true"]')!.getAttribute("title")).toBe(
      "Illustrative trend — no real history available",
    );
    // The placeholder-zero rule: a real non-zero change renders normally.
    expect(
      container.querySelectorAll('[title="No change data in this payload"]').length,
    ).toBe(1);
  });

  it("keeps heatmap cells neutral when no change data exists", () => {
    mockFn.state = "ok";
    mockFn.data = okData(
      [{ base: "USD", quote: "EUR", pair: "USDEUR", rate: 0.9, change_pct: null }],
      [{ base: "USD", quote: "EUR", pair: "USDEUR", rate: 0.9 }],
    );
    const { container } = render(<WCRSPane code="WCRS" />);
    // No change label is printed inside the heatmap cells.
    const heatmap = container.querySelector('[aria-label="Resize cross-rate heatmap"]');
    expect(heatmap).not.toBeNull();
    expect(within(heatmap as HTMLElement).queryByText(/%/)).toBeNull();
    expect(within(heatmap as HTMLElement).queryByText("+0.00%")).toBeNull();
  });
});

describe("WCRS pane — honesty + terminal fixes", () => {
  it("shows a reference pill (never live) on the reference fallback + renders warnings", () => {
    mockFn.state = "ok";
    mockFn.data = referenceData([
      { base: "USD", quote: "EUR", pair: "USDEUR", rate: 0.9, change_pct: null },
    ]);
    render(<WCRSPane code="WCRS" />);
    // Old behaviour: green "live" pill whenever state === "ok".
    expect(screen.queryByText("live")).toBeNull();
    expect(screen.getByText("reference")).toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: /data quality warning/i }),
    ).toHaveTextContent(/labelled reference matrix/i);
  });

  it("uses the backend's JPY-aware spread_pips instead of spread*10000", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      // USDJPY mid ~150, backend ships 3.0 pips; the old pane math would
      // render 300.0 from (ask-bid)*10000.
      {
        base: "USD",
        quote: "JPY",
        pair: "USDJPY",
        rate: 150,
        bid: 150.0,
        ask: 150.03,
        spread_pips: 3.0,
        change_pct: 0.4,
        history: [149, 150, 150.5, 150.03],
      },
    ]);
    render(<WCRSPane code="WCRS" />);
    const row = screen.getByRole("table").querySelector("tbody tr")!;
    expect(within(row as HTMLElement).getByText("3.0")).toBeInTheDocument();
    expect(row.textContent).not.toContain("300.0");
  });

  it("falls back to a JPY-aware pip factor when spread_pips is absent", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      {
        base: "USD",
        quote: "JPY",
        pair: "USDJPY",
        rate: 150,
        bid: 150.0,
        ask: 150.03,
        change_pct: null,
      },
      {
        base: "EUR",
        quote: "USD",
        pair: "EURUSD",
        rate: 1.1,
        bid: 1.0999,
        ask: 1.1001,
        change_pct: null,
      },
    ]);
    render(<WCRSPane code="WCRS" />);
    const rows = screen.getByRole("table").querySelectorAll("tbody tr");
    expect(within(rows[0] as HTMLElement).getByText("3.0")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("2.0")).toBeInTheDocument();
  });

  it("names the cross-rate grid for assistive tech", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { base: "USD", quote: "EUR", pair: "USDEUR", rate: 0.9, change_pct: 0.1 },
    ]);
    render(<WCRSPane code="WCRS" />);
    expect(
      screen.getByRole("table", { name: "WCRS cross rates" }),
    ).toBeInTheDocument();
  });

  it("wires the pair cell to FXIP (focused target + route)", () => {
    mockFn.state = "ok";
    mockFn.data = okData([
      { base: "USD", quote: "EUR", pair: "USDEUR", rate: 0.9, change_pct: 0.1 },
    ]);
    render(<WCRSPane code="WCRS" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Open USDEUR in FX Info Portal" }),
    );
    expect(setFocusedTargetSpy).toHaveBeenCalledWith("FXIP", "USDEUR");
  });
});
