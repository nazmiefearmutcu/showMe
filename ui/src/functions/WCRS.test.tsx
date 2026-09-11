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
