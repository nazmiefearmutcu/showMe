/**
 * Renderer execution tests — drawChart against a recording 2D-context stub.
 *
 * The jsdom smoke test bails before painting (no canvas context), so this
 * suite is the one that actually runs the milestone-2 pipeline: log/percent
 * price modes, the volume strip and user drawings. It asserts observable
 * paint calls (labels, dashes, strips, handles) instead of pixels.
 */
import { describe, expect, it } from "vitest";
import { createPriceScale, createTimeScale } from "./scales";
import { drawChart, fitPriceToVisible, normalizeCompareSeries } from "./renderer";
import type { Bar, CompareSeriesInput, RenderInput, ThemePalette, Viewport } from "./types";
import type { Drawing } from "./drawings";

const VIEWPORT: Viewport = { width: 800, height: 600, priceAxisWidth: 66, timeAxisHeight: 22 };
const PLOT_H = VIEWPORT.height - VIEWPORT.timeAxisHeight; // 578

const PALETTE: ThemePalette = {
  background: "#0b0e14",
  grid: "#1c2230",
  axisText: "#7a8699",
  textPrimary: "#e6edf7",
  textSecondary: "#9aa7bd",
  positive: "#26a69a",
  negative: "#ef5350",
  wick: "#7a8699",
  bodyUp: "#26a69a",
  bodyDown: "#ef5350",
  line: "#4c8dff",
  areaTop: "#4c8dff",
  areaBottom: "#4c8dff",
  crosshair: "#7a8699",
  accent: "#d4a24e",
};

interface Recorded {
  labels: string[];
  dashes: number[][];
  rects: { x: number; y: number; w: number; h: number }[];
  arcs: number;
}

function makeCtx(rec: Recorded): CanvasRenderingContext2D {
  const noop = (): void => undefined;
  const gradient = { addColorStop: noop };
  const ctx = {
    setTransform: noop,
    clearRect: noop,
    beginPath: noop,
    closePath: noop,
    moveTo: noop,
    lineTo: noop,
    rect: noop,
    clip: noop,
    stroke: noop,
    fill: noop,
    save: noop,
    restore: noop,
    fillText: (text: string) => {
      rec.labels.push(String(text));
    },
    setLineDash: (d: number[]) => {
      rec.dashes.push([...d]);
    },
    fillRect: (x: number, y: number, w: number, h: number) => {
      rec.rects.push({ x, y, w, h });
    },
    arc: () => {
      rec.arcs += 1;
    },
    createLinearGradient: () => gradient,
    measureText: () => ({ width: 24 }),
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    font: "",
    textAlign: "left",
    textBaseline: "middle",
    globalAlpha: 1,
  };
  return ctx as unknown as CanvasRenderingContext2D;
}

function makeBars(n: number, base = 100): Bar[] {
  const bars: Bar[] = [];
  for (let i = 0; i < n; i++) {
    const c = base + i;
    bars.push({ t: 1_700_000_000_000 + i * 60_000, o: c - 0.4, h: c + 0.6, l: c - 0.8, c, v: 10 + i });
  }
  return bars;
}

function runDraw(opts: {
  bars?: Bar[];
  priceMode?: RenderInput["priceMode"];
  showVolume?: boolean;
  drawings?: Drawing[];
  priceFit?: [number, number];
  chartType?: RenderInput["chartType"];
  replayIndex?: number;
  compare?: CompareSeriesInput[];
}): Recorded {
  const bars = opts.bars ?? makeBars(60);
  const time = createTimeScale();
  const price = createPriceScale();
  time.setViewport(VIEWPORT);
  price.setViewport(VIEWPORT);
  time.setRange(0, bars.length - 1);
  const [lo, hi] = opts.priceFit ?? [95, 165];
  price.fit(lo, hi, 0);
  const rec: Recorded = { labels: [], dashes: [], rects: [], arcs: 0 };
  drawChart({
    ctx: makeCtx(rec),
    dpr: 1,
    viewport: VIEWPORT,
    palette: PALETTE,
    bars,
    chartType: opts.chartType ?? "candles",
    time,
    price,
    indicators: [],
    crosshair: null,
    symbol: "BTCUSDT",
    priceMode: opts.priceMode,
    showVolume: opts.showVolume,
    drawings: opts.drawings,
    replayIndex: opts.replayIndex,
    compare: opts.compare,
  });
  return rec;
}

