/**
 * F7 — GP chart fixes (audit A6 / GP subsection).
 *
 * Pins the fixes shipped in the charts fix lane that still hold after the
 * pane migrated to the in-house chart engine:
 *   1. The payload's `data.indicators` bundle no longer renders as an
 *      overlay + INDICATORS legend (the engine owns indicator drawing), but
 *      receiving it must not break the pane.
 *   2. The never-existing `cached` footer pill is replaced by an honest
 *      deep/windowed history chip.
 *   3. "52w high/low" only claims 52 weeks when the provider meta supplied
 *      real 52-week levels; otherwise the rail labels show honest
 *      "Range high/low".
 *   4. Client "ATR(14)" is TRUE ATR (Wilder-smoothed true range), aligned
 *      with HP and the backend TECH definition.
 *   5. Sub-cent absolute changes render with adaptive precision instead of
 *      `toFixed(2)` collapsing to "+0.00".
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { GPPane } from "./GP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const gpSourceRaw = readFileSync(resolve(__dirname, "GP.tsx"), "utf-8");

/* ── chart-engine stub ──────────────────────────────────────────────── */
// The engine fetches /api/bars and paints a canvas — stub it out.
vi.mock("@/chart/Chart", () => ({
  Chart: () => <div data-testid="chart-engine" />,
  default: () => <div data-testid="chart-engine" />,
}));

class FakeResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;

/* ── hook mocks ─────────────────────────────────────────────────────── */

const mockQuoteState = {
  transportState: "idle" as TransportState,
  lastTick: null as { price: number; ts: number } | null,
  lastTickAt: null as number | null,
  snapshot: null as { price: number } | null,
  freshnessMs: null as number | null,
  stale: false,
  refreshing: false,
};

vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return {
    ...actual,
    useLiveQuote: () => mockQuoteState,
    useLiveQuotes: () => ({ snapshots: {}, ticks: {} }),
  };
});

const mockState = vi.hoisted(() => ({
  payload: {} as unknown,
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "ok",
    data: mockState.payload,
    error: null,
    refetch: vi.fn(),
  }),
}));

/* ── fixtures ───────────────────────────────────────────────────────── */

function makeRows(count: number) {
  return Array.from({ length: count }, (_, i) => {
    const close = 100 + i * 0.5;
    return {
      time: `2026-01-${String((i % 28) + 1).padStart(2, "0")}`,
      open: close - 0.25,
      high: close + 1,
      low: close - 1,
      close,
      volume: 1_000 + i,
    };
  });
}

/** Flat closes with wide high/low: |Δclose| ATR = 0, true ATR = 20. */
function flatRangeRows(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    time: `2026-01-${String((i % 28) + 1).padStart(2, "0")}`,
    open: 100,
    high: 110,
    low: 90,
    close: 100,
    volume: 10,
  }));
}

function gpPayload(data: Record<string, unknown>) {
  return { data: { ohlcv: makeRows(30), ...data }, sources: ["yahoo_chart"] };
}

beforeEach(() => {
  mockQuoteState.transportState = "idle";
  mockState.payload = gpPayload({});
});

afterEach(() => {
  cleanup();
});

/* ── tests ──────────────────────────────────────────────────────────── */

describe("F7 GP — payload indicators after the engine migration", () => {
  it("does not resurface payload indicators as the removed chip legend", () => {
    mockState.payload = gpPayload({
      indicators: {
        sma_20: [{ time: 1, value: 100 }],
        bb_upper: [{ time: 1, value: 105 }],
      },
    });
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    expect(screen.getByTestId("chart-engine")).toBeInTheDocument();
    expect(container.textContent).not.toContain("SMA_20");
    expect(container.textContent).not.toContain("BB_UPPER");
  });

  it("no longer reads the never-existing `cached` field", () => {
    expect(gpSourceRaw).not.toMatch(/cached/);
  });
});

describe("F7 GP — true ATR(14)", () => {
  it("uses high/low true range, not mean |Δclose|", () => {
    mockState.payload = { data: { ohlcv: flatRangeRows(16) }, sources: ["yahoo_chart"] };
    render(<GPPane code="GP" symbol="AAPL" />);
    const label = screen.getByText("ATR(14)");
    // TR = max(110−90, |110−100|, |90−100|) = 20 on every bar → ATR = 20.00.
    // The pre-fix mean |Δclose| implementation rendered 0.00 here.
    expect(label.parentElement?.textContent).toContain("20.00");
  });
});

describe("F7 GP — honest labels + formatting", () => {
  it("claims '52w high/low' only when provider meta supplied real 52w levels", () => {
    mockState.payload = gpPayload({
      fifty_two_week_high: 260.1,
      fifty_two_week_low: 164.08,
    });
    const first = render(<GPPane code="GP" symbol="AAPL" />);
    expect(first.container.textContent).toContain("52w high");
    expect(first.container.textContent).toContain("52w low");
    expect(first.container.textContent).toContain("260.10");
    cleanup();

    mockState.payload = gpPayload({});
    const second = render(<GPPane code="GP" symbol="AAPL" />);
    expect(second.container.textContent).not.toContain("52w high");
    expect(second.container.textContent).toContain("Range high");
    expect(second.container.textContent).toContain("Range low");
  });

  it("reports deep vs windowed history instead of the fake cache pill", () => {
    mockState.payload = gpPayload({ deep_history: true });
    const first = render(<GPPane code="GP" symbol="AAPL" />);
    expect(first.container.textContent).toContain("deep");
    expect(first.container.textContent).not.toContain("cache");
    cleanup();

    mockState.payload = gpPayload({});
    const second = render(<GPPane code="GP" symbol="AAPL" />);
    expect(second.container.textContent).toContain("windowed");
  });

  it("formats sub-cent absolute changes with adaptive precision", () => {
    mockState.payload = {
      data: {
        ohlcv: [
          { time: "2026-01-01", open: 0.0011, high: 0.0012, low: 0.001, close: 0.0011, volume: 100 },
          { time: "2026-01-02", open: 0.0011, high: 0.0011, low: 0.0005, close: 0.0005, volume: 100 },
        ],
      },
      sources: ["yahoo_chart"],
    };
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    // Δ = −0.0006 must keep its digits; toFixed(2) rendered "-0.00".
    expect(container.textContent).toContain("-0.000600");
  });
});
