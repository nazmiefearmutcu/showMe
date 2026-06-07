/**
 * S03-H regressions for HP / PriceChart.
 *
 * Locks the following invariants that previous rounds (notably S03-R for GP)
 * established for chart panes:
 *
 *   1. PriceChart creates the chart instance ONCE for a given
 *      (chartStyle · compareMode · interval · palette) combination. A normal
 *      candle/history refresh must NOT call `chart.remove()` +
 *      `createChart()` — the bug that wiped scroll/zoom/live state.
 *   2. Historical refresh routes through `setData()` on the existing series
 *      references.
 *   3. A `liveTick` prop applies the current bar via `series.update()`
 *      without touching the chart instance.
 *   4. Switching `chartStyle` (candle ↔ line ↔ area) is the one path that
 *      DOES legitimately rebuild — the old chart is removed and a new one
 *      is constructed exactly once.
 *   5. Changing only the `onCrosshair` callback identity does NOT rebuild.
 *   6. `buildMockNews` and its canned headlines are gone; the NEWS rail
 *      ships an honest "not wired" empty state instead.
 *   7. HP's Compare overlay and Export PNG/CSV controls are PRESERVED as
 *      real, wired behavior — they are not turned into the GP-style
 *      aria-disabled placeholders.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import type { IChartApi } from "lightweight-charts";
import { PriceChart, type HPLiveTick } from "./HP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const hpSourceRaw = readFileSync(resolve(__dirname, "HP.tsx"), "utf-8");

// ---- lightweight-charts spy --------------------------------------------
// Each call to `createChart` returns a fresh stub so we can count
// instantiations and assert that `setData` / `update` happen on the same
// instance across refreshes.
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
  subscribeCrosshairMove: ReturnType<typeof vi.fn>;
  priceScale: ReturnType<typeof vi.fn>;
  timeScale: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  takeScreenshot: ReturnType<typeof vi.fn>;
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
    // Stable per-chart timeScale stub so spies accumulate calls across the
    // chart's lifetime (mount focus + every data refresh). Without this each
    // `chart.timeScale()` call returned a fresh `setVisibleLogicalRange` spy,
    // making cumulative-call assertions impossible.
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
      subscribeCrosshairMove: vi.fn(),
      priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
      timeScale: vi.fn(() => timeScaleStub),
      remove: vi.fn(),
      applyOptions: vi.fn(),
      resize: vi.fn(),
      takeScreenshot: vi.fn(() => document.createElement("canvas")),
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

// HPRow loosened to the shape PriceChart actually reads.
type Row = {
  date?: string;
  ts?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  adj_close?: number;
  adjClose?: number;
};

function makeCandle(date: string, close: number): Row {
  return {
    date,
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    volume: 1_000,
  };
}

function chartApiRef() {
  return { current: null } as { current: IChartApi | null };
}

afterEach(() => {
  chartInstances.length = 0;
  cleanup();
});

describe("HP / PriceChart — chart instance lifecycle", () => {
  it("creates the chart once and reuses it across candle refreshes", () => {
    const ref = chartApiRef();
    const initial = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    const updated = [...initial, makeCandle("2026-05-17", 103)];
    const { rerender } = render(
      <PriceChart
        chartId="HP"
        rows={initial}
        interval="1d"
        chartStyle="candle"
        activeIndicators={[]}
        onCrosshair={() => undefined}
        comparedSeries={[]}
        chartApiRef={ref}
      />,
    );
    expect(chartInstances).toHaveLength(1);
    const chart = chartInstances[0];
    expect(chart.remove).not.toHaveBeenCalled();
    expect(chart.addCandlestickSeries).toHaveBeenCalledTimes(1);
    const candleSeries = chart.__series[0];
    expect(candleSeries.setData).toHaveBeenCalledTimes(1);

    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={updated}
          interval="1d"
          chartStyle="candle"
          activeIndicators={[]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
        />,
      );
    });

    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    // The same candle series instance received a fresh setData with the
    // larger row set.
    expect(candleSeries.setData).toHaveBeenCalledTimes(2);
    const lastCall = candleSeries.setData.mock.calls.at(-1)?.[0] as unknown[];
    expect(lastCall).toHaveLength(updated.length);
  });

  it("changing chartStyle DOES rebuild the chart (intentional)", () => {
    const ref = chartApiRef();
    const candles = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    const { rerender } = render(
      <PriceChart
        chartId="HP"
        rows={candles}
        interval="1d"
        chartStyle="candle"
        activeIndicators={[]}
        onCrosshair={() => undefined}
        comparedSeries={[]}
        chartApiRef={ref}
      />,
    );
    expect(chartInstances).toHaveLength(1);

    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={candles}
          interval="1d"
          chartStyle="line"
          activeIndicators={[]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
        />,
      );
    });
    expect(chartInstances).toHaveLength(2);
    expect(chartInstances[0].remove).toHaveBeenCalledTimes(1);
    // The new instance uses a line series, not a candle series.
    expect(chartInstances[1].addCandlestickSeries).not.toHaveBeenCalled();
    expect(chartInstances[1].addLineSeries).toHaveBeenCalled();
  });

  it("changing only the onCrosshair callback identity does NOT rebuild", () => {
    const ref = chartApiRef();
    const candles = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    const { rerender } = render(
      <PriceChart
        chartId="HP"
        rows={candles}
        interval="1d"
        chartStyle="candle"
        activeIndicators={[]}
        onCrosshair={() => undefined}
        comparedSeries={[]}
        chartApiRef={ref}
      />,
    );
    expect(chartInstances).toHaveLength(1);
    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={candles}
          interval="1d"
          chartStyle="candle"
          activeIndicators={[]}
          onCrosshair={() => undefined /* new identity each render */}
          comparedSeries={[]}
          chartApiRef={ref}
        />,
      );
    });
    expect(chartInstances).toHaveLength(1);
    expect(chartInstances[0].remove).not.toHaveBeenCalled();
  });

  it("applies a live tick via series.update() without rebuilding", () => {
    const ref = chartApiRef();
    const candles = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    const { rerender } = render(
      <PriceChart
        chartId="HP"
        rows={candles}
        interval="1d"
        chartStyle="candle"
        activeIndicators={[]}
        onCrosshair={() => undefined}
        comparedSeries={[]}
        chartApiRef={ref}
        liveTick={null}
      />,
    );
    const chart = chartInstances[0];
    const candleSeries = chart.__series[0];
    expect(candleSeries.update).not.toHaveBeenCalled();

    const tick: HPLiveTick = { price: 105, ts: Date.now() };
    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={candles}
          interval="1d"
          chartStyle="candle"
          activeIndicators={[]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
          liveTick={tick}
        />,
      );
    });

    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    expect(candleSeries.update).toHaveBeenCalledTimes(1);
    const updateArg = candleSeries.update.mock.calls[0]?.[0] as {
      close: number;
      high: number;
      low: number;
    };
    expect(updateArg.close).toBe(105);
    // High must expand to cover the new tick.
    expect(updateArg.high).toBeGreaterThanOrEqual(105);
    // Low must remain ≤ the new tick (105 ≥ 99 so unchanged).
    expect(updateArg.low).toBeLessThanOrEqual(105);
  });

  it("adding an indicator does NOT remove the chart — it only adds a series", () => {
    const ref = chartApiRef();
    const candles = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    const { rerender } = render(
      <PriceChart
        chartId="HP"
        rows={candles}
        interval="1d"
        chartStyle="candle"
        activeIndicators={[]}
        onCrosshair={() => undefined}
        comparedSeries={[]}
        chartApiRef={ref}
      />,
    );
    const chart = chartInstances[0];
    const baselineAddLine = chart.addLineSeries.mock.calls.length;

    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={candles}
          interval="1d"
          chartStyle="candle"
          activeIndicators={["SMA(20)"]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
        />,
      );
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    expect(chart.addLineSeries.mock.calls.length).toBeGreaterThan(baselineAddLine);

    // Removing the indicator drops the series WITHOUT touching the chart.
    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={candles}
          interval="1d"
          chartStyle="candle"
          activeIndicators={[]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
        />,
      );
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.remove).not.toHaveBeenCalled();
    expect(chart.removeSeries).toHaveBeenCalled();
  });

  it("publishes the chart API on the supplied ref", () => {
    const ref = chartApiRef();
    const candles = [makeCandle("2026-05-15", 100), makeCandle("2026-05-16", 101)];
    render(
      <PriceChart
        chartId="HP"
        rows={candles}
        interval="1d"
        chartStyle="candle"
        activeIndicators={[]}
        onCrosshair={() => undefined}
        comparedSeries={[]}
        chartApiRef={ref}
      />,
    );
    expect(ref.current).toBe(chartInstances[0] as unknown as IChartApi);
  });
});