describe("drawChart — price-scale modes", () => {
  it("linear mode labels raw prices", () => {
    const rec = runDraw({});
    expect(rec.labels.length).toBeGreaterThan(0);
    // Axis labels never carry a % suffix in linear mode (the legend readout
    // may mention % inside "(+1.00%)" — endsWith keeps the check specific).
    expect(rec.labels.some((l) => l.endsWith("%"))).toBe(false);
  });

  it("percent mode labels % change relative to the first visible close", () => {
    const rec = runDraw({ priceMode: "percent" });
    // bars[0].c = 100 -> +8.00% appears for the price 108 gridline region.
    expect(rec.labels.some((l) => l.endsWith("%"))).toBe(true);
    expect(rec.labels).toContain("+0.00%");
  });

  it("log mode keeps price labels and never emits NaN", () => {
    const rec = runDraw({ priceMode: "log" });
    expect(rec.labels.length).toBeGreaterThan(0);
    expect(rec.labels.some((l) => l.includes("NaN"))).toBe(false);
    expect(rec.labels.some((l) => l.endsWith("%"))).toBe(false);
  });

  it("log mode falls back to price grid on a non-positive range without crashing", () => {
    const rec = runDraw({ priceMode: "log", priceFit: [-20, 40] });
    expect(rec.labels.length).toBeGreaterThan(0);
  });
});

describe("drawChart — volume strip", () => {
  it("paints volume bars only inside the bottom ~18% of the main pane", () => {
    const rec = runDraw({ chartType: "line", showVolume: true });
    const stripTop = PLOT_H - PLOT_H * 0.18;
    const strip = rec.rects.filter((r) => r.y >= stripTop - 1 && r.h >= 1);
    expect(strip.length).toBeGreaterThan(10);
    for (const r of strip) {
      expect(r.y + r.h).toBeLessThanOrEqual(PLOT_H + 0.5);
    }
  });

  it("skips silently when every visible volume is 0", () => {
    const bars = makeBars(30).map((b) => ({ ...b, v: 0 }));
    const rec = runDraw({ bars, chartType: "line", showVolume: true, priceFit: [95, 135] });
    const stripTop = PLOT_H - PLOT_H * 0.18;
    const strip = rec.rects.filter((r) => r.y >= stripTop - 1 && r.h >= 1);
    expect(strip).toHaveLength(0);
  });

  it("draws nothing when showVolume is off", () => {
    const rec = runDraw({ chartType: "line", showVolume: false });
    const stripTop = PLOT_H - PLOT_H * 0.18;
    expect(rec.rects.filter((r) => r.y >= stripTop - 1 && r.h >= 1)).toHaveLength(0);
  });
});

describe("drawChart — user drawings", () => {
  it("draws a dashed hline with an axis tag", () => {
    const rec = runDraw({
      drawings: [{ id: "h1", kind: "hline", price: 130 }],
    });
    expect(rec.dashes.some((d) => d[0] === 5 && d[1] === 4)).toBe(true);
    expect(rec.labels).toContain("130");
  });

  it("draws a trendline with two round handles", () => {
    const rec = runDraw({
      drawings: [
        { id: "t1", kind: "trend", p1: { index: 10, price: 110 }, p2: { index: 50, price: 150 } },
      ],
    });
    expect(rec.arcs).toBeGreaterThanOrEqual(2);
  });

  it("skips malformed drawings without throwing", () => {
    const rec = runDraw({
      drawings: [
        { id: "bad1", kind: "hline" },
        { id: "bad2", kind: "trend", p1: { index: Number.NaN, price: 1 } },
      ],
    });
    expect(rec.arcs).toBe(0);
    expect(rec.dashes.some((d) => d[0] === 5)).toBe(false);
  });

  it("skips an hline at a non-positive price under log mode", () => {
    const rec = runDraw({
      priceMode: "log",
      drawings: [{ id: "h2", kind: "hline", price: -5 }],
    });
    expect(rec.dashes.some((d) => d[0] === 5 && d[1] === 4)).toBe(false);
  });

  it("paints fib levels between the two anchors with ratio labels", () => {
    const rec = runDraw({
      drawings: [
        { id: "f1", kind: "fib", p1: { index: 0, price: 100 }, p2: { index: 59, price: 160 } },
      ],
    });
    expect(rec.labels.some((l) => l.startsWith("0.0%"))).toBe(true);
    expect(rec.labels.some((l) => l.startsWith("50.0%"))).toBe(true);
    expect(rec.labels.some((l) => l.startsWith("61.8%"))).toBe(true);
    expect(rec.labels.some((l) => l.startsWith("100.0%"))).toBe(true);
    expect(rec.arcs).toBe(2); // anchor handles
  });
});

