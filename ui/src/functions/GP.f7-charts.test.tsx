/**
 * F7 — GP chart fixes (audit A6 / GP subsection).
 *
 * Pins the fixes shipped in the charts fix lane:
 *   1. `data.indicators` is emitted by the GP alias again → the INDICATORS
 *      legend and the chart overlay series actually render.
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
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { GPPane } from "./GP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const gpSourceRaw = readFileSync(resolve(__dirname, "GP.tsx"), "utf-8");

/* ── lightweight-charts spy ─────────────────────────────────────────── */

interface SeriesStub {
  setData: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  __label?: string;
}
interface AddedEntry {
  constructor: unknown;
  options: Record<string, unknown>;
  series: SeriesStub;
}
interface ChartStub {
  addSeries: ReturnType<typeof vi.fn>;
  removeSeries: ReturnType<typeof vi.fn>;
  subscribeCrosshairMove: ReturnType<typeof vi.fn>;
  priceScale: ReturnType<typeof vi.fn>;
  timeScale: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  __series: SeriesStub[];
  __added: AddedEntry[];
}

const chartInstances: ChartStub[] = [];

vi.mock("lightweight-charts", () => {
  class LineSeries {}
  class CandlestickSeries {}
  class HistogramSeries {}
  class AreaSeries {}
  const createChart = vi.fn(() => {
    const series: SeriesStub[] = [];
    const added: AddedEntry[] = [];
    const makeSeries = (): SeriesStub => ({
      setData: vi.fn(),
      update: vi.fn(),
      applyOptions: vi.fn(),
    });
    const instance: ChartStub = {
      addSeries: vi.fn(
        (constructor: unknown, options: Record<string, unknown>) => {
          const stub = makeSeries();
          series.push(stub);
          added.push({ constructor, options, series: stub });
          return stub;
        },
      ),
      removeSeries: vi.fn(),
      subscribeCrosshairMove: vi.fn(),
      priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
      timeScale: vi.fn(() => ({
        fitContent: vi.fn(),
        setVisibleLogicalRange: vi.fn(),
      })),
      remove: vi.fn(),
      applyOptions: vi.fn(),
      resize: vi.fn(),
      __series: series,
      __added: added,
    };
    chartInstances.push(instance);
    return instance;
  });
  return { createChart, LineSeries, CandlestickSeries, HistogramSeries, AreaSeries };
});

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
  chartInstances.length = 0;
  mockQuoteState.transportState = "idle";
  mockState.payload = gpPayload({});
});

afterEach(() => {
  cleanup();
});

/* ── tests ──────────────────────────────────────────────────────────── */

describe("F7 GP — payload indicators reach the chart", () => {
  it("renders the INDICATORS legend from data.indicators", () => {
    mockState.payload = gpPayload({
      indicators: {
        sma_20: [{ time: 1, value: 100 }],
        bb_upper: [{ time: 1, value: 105 }],
      },
    });
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    expect(container.textContent).toContain("SMA_20");
    expect(container.textContent).toContain("BB_UPPER");
  });

  it("draws the overlay series from data.indicators", () => {
    mockState.payload = gpPayload({
      indicators: {
        sma_20: [
          { time: 1, value: 100 },
          { time: 2, value: 101 },
        ],
        ema_20: [{ time: 1, value: 99 }],
      },
    });
    render(<GPPane code="GP" symbol="AAPL" />);
    const chart = chartInstances[0];
    const sma = chart.__added.find((entry) => entry.series.__label === "sma_20");
    const ema = chart.__added.find((entry) => entry.series.__label === "ema_20");
    expect(sma).toBeDefined();
    expect(ema).toBeDefined();
    expect(sma?.series.setData).toHaveBeenCalled();
    expect(ema?.series.setData).toHaveBeenCalled();
  });

  it("re-draws overlays after a chart-style rebuild", () => {
    mockState.payload = gpPayload({
      indicators: { sma_20: [{ time: 1, value: 100 }, { time: 2, value: 101 }] },
    });
    render(<GPPane code="GP" symbol="AAPL" />);
    expect(chartInstances).toHaveLength(1);
    // Candle → Line is the legitimate rebuild path (different series type).
    fireEvent.click(screen.getByRole("button", { name: "Line" }));
    expect(chartInstances).toHaveLength(2);
    const rebuilt = chartInstances[1];
    const sma = rebuilt.__added.find((entry) => entry.series.__label === "sma_20");
    expect(sma).toBeDefined();
    expect(sma?.series.setData).toHaveBeenCalled();
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
