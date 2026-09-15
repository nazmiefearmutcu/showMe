/**
 * indicators.ts — hand-computed formula checks plus registry contract pins.
 *
 * Hand-computed cases cover SMA/EMA/WMA/Bollinger/RSI/MACD/ATR/Stochastic/
 * OBV/VWAP. The property suite then walks EVERY registry entry and pins the
 * three invariants the renderer relies on: one data point per bar, no NaN
 * (null is the only "undefined" marker), and nulls exactly until the
 * documented warmup index.
 */
import { describe, expect, it } from "vitest";
import { INDICATORS, indicatorById, indicatorCategories } from "./indicators";
import type { Bar, IndicatorDef, IndicatorParams, IndicatorResult } from "./types";

type Maybe = number | null;

function barsFromCloses(closes: number[], volumes?: number[]): Bar[] {
  return closes.map((c, i) => ({
    t: 1_700_000_000_000 + i * 60_000,
    o: i === 0 ? c : closes[i - 1],
    h: c + 1,
    l: c - 1,
    c,
    v: volumes ? volumes[i] : 100,
  }));
}

/** Deterministic 200-bar pseudo-random walk (fixed LCG seed, no Math.random). */
function deterministicBars(n: number): Bar[] {
  const closes: number[] = [];
  let seed = 987654321;
  let price = 100;
  for (let i = 0; i < n; i++) {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const r = seed / 4294967296 - 0.5;
    price = Math.max(5, price + r * 2);
    closes.push(price);
  }
  return closes.map((c, i) => ({
    t: 1_700_000_000_000 + i * 60_000,
    o: c - 0.2,
    h: c + 0.9,
    l: c - 1.1,
    c,
    v: 1000 + i,
  }));
}

function getDef(id: string): IndicatorDef {
  const def = indicatorById(id);
  if (!def) throw new Error(`missing indicator: ${id}`);
  return def;
}

function plotOf(result: IndicatorResult, key: string): Maybe[] {
  const plot = result.plots.find((p) => p.key === key);
  if (!plot) throw new Error(`missing plot: ${key}`);
  return plot.data;
}

function defaultParams(def: IndicatorDef): IndicatorParams {
  const params: IndicatorParams = {};
  for (const p of def.params) params[p.key] = p.default;
  return params;
}

/* ── hand-computed values ────────────────────────────────────────────── */