describe("drawChart — bar replay", () => {
  it("paints no candle after the replay cursor", () => {
    const bars = makeBars(60);
    const rec = runDraw({ bars, chartType: "candles", showVolume: false, replayIndex: 30 });
    const PLOT_W = VIEWPORT.width - VIEWPORT.priceAxisWidth;
    const x30 = (30 / 59) * PLOT_W;
    const bodyW = Math.min(28, (PLOT_W / 59) * 0.72);
    expect(rec.rects.filter((r) => r.x < x30).length).toBeGreaterThan(0);
    for (const r of rec.rects) {
      expect(r.x).toBeLessThanOrEqual(x30 + bodyW / 2 + 0.5);
    }
  });

  it("keeps the full series when replayIndex is omitted (backward compatible)", () => {
    const bars = makeBars(60);
    const rec = runDraw({ bars, chartType: "candles", showVolume: false });
    const PLOT_W = VIEWPORT.width - VIEWPORT.priceAxisWidth;
    const x30 = (30 / 59) * PLOT_W;
    expect(rec.rects.some((r) => r.x > x30 + 40)).toBe(true);
  });
});

describe("normalizeCompareSeries", () => {
  const mk = (closes: number[]): Bar[] =>
    closes.map((c, i) => ({ t: 1_700_000_000_000 + i * 60_000, o: c, h: c, l: c, c, v: 1 }));

  it("normalizes vs. the first finite close at/after firstIndex", () => {
    expect(normalizeCompareSeries(mk([50, 100, 110]), 1)).toEqual([-50, 0, 10]);
  });

  it("skips zero closes for the base and marks them null", () => {
    const out = normalizeCompareSeries(mk([0, 100, 150]), 0);
    expect(out[0]).toBeNull();
    expect(out[1]).toBe(0);
    expect(out[2]).toBeCloseTo(50, 10);
  });

  it("returns all nulls when no finite non-zero base exists", () => {
    expect(normalizeCompareSeries(mk([0, 0]), 0)).toEqual([null, null]);
    expect(normalizeCompareSeries([], 0)).toEqual([]);
  });
});

describe("drawChart — compare overlay", () => {
  it("labels each compare line's percent change in the legend", () => {
    const values: (number | null)[] = new Array(60).fill(0);
    values[59] = 10;
    const rec = runDraw({ compare: [{ symbol: "ETHUSDT", color: "#ff0000", values }] });
    expect(rec.labels).toContain("ETHUSDT +10.00%");
  });

  it("renders an honest dash when the cursor bar has no compare value", () => {
    const values: (number | null)[] = new Array(60).fill(null);
    const rec = runDraw({ compare: [{ symbol: "ETHUSDT", color: "#ff0000", values }] });
    expect(rec.labels).toContain("ETHUSDT —");
  });
});

describe("fitPriceToVisible — replay bound", () => {
  const bars: Bar[] = Array.from({ length: 60 }, (_, i) => ({
    t: 1_700_000_000_000 + i * 60_000,
    o: 100,
    h: i < 30 ? 130 : 1000,
    l: 90,
    c: 100,
    v: 1,
  }));

  it("excludes bars after lastIndex from the fit", () => {
    const time = createTimeScale();
    time.setViewport(VIEWPORT);
    time.setRange(0, 59);
    const price = createPriceScale();
    price.setViewport(VIEWPORT);
    fitPriceToVisible(price, bars, time, 0, 29);
    expect(price.range().max).toBeLessThan(200);

    const full = createPriceScale();
    full.setViewport(VIEWPORT);
    fitPriceToVisible(full, bars, time, 0);
    expect(full.range().max).toBeGreaterThan(900);
  });
});
