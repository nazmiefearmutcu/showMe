/**
 * Pins the mount-once architecture for `SeriesChart` / `LightweightSeriesChart`.
 *
 * Previous implementation tore the chart down (`chart.remove()` +
 * `createChart()`) on every `series` / `delta` / `intradayTime` / `palette`
 * change, wiping the user's wheel/pinch zoom. The refactor mirrors HP/GP:
 *
 *   1. Mount effect creates the chart ONCE for a given (kind · paletteKey).
 *   2. Data refresh routes through `setData` on existing series refs.
 *   3. A dedicated first-seed-focus effect calls `setVisibleLogicalRange`
 *      exactly once per chart instance. Subsequent refreshes leave the
 *      viewport alone so the user's manual zoom survives.
 *   4. `series.kind` swap is the ONLY data-driven path that rebuilds (the
 *      series type itself changes).
 *   5. `intradayTime` flips toggle `timeScale.timeVisible` via
 *      `chart.applyOptions(...)` — no rebuild.
 *   6. Line color sign flips toggle via `series.applyOptions({ color })` —
 *      no rebuild.
 */
import type { Time } from "lightweight-charts";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { SeriesChart } from "./charts";
import type { ChartPoint, ChartSeries } from "./_types";

// ---- lightweight-charts spy --------------------------------------------
// Each `createChart` call returns a fresh stub so we can count instances and
// assert that `setData` / `applyOptions` happen on the same instance across
// refreshes.
interface SeriesStub {
  setData: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
}
interface TimeScaleStub {
  fitContent: ReturnType<typeof vi.fn>;
  setVisibleLogicalRange: ReturnType<typeof vi.fn>;
}
interface ChartStub {
  addCandlestickSeries: ReturnType<typeof vi.fn<(...args: unknown[]) => SeriesStub>>;
  addLineSeries: ReturnType<typeof vi.fn<(...args: unknown[]) => SeriesStub>>;
  addAreaSeries: ReturnType<typeof vi.fn<(...args: unknown[]) => SeriesStub>>;
  addHistogramSeries: ReturnType<typeof vi.fn<(...args: unknown[]) => SeriesStub>>;
  removeSeries: ReturnType<typeof vi.fn>;
  priceScale: ReturnType<typeof vi.fn>;
  timeScale: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  __series: SeriesStub[];
  __timeScale: TimeScaleStub;
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
    // Stable per-chart timeScale stub so `setVisibleLogicalRange` calls
    // accumulate across the chart's lifetime — without this each
    // `chart.timeScale()` call returned a fresh spy, breaking cumulative
    // assertions.
    const timeScaleStub: TimeScaleStub = {
      fitContent: vi.fn(),
      setVisibleLogicalRange: vi.fn(),
    };
    const instance: ChartStub = {
      addCandlestickSeries: vi.fn(() => track(makeSeries())),
      addLineSeries: vi.fn(() => track(makeSeries())),
      addAreaSeries: vi.fn(() => track(makeSeries())),
      addHistogramSeries: vi.fn(() => track(makeSeries())),
      removeSeries: vi.fn(),
      priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
      timeScale: vi.fn(() => timeScaleStub),
      remove: vi.fn(),
      applyOptions: vi.fn(),
      resize: vi.fn(),
      __series: series,
      __timeScale: timeScaleStub,
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

afterEach(() => {
  chartInstances.length = 0;
  cleanup();
});

function makePoint(
  i: number,
  close: number,
  options: { time?: Time; xLabel?: string } = {},
): ChartPoint {
  const day = String(15 + i).padStart(2, "0");
  return {
    xLabel: options.xLabel ?? `2026-05-${day}`,
    y: close,
    time: options.time ?? (`2026-05-${day}` as Time),
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    volume: 1_000,
  };
}

function lineSeries(closes: number[]): ChartSeries {
  return {
    kind: "line",
    title: "Test line",
    rows: [],
    xKey: "date",
    labelKey: null,
    yKey: "value",
    points: closes.map((c, i) => makePoint(i, c)),
  };
}

function ohlcSeries(closes: number[]): ChartSeries {
  return {
    kind: "ohlc",
    title: "Test ohlc",
    rows: [],
    xKey: "date",
    labelKey: null,
    yKey: "close",
    points: closes.map((c, i) => makePoint(i, c)),
  };
}

describe("SeriesChart — chart instance lifecycle", () => {
  it("creates the chart once and reuses it across line-series data refreshes", () => {
    const initial = lineSeries([100, 101, 102]);
    const refreshed = lineSeries([100, 101, 102, 103]);
    const refreshedAgain = lineSeries([100, 101, 102, 103, 104]);

    const { rerender } = render(
      <SeriesChart chartId="STUB" series={initial} />,
    );
    expect(chartInstances).toHaveLength(1);
    const chart = chartInstances[0];
    expect(chart.addLineSeries).toHaveBeenCalledTimes(1);
    expect(chart.remove).not.toHaveBeenCalled();
    const lineSeriesStub = chart.__series[0];
    expect(lineSeriesStub.setData).toHaveBeenCalledTimes(1);

    act(() => {
      rerender(<SeriesChart chartId="STUB" series={refreshed} />);
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    expect(lineSeriesStub.setData).toHaveBeenCalledTimes(2);

    act(() => {
      rerender(<SeriesChart chartId="STUB" series={refreshedAgain} />);
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    expect(lineSeriesStub.setData).toHaveBeenCalledTimes(3);
    // Final setData call carries the largest row set.
    const lastSet = lineSeriesStub.setData.mock.calls.at(-1)?.[0] as unknown[];
    expect(lastSet).toHaveLength(refreshedAgain.points.length);
  });

  it("creates the chart once across ohlc-series data refreshes", () => {
    const initial = ohlcSeries([100, 101, 102]);
    const refreshed = ohlcSeries([100, 101, 102, 103]);
    const { rerender } = render(
      <SeriesChart chartId="STUB" series={initial} />,
    );
    expect(chartInstances).toHaveLength(1);
    const chart = chartInstances[0];
    expect(chart.addCandlestickSeries).toHaveBeenCalledTimes(1);
    expect(chart.addHistogramSeries).toHaveBeenCalledTimes(1);
    const candleStub = chart.__series[0];
    const volStub = chart.__series[1];
    expect(candleStub.setData).toHaveBeenCalledTimes(1);
    expect(volStub.setData).toHaveBeenCalledTimes(1);

    act(() => {
      rerender(<SeriesChart chartId="STUB" series={refreshed} />);
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    expect(candleStub.setData).toHaveBeenCalledTimes(2);
    expect(volStub.setData).toHaveBeenCalledTimes(2);
  });
});

describe("SeriesChart — viewport preservation across data refreshes", () => {
  // The bug the refactor closes: the old single-`useEffect` rebuilt the
  // chart on every series prop change, which in turn re-called
  // `focusLatestBars` → `setVisibleLogicalRange`. The contract:
  // `setVisibleLogicalRange` fires exactly once for a given chart instance,
  // and only for the first-seed framing.
  it("calls setVisibleLogicalRange once across multiple series prop changes", () => {
    const a = lineSeries([100, 101, 102]);
    const b = lineSeries([100, 101, 102, 103]);
    const c = lineSeries([100, 101, 102, 103, 104]);

    const { rerender } = render(<SeriesChart chartId="STUB" series={a} />);
    const chart = chartInstances[0];
    expect(chart).toBeDefined();
    expect(chart.__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    act(() => {
      rerender(<SeriesChart chartId="STUB" series={b} />);
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    act(() => {
      rerender(<SeriesChart chartId="STUB" series={c} />);
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);
  });
});

describe("SeriesChart — kind swap is the only rebuild path", () => {
  it("rebuilds the chart when series.kind flips line ↔ ohlc", () => {
    const line = lineSeries([100, 101, 102]);
    const ohlc = ohlcSeries([100, 101, 102]);

    const { rerender } = render(<SeriesChart chartId="STUB" series={line} />);
    expect(chartInstances).toHaveLength(1);
    expect(chartInstances[0].__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    act(() => {
      rerender(<SeriesChart chartId="STUB" series={ohlc} />);
    });
    // New instance — old chart was removed, new chart re-frames once.
    expect(chartInstances).toHaveLength(2);
    expect(chartInstances[0].remove).toHaveBeenCalledTimes(1);
    expect(chartInstances[1].__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    // Refresh on the new instance — viewport still untouched.
    const ohlcRefreshed = ohlcSeries([100, 101, 102, 103]);
    act(() => {
      rerender(<SeriesChart chartId="STUB" series={ohlcRefreshed} />);
    });
    expect(chartInstances).toHaveLength(2);
    expect(chartInstances[1].__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);
  });
});

describe("SeriesChart — intradayTime toggles via applyOptions, never rebuild", () => {
  it("calls chart.applyOptions when intraday time presence flips", () => {
    const dailySeries: ChartSeries = lineSeries([100, 101, 102]);
    const intradaySeries: ChartSeries = {
      ...dailySeries,
      points: [
        makePoint(0, 100, { time: 1_700_000_000 as unknown as Time }),
        makePoint(1, 101, { time: 1_700_003_600 as unknown as Time }),
        makePoint(2, 102, { time: 1_700_007_200 as unknown as Time }),
      ],
    };

    const { rerender } = render(
      <SeriesChart chartId="STUB" series={dailySeries} />,
    );
    const chart = chartInstances[0];
    // Mount-time applyOptions call from the dedicated intradayTime effect.
    const mountApplyOptionCalls = chart.applyOptions.mock.calls.length;
    expect(mountApplyOptionCalls).toBeGreaterThanOrEqual(1);

    act(() => {
      rerender(<SeriesChart chartId="STUB" series={intradaySeries} />);
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    // intradayTime flipped false → true, applyOptions called again with the
    // new timeScale option, NOT a rebuild.
    expect(chart.applyOptions.mock.calls.length).toBeGreaterThan(
      mountApplyOptionCalls,
    );
    const lastApply = chart.applyOptions.mock.calls.at(-1)?.[0] as {
      timeScale?: { timeVisible?: boolean };
    };
    expect(lastApply?.timeScale?.timeVisible).toBe(true);
  });
});

describe("SeriesChart — line color sign flip applies via applyOptions", () => {
  it("re-colors the line via applyOptions when delta sign changes, no rebuild", () => {
    const ascending = lineSeries([100, 101, 102, 103]);
    const descending = lineSeries([200, 180, 160, 140]);

    const { rerender } = render(
      <SeriesChart chartId="STUB" series={ascending} />,
    );
    const chart = chartInstances[0];
    const lineSeriesStub = chart.__series[0];
    // Initial applyOptions call from the data-refresh effect (positive delta).
    const before = lineSeriesStub.applyOptions.mock.calls.length;
    expect(before).toBeGreaterThanOrEqual(1);

    act(() => {
      rerender(<SeriesChart chartId="STUB" series={descending} />);
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    // Delta flipped negative → another applyOptions call with the new color.
    expect(lineSeriesStub.applyOptions.mock.calls.length).toBeGreaterThan(before);
  });
});
