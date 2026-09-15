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
import { drawChart } from "./renderer";
import type { Bar, RenderInput, ThemePalette, Viewport } from "./types";
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
});
