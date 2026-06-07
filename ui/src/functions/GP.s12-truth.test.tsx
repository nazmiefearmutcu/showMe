/**
 * S12 GP truth — header/footer must reflect the live tick when the
 * transport is actually live, not stay frozen on the candle-derived
 * historical close.
 *
 * Pre-S12 the price/change in the GP header strip rendered straight
 * from `lastClose` (the close of the most recent historical candle),
 * which meant the chart series ticked via `series.update()` while the
 * displayed number stayed stale until the next history refetch. This
 * test pins the new contract:
 *
 *  1. When `useLiveQuote.transportState === "live"` and a tick is
 *     present, the header price element exposes
 *     `data-testid="gp-display-price"` with `data-live="1"` and the
 *     formatted live price.
 *  2. When transport is idle / no tick has landed, the header falls
 *     back to the historical `lastClose` and reports `data-live="0"`.
 *  3. A live tick still routes through `series.update()` on the
 *     existing chart instance — no remount.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { GPPane } from "./GP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const gpSourceRaw = readFileSync(resolve(__dirname, "GP.tsx"), "utf-8");

/* ── lightweight-charts spy ────────────────────────────────────────── */

interface SeriesStub {
  setData: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
}
interface ChartStub {
  addCandlestickSeries: any;
  addLineSeries: any;
  addAreaSeries: any;
  addHistogramSeries: any;
  removeSeries: any;
  subscribeCrosshairMove: any;
  priceScale: any;
  timeScale: any;
  remove: any;
  applyOptions: any;
  resize: any;
  takeScreenshot: any;
  __series: SeriesStub[];
  addSeries: any;
}

const chartInstances: ChartStub[] = [];

function makeSeries(): SeriesStub {
  return {
    setData: vi.fn(),
    update: vi.fn(),
    applyOptions: vi.fn(),
  };
}

vi.mock("lightweight-charts", () => {
  class LineSeries {}
  class CandlestickSeries {}
  class HistogramSeries {}
  class AreaSeries {}
  const createChart = vi.fn(() => {
    const series: SeriesStub[] = [];
    const track = (s: SeriesStub) => {
      series.push(s);
      return s;
    };
    const instance: ChartStub = {
      addCandlestickSeries: vi.fn(() => track(makeSeries())),
      addLineSeries: vi.fn(() => track(makeSeries())),
      addAreaSeries: vi.fn(() => track(makeSeries())),
      addHistogramSeries: vi.fn(() => track(makeSeries())),
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
      takeScreenshot: vi.fn(() => document.createElement("canvas")),
      __series: series,
      addSeries: vi.fn((constructor, options) => {
        if (constructor === CandlestickSeries) return instance.addCandlestickSeries(options);
        if (constructor === LineSeries) return instance.addLineSeries(options);
        if (constructor === HistogramSeries) return instance.addHistogramSeries(options);
        if (constructor === AreaSeries) return instance.addAreaSeries(options);
        return track(makeSeries());
      }),
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

/* ── hook mocks ────────────────────────────────────────────────────── */

interface MockLiveQuoteState {
  transportState: TransportState;
  lastTick: { price: number; ts: number } | null;
  lastTickAt: number | null;
  snapshot: { price: number } | null;
  freshnessMs: number | null;
  stale: boolean;
  refreshing: boolean;
}

const mockQuoteState: MockLiveQuoteState = {
  transportState: "idle",
  lastTick: null,
  lastTickAt: null,
  snapshot: null,
  freshnessMs: null,
  stale: false,
  refreshing: false,
};

function resetMockQuoteState() {
  mockQuoteState.transportState = "idle";
  mockQuoteState.lastTick = null;
  mockQuoteState.lastTickAt = null;
  mockQuoteState.snapshot = null;
  mockQuoteState.freshnessMs = null;
  mockQuoteState.stale = false;
  mockQuoteState.refreshing = false;
}

vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return {
    ...actual,
    useLiveQuote: () => mockQuoteState,
    useLiveQuotes: () => ({ snapshots: {}, ticks: {} }),
  };
});

const baseGpData = {
  data: {
    ohlcv: [
      { time: "2026-05-18", open: 100, high: 102, low: 99, close: 101, volume: 100_000 },
      { time: "2026-05-19", open: 101, high: 104, low: 100, close: 103, volume: 120_000 },
      { time: "2026-05-20", open: 103, high: 105, low: 102, close: 104.25, volume: 90_000 },
    ],
  },
  sources: ["yfinance"],
};

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "ok",
    data: baseGpData,
    error: null,
    refetch: vi.fn(),
  }),
}));

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  chartInstances.length = 0;
  resetMockQuoteState();
});
afterEach(() => {
  cleanup();
});

