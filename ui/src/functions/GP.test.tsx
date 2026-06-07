/**
 * S03-R regressions for GP / TECH.
 *
 * What we lock down:
 *   1. ChartView creates the chart ONCE for a given style/palette — refreshing
 *      candles or indicators must not call `chart.remove()` + `createChart()`
 *      (the bug that killed scroll/zoom state and live ticks).
 *   2. Historical refresh updates the existing series via `setData()`.
 *   3. A live tick updates the current bar via `series.update()` without
 *      touching the chart instance.
 *   4. The source no longer ships the `buildMockNews` fabricator and none of
 *      the canned fake headlines leak into the file.
 *   5. Compare and Export toolbar controls — Round-3 audit found them visible
 *      but non-functional. They must now be aria-disabled with a `title`.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { ChartView } from "./GP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const gpSourceRaw = readFileSync(resolve(__dirname, "GP.tsx"), "utf-8");

// ---- lightweight-charts spy --------------------------------------------
// Each call to `createChart` returns a fresh stub so we can count
// instantiations and assert that `setData` / `update` happen on the same
// instance across refreshes.
interface SeriesStub {
  setData: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  __label?: string;
}
interface ChartStub {
  addCandlestickSeries: ReturnType<typeof vi.fn<(...args: unknown[]) => SeriesStub>>;
  addLineSeries: ReturnType<typeof vi.fn<(...args: unknown[]) => SeriesStub>>;
  addAreaSeries: ReturnType<typeof vi.fn<(...args: unknown[]) => SeriesStub>>;
  addHistogramSeries: ReturnType<typeof vi.fn<(...args: unknown[]) => SeriesStub>>;
  removeSeries: ReturnType<typeof vi.fn>;
  subscribeCrosshairMove: ReturnType<typeof vi.fn>;
  priceScale: ReturnType<typeof vi.fn>;
  timeScale: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  __series: SeriesStub[];
  addSeries: ReturnType<typeof vi.fn>;
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

// jsdom ships no ResizeObserver — stub it so the mount effect doesn't throw.
class FakeResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;

function makeCandle(time: string, close: number) {
  return {
    ts: time,
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    volume: 1_000,
  };
}

afterEachReset();

function afterEachReset() {
  // Vitest globals via @testing-library/react teardown.
  // We just rely on cleanup() inside each test where needed.
}

describe("GP / ChartView — chart instance lifecycle", () => {
  it("creates the chart once and reuses it across candle refreshes", () => {
    chartInstances.length = 0;
    const initial = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    const updated = [...initial, makeCandle("2026-05-17", 103)];
    const { rerender } = render(
      <ChartView
        chartId="GP"
        candles={initial}
        interval="1d"
        chartStyle="candle"
        onCrosshair={() => undefined}
      />,
    );
    expect(chartInstances).toHaveLength(1);
    const chart = chartInstances[0];
    expect(chart.remove).not.toHaveBeenCalled();
    expect(chart.addCandlestickSeries).toHaveBeenCalledTimes(1);

    act(() => {
      rerender(
        <ChartView
          chartId="GP"
          candles={updated}
          interval="1d"
          chartStyle="candle"
          onCrosshair={() => undefined}
        />,
      );
    });

    // Same chart instance, still no remove(). The candle + volume series
    // should each have had setData called again with the refreshed data.
    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    const candleSeries = chart.__series[0];
    expect(candleSeries.setData).toHaveBeenCalledTimes(2);
    // Final call should reflect the updated candle count.
    const lastCall = candleSeries.setData.mock.calls.at(-1)?.[0] as unknown[];
    expect(lastCall).toHaveLength(updated.length);
    cleanup();
  });

  it("changing chartStyle DOES rebuild the chart (intentional)", () => {
    chartInstances.length = 0;
    const candles = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    const { rerender } = render(
      <ChartView
        chartId="GP"
        candles={candles}
        interval="1d"
        chartStyle="candle"
        onCrosshair={() => undefined}
      />,
    );
    expect(chartInstances).toHaveLength(1);

    act(() => {
      rerender(
        <ChartView
          chartId="GP"
          candles={candles}
          interval="1d"
          chartStyle="line"
          onCrosshair={() => undefined}
        />,
      );
    });
    // Style change is the legitimate trigger to swap series → new instance.
    expect(chartInstances).toHaveLength(2);
    expect(chartInstances[0].remove).toHaveBeenCalledTimes(1);
    cleanup();
  });

  it("changing only the onCrosshair callback identity does NOT rebuild", () => {
    chartInstances.length = 0;
    const candles = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    const { rerender } = render(
      <ChartView
        chartId="GP"
        candles={candles}
        interval="1d"
        chartStyle="candle"
        onCrosshair={() => undefined}
      />,
    );
    expect(chartInstances).toHaveLength(1);
    act(() => {
      rerender(
        <ChartView
          chartId="GP"
          candles={candles}
          interval="1d"
          chartStyle="candle"
          onCrosshair={() => undefined /* new identity each render */}
        />,
      );
    });
    expect(chartInstances).toHaveLength(1);
    cleanup();
  });

  it("applies a live tick via series.update() without rebuilding", () => {
    chartInstances.length = 0;
    const candles = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    const { rerender } = render(
      <ChartView
        chartId="GP"
        candles={candles}
        interval="1d"
        chartStyle="candle"
        onCrosshair={() => undefined}
        liveTick={null}
      />,
    );
    const chart = chartInstances[0];
    const candleSeries = chart.__series[0];
    expect(candleSeries.update).not.toHaveBeenCalled();

    act(() => {
      rerender(
        <ChartView
          chartId="GP"
          candles={candles}
          interval="1d"
          chartStyle="candle"
          onCrosshair={() => undefined}
          liveTick={{ price: 105, ts: Date.now() }}
        />,
      );
    });

    expect(chartInstances).toHaveLength(1);
    expect(candleSeries.update).toHaveBeenCalledTimes(1);
    const updateArg = candleSeries.update.mock.calls[0]?.[0] as {
      close: number;
      high: number;
      low: number;
    };
    expect(updateArg.close).toBe(105);
    // High must expand to cover the new tick.
    expect(updateArg.high).toBeGreaterThanOrEqual(105);
    cleanup();
  });
});

describe("GP source — fabricated content guards", () => {
  it("does not export or define buildMockNews", () => {
    expect(gpSourceRaw).not.toMatch(/function\s+buildMockNews/);
    expect(gpSourceRaw).not.toMatch(/buildMockNews\s*\(/);
  });

  it("does not contain the canned fake headline strings", () => {
    // These three sentences were the entire output of the removed
    // `buildMockNews` helper. Any reintroduction must fail this test.
    expect(gpSourceRaw).not.toContain("momentum builds as MA cross fires");
    expect(gpSourceRaw).not.toContain("Technical traders eye");
    expect(gpSourceRaw).not.toContain("closes in on key Fib retracement");
  });

  it("Compare and Export toolbar controls are aria-disabled", () => {
    // Lightweight string assertions — these JSX attributes must travel
    // together with the test-ids that downstream a11y harness checks expect.
    expect(gpSourceRaw).toMatch(
      /aria-disabled="true"[\s\S]{0,400}data-testid="gp-compare-button"/,
    );
    expect(gpSourceRaw).toMatch(
      /aria-disabled="true"[\s\S]{0,400}data-testid="gp-export-button"/,
    );
    // Both should carry a title so hover explains why they're inert.
    expect(gpSourceRaw).toMatch(/title="Compare overlay is not wired yet"/);
    expect(gpSourceRaw).toMatch(/title="Chart export is not wired yet"/);
  });
});
