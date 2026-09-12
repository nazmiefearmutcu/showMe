/**
 * TCA pane — derived-math + mode-honesty + poll-contract tests (F4 macro lane).
 *
 * Pins:
 *  - per-fill slippage/cost are DERIVED from price/benchmark/notional when the
 *    backend omits them (signed by side), and the KPI ribbon rolls them up;
 *  - degraded payloads show the degraded notice + pill, live payloads do not;
 *  - the visibility poll refetches via `refetch()` with stable params;
 *  - the fills grid carries an ariaLabel.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { TCAPane } from "./TCA";

/* ── useFunction / tick mocks ─────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; warnings?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  if (next.refetch) mockFn.refetch = next.refetch;
}

const mockTick = { current: 0 };
let lastFnArgs: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: mockFn.refetch,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

/** No slippage_bps / cost_usd / summary on purpose — the pane must derive. */
function derivedPayload() {
  return {
    data: {
      data: {
        status: "ok",
        data_mode: "live",
        benchmark: "VWAP",
        rows: [
          {
            order_id: "r1",
            symbol: "BTCUSDT",
            side: "BUY",
            quantity: 10,
            avg_fill_px: 110,
            benchmark_px: 100,
            benchmark_source: "binance",
            filled_at: "2026-09-11T12:00:00Z",
          },
          {
            order_id: "r2",
            symbol: "BTCUSDT",
            side: "SELL",
            quantity: 5,
            avg_fill_px: 90,
            benchmark_px: 100,
            benchmark_source: "binance",
            filled_at: "2026-09-11T12:05:00Z",
          },
        ],
        summary: {},
      },
    },
    sources: ["binance"],
    warnings: [],
    elapsed_ms: 8,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockTick.current = 0;
  lastFnArgs = undefined;
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("TCA pane — derived slippage/cost fallback", () => {
  it("derives signed slippage, cost and roll-ups from price vs benchmark", () => {
    setMockFn({ state: "ok", ...derivedPayload() });
    render(<TCAPane code="TCA" symbol="BTCUSDT" />);
    // BUY 110 vs 100 and SELL 90 vs 100 are both +1000 bp adverse.
    expect(screen.getAllByText("+1000.0 bp").length).toBeGreaterThan(0);
    // cost = 0.1 x 1100 + 0.1 x 450 = $155.00
    expect(screen.getAllByText("$155.00").length).toBeGreaterThan(0);
    expect(screen.getByText(/Per-fill slippage/i)).toBeInTheDocument();
  });
});

describe("TCA pane — mode honesty", () => {
  it("shows the degraded banner + pill for a degraded payload", () => {
    const payload = derivedPayload();
    (payload.data.data as Record<string, unknown>).data_mode = "degraded";
    setMockFn({ state: "ok", ...payload });
    render(<TCAPane code="TCA" symbol="BTCUSDT" />);
    expect(screen.getByText(/Degraded TCA payload/i)).toBeInTheDocument();
    expect(within(screen.getByTestId("tca-mode-pill")).getByText("degraded")).toBeInTheDocument();
    expect(screen.queryByText(/Reference TCA payload/i)).toBeNull();
  });

  it("keeps the live pill clean for a live payload", () => {
    setMockFn({ state: "ok", ...derivedPayload() });
    render(<TCAPane code="TCA" symbol="BTCUSDT" />);
    expect(within(screen.getByTestId("tca-mode-pill")).getByText("live")).toBeInTheDocument();
    expect(screen.queryByText(/Degraded TCA payload/i)).toBeNull();
  });

  it("renders the empty state when the ledger has no fills", () => {
    setMockFn({
      state: "ok",
      data: {
        data: { status: "empty", rows: [], summary: { fill_count: 0 } },
        sources: [],
        warnings: [],
      },
    });
    render(<TCAPane code="TCA" symbol="BTCUSDT" />);
    expect(screen.getByText(/No fills to analyze/i)).toBeInTheDocument();
  });
});

describe("TCA pane — fills grid + visibility poll", () => {
  it("exposes the fills grid with an ariaLabel", () => {
    setMockFn({ state: "ok", ...derivedPayload() });
    render(<TCAPane code="TCA" symbol="BTCUSDT" />);
    fireEvent.click(screen.getByRole("tab", { name: "Fills" }));
    expect(screen.getByLabelText("TCA fills")).toBeInTheDocument();
  });

  it("refetches on a visibility tick but not on mount, params stay tick-free", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...derivedPayload(), refetch });
    const { rerender } = render(<TCAPane code="TCA" symbol="BTCUSDT" />);
    expect(refetch).not.toHaveBeenCalled();
    expect(lastFnArgs?.params).toEqual({ benchmark: "VWAP" });

    mockTick.current = 1;
    rerender(<TCAPane code="TCA" symbol="BTCUSDT" />);
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(lastFnArgs?.params).toEqual({ benchmark: "VWAP" });
  });
});

describe("TCA pane — fills grid sort + keyboard (lane B4)", () => {
  it("defaults to worst-cost fill first and enables keyboard grid navigation", () => {
    const payload = derivedPayload();
    // Reverse the fills so only the built-in sorter can put r1 first.
    const data = payload.data.data as { rows: unknown[] };
    data.rows = [...data.rows].reverse();
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<TCAPane code="TCA" symbol="BTCUSDT" />);
    fireEvent.click(screen.getByRole("tab", { name: "Fills" }));

    const grid = screen.getByRole("grid", { name: "TCA fills" });
    expect(grid).toBeInTheDocument();
    // Roving keyboard cell: the first cell owns the tab stop.
    expect(
      grid.querySelector('td[data-cell="0-0"]')?.getAttribute("tabindex"),
    ).toBe("0");

    // Derived costs: r1 = $110.00 (10 @ +1000bp) > r2 = $45.00 — cost
    // descending keeps the worst fill first.
    const rowsBefore = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsBefore[0]?.textContent).toContain("$110.00");
    expect(rowsBefore.at(-1)?.textContent).toContain("$45.00");

    // Activating the sort cycles desc -> none: reversed fixture order returns.
    fireEvent.click(container.querySelector('th[aria-sort="descending"]')!);
    const rowsAfter = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsAfter[0]?.textContent).toContain("$45.00");
  });
});