describe("HP source — fabricated content guards", () => {
  it("does not export or define buildMockNews", () => {
    expect(hpSourceRaw).not.toMatch(/function\s+buildMockNews/);
    expect(hpSourceRaw).not.toMatch(/buildMockNews\s*\(/);
  });

  it("does not contain the canned fake headline strings", () => {
    // These three sentences were the entire output of the removed
    // `buildMockNews` helper. Any reintroduction must fail this test.
    expect(hpSourceRaw).not.toContain("prints fresh session high on volume spike");
    expect(hpSourceRaw).not.toContain("Sector rotation lifts");
    expect(hpSourceRaw).not.toContain("options skew turns bullish into expiry");
  });

  it("renders an honest 'News feed not wired' empty state", () => {
    expect(hpSourceRaw).toContain("News feed not wired");
    expect(hpSourceRaw).toMatch(/data-testid="hp-news-empty"/);
  });
});

describe("HP source — Compare and Export preservation", () => {
  it("keeps the real Compare overlay (ComparePopup + comparedSymbols persistence)", () => {
    // HP's Compare popup is wired through `comparedSymbols` persistence and
    // a real `compareA/B/C` set of useFunction calls. Make sure the rebuild
    // didn't accidentally rip those out.
    expect(hpSourceRaw).toMatch(/function\s+ComparePopup\s*\(/);
    expect(hpSourceRaw).toMatch(/usePersistentSymbols\(/);
    expect(hpSourceRaw).toMatch(/onCompareAdd\s*=/);
  });

  it("keeps the real Export PNG path (takeScreenshot → blob → download)", () => {
    expect(hpSourceRaw).toMatch(/handleExportPng/);
    expect(hpSourceRaw).toMatch(/takeScreenshot\(\)/);
    expect(hpSourceRaw).toMatch(/\.png/);
  });

  it("keeps the real Export CSV path (downloadCsv → buildCsv)", () => {
    expect(hpSourceRaw).toMatch(/function\s+downloadCsv\s*\(/);
    expect(hpSourceRaw).toMatch(/downloadCsv\(/);
    expect(hpSourceRaw).toMatch(/from\s+"\.\/HP\.csv"/);
  });

  it("does NOT regress Compare/Export into the GP-style aria-disabled placeholder", () => {
    // GP's audit explicitly disabled those toolbars with a 'not wired yet'
    // title. HP's controls are real — neither title must leak into HP.
    expect(hpSourceRaw).not.toContain("Compare overlay is not wired yet");
    expect(hpSourceRaw).not.toContain("Chart export is not wired yet");
  });
});

describe("HP source — mount-only chart contract", () => {
  it("does not pin the mount-effect to chartRows", () => {
    // The S03-H bug was: chart lifecycle effect dep array ended with
    // `chartRows, ...`. The new layout has a dedicated data-refresh effect.
    // We assert the dep array signature of the mount effect.
    expect(hpSourceRaw).toMatch(
      /\}, \[chartStyle, compareMode, interval, paletteKey, chartApiRef\]\);/,
    );
  });

  it("uses a value-stable paletteKey instead of palette object identity", () => {
    // `useChartPalette` returns a fresh object on every render; depending the
    // mount effect on its identity caused two `createChart` calls on the
    // initial commit. The fix joins the palette's color slots into a string.
    expect(hpSourceRaw).toMatch(/const paletteKey = useMemo\(/);
    expect(hpSourceRaw).toMatch(/palette\.volPos[\s\S]{0,100}palette\.volNeg/);
  });
});

describe("HP / PriceChart — viewport preservation across data refreshes", () => {
  // The bug: HP's data-refresh effect called `focusLatestBars(chart, …)` after
  // every `setData()`, which in turn invoked
  // `chart.timeScale().setVisibleLogicalRange(…)`. Each periodic poll therefore
  // snapped the user's manual zoom back to the "latest 90-240 bars" default.
  //
  // The contract: `setVisibleLogicalRange` fires exactly once across the
  // chart's lifetime (the initial mount focus). Subsequent refreshes,
  // indicator toggles, and live ticks must leave the viewport alone so the
  // user's wheel/pinch zoom survives the next data poll.
  it("calls setVisibleLogicalRange once on mount, not on subsequent refreshes", () => {
    const ref = chartApiRef();
    const initial = [
      makeCandle("2026-05-15", 100),
      makeCandle("2026-05-16", 101),
      makeCandle("2026-05-17", 102),
    ];
    const refreshed = [...initial, makeCandle("2026-05-18", 103)];
    const refreshedAgain = [...refreshed, makeCandle("2026-05-19", 104)];

    const { rerender } = render(
      <PriceChart
        chartId="HP"
        rows={initial}
        interval="1d"
        chartStyle="candle"
        activeIndicators={[]}
        onCrosshair={() => undefined}
        comparedSeries={[]}
        chartApiRef={ref}
      />,
    );
    const chart = chartInstances[0];
    expect(chart).toBeDefined();
    // Mount commits BOTH the chart-instance effect and the data-refresh effect.
    // The data-refresh effect SHOULD NOT re-focus — the dedicated
    // first-seed-focus effect handles initial framing exactly once.
    expect(chart.__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    // Periodic poll #1 — same instance, larger row set.
    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={refreshed}
          interval="1d"
          chartStyle="candle"
          activeIndicators={[]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
        />,
      );
    });
    expect(chartInstances).toHaveLength(1);
    expect(chart.__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    // Periodic poll #2 — viewport still must not be touched.
    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={refreshedAgain}
          interval="1d"
          chartStyle="candle"
          activeIndicators={[]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
        />,
      );
    });
    expect(chart.__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);
  });

  it("does not touch viewport on indicator toggle or live tick", () => {
    const ref = chartApiRef();
    const rows = [
      makeCandle("2026-05-15", 100),
      makeCandle("2026-05-16", 101),
      makeCandle("2026-05-17", 102),
    ];
    const { rerender } = render(
      <PriceChart
        chartId="HP"
        rows={rows}
        interval="1d"
        chartStyle="candle"
        activeIndicators={[]}
        onCrosshair={() => undefined}
        comparedSeries={[]}
        chartApiRef={ref}
        liveTick={null}
      />,
    );
    const chart = chartInstances[0];
    expect(chart.__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    // Indicator add — no viewport change.
    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={rows}
          interval="1d"
          chartStyle="candle"
          activeIndicators={["SMA(20)"]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
          liveTick={null}
        />,
      );
    });
    expect(chart.__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    // Live tick — no viewport change.
    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={rows}
          interval="1d"
          chartStyle="candle"
          activeIndicators={["SMA(20)"]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
          liveTick={{ price: 103, ts: Date.now() }}
        />,
      );
    });
    expect(chart.__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);
  });

  it("re-frames once after a chartStyle rebuild — new instance, new first-seed focus", () => {
    // When the user swaps candle ↔ line, the chart is intentionally
    // recreated (different series type). The new instance is allowed to call
    // setVisibleLogicalRange once for its own first-seed focus — but only
    // once, and never again on subsequent data refreshes.
    const ref = chartApiRef();
    const rows = [
      makeCandle("2026-05-15", 100),
      makeCandle("2026-05-16", 101),
      makeCandle("2026-05-17", 102),
    ];
    const { rerender } = render(
      <PriceChart
        chartId="HP"
        rows={rows}
        interval="1d"
        chartStyle="candle"
        activeIndicators={[]}
        onCrosshair={() => undefined}
        comparedSeries={[]}
        chartApiRef={ref}
      />,
    );
    expect(chartInstances[0].__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={rows}
          interval="1d"
          chartStyle="line"
          activeIndicators={[]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
        />,
      );
    });
    expect(chartInstances).toHaveLength(2);
    expect(chartInstances[1].__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);

    // Refresh on the new instance — viewport still untouched.
    act(() => {
      rerender(
        <PriceChart
          chartId="HP"
          rows={[...rows, makeCandle("2026-05-18", 103)]}
          interval="1d"
          chartStyle="line"
          activeIndicators={[]}
          onCrosshair={() => undefined}
          comparedSeries={[]}
          chartApiRef={ref}
        />,
      );
    });
    expect(chartInstances[1].__timeScale.setVisibleLogicalRange).toHaveBeenCalledTimes(1);
  });
});