describe("hand-computed indicator values", () => {
  it("SMA(3) over [1,2,3,4,5]", () => {
    const res = getDef("sma").compute(barsFromCloses([1, 2, 3, 4, 5]), { length: 3 });
    expect(plotOf(res, "sma")).toEqual([null, null, 2, 3, 4]);
  });

  it("EMA(3) seeds with SMA then k = 0.5", () => {
    const res = getDef("ema").compute(barsFromCloses([1, 2, 3, 4, 5]), { length: 3 });
    expect(plotOf(res, "ema")).toEqual([null, null, 2, 3, 4]);
  });

  it("WMA(2) weights the newest bar 2:1", () => {
    const res = getDef("wma").compute(barsFromCloses([1, 2, 3, 4]), { length: 2 });
    const wma = plotOf(res, "wma");
    expect(wma[0]).toBeNull();
    expect(wma[1]).toBeCloseTo(5 / 3, 10);
    expect(wma[2]).toBeCloseTo(8 / 3, 10);
    expect(wma[3]).toBeCloseTo(11 / 3, 10);
  });

  it("Bollinger(3, 2) uses population std over the window", () => {
    const res = getDef("bb").compute(barsFromCloses([1, 2, 3, 4, 5]), {
      length: 3,
      mult: 2,
    });
    const std = Math.sqrt(2 / 3);
    const upper = plotOf(res, "bbu");
    const mid = plotOf(res, "bbm");
    const lower = plotOf(res, "bbl");
    expect(mid).toEqual([null, null, 2, 3, 4]);
    expect(upper[2]).toBeCloseTo(2 + 2 * std, 10);
    expect(lower[2]).toBeCloseTo(2 - 2 * std, 10);
    expect(upper[4]).toBeCloseTo(4 + 2 * std, 10);
    expect(lower[4]).toBeCloseTo(4 - 2 * std, 10);
  });

  it("RSI(3) follows Wilder smoothing exactly", () => {
    const res = getDef("rsi").compute(barsFromCloses([3, 2, 1, 2, 3, 4]), { length: 3 });
    const rsi = plotOf(res, "rsi");
    expect(rsi.slice(0, 3)).toEqual([null, null, null]);
    expect(rsi[3]).toBeCloseTo(100 / 3, 6);
    expect(rsi[4]).toBeCloseTo(100 - 100 / 2.25, 6);
    expect(rsi[5]).toBeCloseTo(100 - 100 / 3.375, 6);
  });

  it("MACD(2,4,3) computes line, signal seed and histogram", () => {
    const res = getDef("macd").compute(barsFromCloses([1, 2, 4, 7, 11, 16, 22]), {
      fast: 2,
      slow: 4,
      signal: 3,
    });
    const macd = plotOf(res, "macd");
    const signal = plotOf(res, "signal");
    const hist = plotOf(res, "hist");
    expect(macd.slice(0, 3)).toEqual([null, null, null]);
    expect(signal.slice(0, 5)).toEqual([null, null, null, null, null]);
    expect(macd[3]).toBeCloseTo(2.2222222, 6);
    expect(macd[6]).toBeCloseTo(4.2689712, 6);
    expect(signal[5]).toBeCloseTo(2.8032922, 6);
    expect(signal[6]).toBeCloseTo(3.5361317, 6);
    expect(hist[5]).toBeCloseTo(0.6436214, 6);
    expect(hist[6]).toBeCloseTo(0.7328395, 6);
  });

  it("ATR(3) on constant-range bars equals that range", () => {
    const res = getDef("atr").compute(barsFromCloses([10, 10, 10, 10, 10]), { length: 3 });
    expect(plotOf(res, "atr")).toEqual([null, null, 2, 2, 2]);
  });

  it("Stochastic(3,2,2) yields 75 when the close sits at the window top", () => {
    const res = getDef("stoch").compute(barsFromCloses([10, 11, 12, 13, 14]), {
      kLength: 3,
      kSmooth: 2,
      dSmooth: 2,
    });
    const k = plotOf(res, "k");
    const d = plotOf(res, "d");
    expect(k.slice(0, 3)).toEqual([null, null, null]);
    expect(k[3]).toBeCloseTo(75, 10);
    expect(k[4]).toBeCloseTo(75, 10);
    expect(d[3]).toBeNull();
    expect(d[4]).toBeCloseTo(75, 10);
  });

  it("OBV adds volume on up closes, subtracts on down, holds on flat", () => {
    const res = getDef("obv").compute(barsFromCloses([10, 11, 10, 10, 12], [1, 2, 3, 4, 5]), {});
    expect(plotOf(res, "obv")).toEqual([0, 2, -1, -1, 4]);
  });

  it("VWAP is cumulative by default and windowed when length > 0", () => {
    const bars = barsFromCloses([1, 2, 4], [100, 100, 200]);
    const cumulative = plotOf(getDef("vwap").compute(bars, { length: 0 }), "vwap");
    expect(cumulative[0]).toBeCloseTo(1, 10);
    expect(cumulative[1]).toBeCloseTo(1.5, 10);
    expect(cumulative[2]).toBeCloseTo(2.75, 10);
    const rolling = plotOf(getDef("vwap").compute(bars, { length: 2 }), "vwap");
    expect(rolling[0]).toBeNull();
    expect(rolling[1]).toBeCloseTo(1.5, 10);
    expect(rolling[2]).toBeCloseTo(1000 / 300, 10);
  });
});

/* ── registry metadata ───────────────────────────────────────────────── */

describe("registry metadata", () => {
  it("exposes 25 unique ids and every compute is callable", () => {
    expect(INDICATORS).toHaveLength(25);
    expect(new Set(INDICATORS.map((d) => d.id)).size).toBe(25);
    for (const def of INDICATORS) {
      expect(def.name.length).toBeGreaterThan(0);
      expect(def.category.length).toBeGreaterThan(0);
    }
  });

  it("indicatorById finds known ids and returns undefined otherwise", () => {
    expect(indicatorById("rsi")?.name).toBe("RSI");
    expect(indicatorById("cmf")?.overlayDefault).toBe(false);
    expect(indicatorById("does-not-exist")).toBeUndefined();
  });

  it("indicatorCategories lists unique groups in registry order", () => {
    const categories = indicatorCategories();
    expect(new Set(categories).size).toBe(categories.length);
    expect(categories).toContain("Moving averages");
    expect(categories).toContain("Bands");
    expect(categories).toContain("Oscillators");
    expect(categories).toContain("Levels");
    expect(categories).toContain("Trend");
    expect(categories).toContain("Volume");
    expect(categories).toContain("Volatility");
  });

  it("overlayDefault matches the spec split (11 price-pane, 14 panes)", () => {
    const overlays = INDICATORS.filter((d) => d.overlayDefault).map((d) => d.id);
    const panes = INDICATORS.filter((d) => !d.overlayDefault).map((d) => d.id);
    expect(overlays).toEqual([
      "sma",
      "ema",
      "wma",
      "bb",
      "vwap",
      "keltner",
      "donchian",
      "psar",
      "supertrend",
      "ichimoku",
      "pivot",
    ]);
    expect(panes).toEqual([
      "rsi",
      "macd",
      "stoch",
      "atr",
      "adx",
      "cci",
      "williams-r",
      "obv",
      "mfi",
      "roc",
      "volume",
      "stoch-rsi",
      "uo",
      "cmf",
    ]);
  });

  it("declares the spec levels and zero lines", () => {
    const bars = deterministicBars(200);
    const result = (id: string) => getDef(id).compute(bars, defaultParams(getDef(id)));
    expect(result("rsi").levels).toEqual([30, 70]);
    expect(result("stoch").levels).toEqual([20, 80]);
    expect(result("adx").levels).toEqual([25]);
    expect(result("cci").levels).toEqual([-100, 100]);
    expect(result("williams-r").levels).toEqual([-20, -80]);
    expect(result("mfi").levels).toEqual([20, 80]);
    expect(result("stoch-rsi").levels).toEqual([20, 80]);
    expect(result("uo").levels).toEqual([30, 70]);
    expect(result("macd").zeroLine).toBe(true);
    expect(result("cci").zeroLine).toBe(true);
    expect(result("roc").zeroLine).toBe(true);
    expect(result("cmf").zeroLine).toBe(true);
  });
});