describe("S12 GP truth — header reflects live tick", () => {
  it("falls back to historical lastClose when transport is idle (data-live=0)", () => {
    mockQuoteState.transportState = "idle";
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    const priceEl = container.querySelector('[data-testid="gp-display-price"]');
    expect(priceEl).not.toBeNull();
    expect(priceEl?.getAttribute("data-live")).toBe("0");
    // historical lastClose from baseGpData = 104.25 → "104.25"
    expect(priceEl?.textContent).toMatch(/104\.25/);
  });

  it("renders the live tick when transport is 'live' (data-live=1)", () => {
    mockQuoteState.transportState = "live";
    mockQuoteState.lastTick = { price: 108.6, ts: Date.now() };
    mockQuoteState.lastTickAt = Date.now();
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    const priceEl = container.querySelector('[data-testid="gp-display-price"]');
    expect(priceEl?.getAttribute("data-live")).toBe("1");
    expect(priceEl?.textContent).toMatch(/108\.6/);
  });

  it("does NOT promote a stale snapshot price to live tick (data-live=0 when transport != live)", () => {
    // Snapshot present but transport hasn't reached "live" — header
    // must show the historical lastClose, not the snapshot price.
    mockQuoteState.transportState = "connecting";
    mockQuoteState.snapshot = { price: 999.99 };
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    const priceEl = container.querySelector('[data-testid="gp-display-price"]');
    expect(priceEl?.getAttribute("data-live")).toBe("0");
    expect(priceEl?.textContent).toMatch(/104\.25/);
  });

  it("source guards a minimum chart height (>= 240px) so the chart remains dominant", () => {
    const minHeightMatches = Array.from(
      gpSourceRaw.matchAll(/minHeight\s*=\s*\{(\d+)\}/g),
    ).map((m) => Number(m[1]));
    expect(minHeightMatches.length).toBeGreaterThan(0);
    expect(minHeightMatches[0]).toBeGreaterThanOrEqual(240);
    expect(gpSourceRaw).toMatch(/defaultHeight=\{\{[^}]*min:\s*(2[4-9]\d|[3-9]\d{2,})/);
  });

  it("threads a live tick into series.update() without remounting the chart", () => {
    const { rerender } = render(<GPPane code="GP" symbol="AAPL" />);
    const firstInstance = chartInstances[0];
    expect(firstInstance).toBeDefined();
    const candleSeries = firstInstance.__series[0];
    expect(candleSeries.update).not.toHaveBeenCalled();

    const tickTs = Date.now();
    act(() => {
      mockQuoteState.transportState = "live";
      mockQuoteState.lastTick = { price: 109.5, ts: tickTs };
      mockQuoteState.lastTickAt = tickTs;
    });
    rerender(<GPPane code="GP" symbol="AAPL" />);
    expect(chartInstances.length).toBe(1);
    expect(firstInstance.remove).not.toHaveBeenCalled();
    expect(candleSeries.update).toHaveBeenCalled();
    const lastCall = candleSeries.update.mock.calls.at(-1);
    expect(lastCall?.[0]?.close ?? lastCall?.[0]?.value).toBe(109.5);
  });
});