/* ── property pins: every indicator, every plot ──────────────────────── */

/** First index whose value must be non-null, per indicator + plot key. */
const FIRST_DEFINED: Record<string, Record<string, number>> = {
  sma: { sma: 19 },
  ema: { ema: 19 },
  wma: { wma: 19 },
  bb: { bbu: 19, bbm: 19, bbl: 19 },
  vwap: { vwap: 0 },
  keltner: { kcu: 19, kcm: 19, kcl: 19 },
  donchian: { dcu: 19, dcm: 19, dcl: 19 },
  psar: { psar: 1 },
  supertrend: { st: 9, trend: 9 },
  ichimoku: { tenkan: 8, kijun: 25, senkouA: 51, senkouB: 77 },
  rsi: { rsi: 14 },
  macd: { macd: 25, signal: 33, hist: 33 },
  stoch: { k: 15, d: 17 },
  atr: { atr: 13 },
  adx: { adx: 27, plusDI: 14, minusDI: 14 },
  cci: { cci: 19 },
  "williams-r": { wr: 13 },
  obv: { obv: 0 },
  mfi: { mfi: 14 },
  roc: { roc: 12 },
  volume: { volume: 0 },
  "stoch-rsi": { k: 29, d: 31 },
  uo: { uo: 28 },
  cmf: { cmf: 19 },
};

const BARS = deterministicBars(200);

describe("property pins (length, no-NaN, warmup) for every indicator", () => {
  for (const def of INDICATORS) {
    it(`${def.id}: one point per bar, finite-or-null, warmup nulls`, () => {
      const result = def.compute(BARS, defaultParams(def));
      for (const plot of result.plots) {
        expect(plot.data).toHaveLength(BARS.length);
        for (const value of plot.data) {
          if (value !== null) expect(Number.isFinite(value)).toBe(true);
        }
        const firstExpected = FIRST_DEFINED[def.id]?.[plot.key];
        expect(firstExpected).toBeDefined();
        for (let i = 0; i < firstExpected; i++) {
          expect(plot.data[i]).toBeNull();
        }
        expect(plot.data[firstExpected]).not.toBeNull();
        expect(Number.isFinite(plot.data[firstExpected] as number)).toBe(true);
      }
      if (def.id === "pivot") {
        expect(result.plots).toHaveLength(0);
        const levels = result.levels ?? [];
        expect(levels).toHaveLength(7);
        for (const level of levels) expect(Number.isFinite(level)).toBe(true);
        for (let i = 1; i < levels.length; i++) {
          expect(levels[i]).toBeGreaterThan(levels[i - 1]);
        }
      }
    });
  }

  it("every indicator returns empty output for empty input without throwing", () => {
    for (const def of INDICATORS) {
      const result = def.compute([], defaultParams(def));
      for (const plot of result.plots) expect(plot.data).toHaveLength(0);
      if (def.id === "pivot") expect(result.levels).toEqual([]);
    }
  });

  it("tiny series produce no NaN and no out-of-bounds values", () => {
    const tiny = deterministicBars(3);
    for (const def of INDICATORS) {
      const result = def.compute(tiny, defaultParams(def));
      for (const plot of result.plots) {
        expect(plot.data).toHaveLength(3);
        for (const value of plot.data) {
          if (value !== null) expect(Number.isFinite(value)).toBe(true);
        }
      }
    }
  });
});
