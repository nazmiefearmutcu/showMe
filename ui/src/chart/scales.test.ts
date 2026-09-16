import { describe, expect, it } from "vitest";
import type { Viewport } from "./types";
import { createPriceScale, createTimeScale } from "./scales";
import { percentFromBase, priceMapperFor } from "./renderer";

const VIEWPORT: Viewport = {
  width: 800,
  height: 600,
  priceAxisWidth: 64,
  timeAxisHeight: 24,
};
const PLOT_W = VIEWPORT.width - VIEWPORT.priceAxisWidth; // 736
const PLOT_H = VIEWPORT.height - VIEWPORT.timeAxisHeight; // 576

describe("createTimeScale", () => {
  it("maps the visible index range linearly onto [0, plotWidth]", () => {
    const s = createTimeScale();
    s.setViewport(VIEWPORT);
    s.setRange(0, 100);
    expect(s.toX(0)).toBeCloseTo(0, 9);
    expect(s.toX(100)).toBeCloseTo(PLOT_W, 9);
    expect(s.toX(50)).toBeCloseTo(PLOT_W / 2, 9);
    expect(s.toIndex(0)).toBeCloseTo(0, 9);
    expect(s.toIndex(PLOT_W)).toBeCloseTo(100, 9);
  });

  it("round-trips index <-> x for float values", () => {
    const s = createTimeScale();
    s.setViewport(VIEWPORT);
    s.setRange(0, 100);
    const index = 37.25;
    expect(s.toIndex(s.toX(index))).toBeCloseTo(index, 9);
    const x = 123.75;
    expect(s.toX(s.toIndex(x))).toBeCloseTo(x, 9);
  });

  it("normalizes setRange, expands equal endpoints, ignores non-finite input", () => {
    const s = createTimeScale();
    s.setViewport(VIEWPORT);
    s.setRange(20.75, 10.25);
    let r = s.range();
    expect(r.from).toBeCloseTo(10.25, 9);
    expect(r.to).toBeCloseTo(20.75, 9);

    s.setRange(5, 5);
    r = s.range();
    expect(r.to - r.from).toBeCloseTo(1, 9);
    expect(r.from).toBeLessThan(5);
    expect(r.to).toBeGreaterThan(5);

    const before = s.range();
    s.setRange(Number.NaN, 12);
    expect(s.range().from).toBeCloseTo(before.from, 9);
    expect(s.range().to).toBeCloseTo(before.to, 9);
  });

  it("computes barWidth = plotWidth / span", () => {
    const s = createTimeScale();
    s.setViewport(VIEWPORT);
    s.setRange(0, 100);
    expect(s.barWidth()).toBeCloseTo(PLOT_W / 100, 9);
    const r = s.range();
    expect(s.barWidth()).toBeCloseTo(PLOT_W / (r.to - r.from), 9);
    s.setRange(0, 1);
    expect(s.barWidth()).toBeCloseTo(PLOT_W, 6);
    // A sub-pixel request clamps at the 1500 px/bar extreme.
    s.setRange(0, 1e-6);
    expect(s.barWidth()).toBeCloseTo(1500, 6);
  });

  it("keeps the index under the cursor invariant while zooming in", () => {
    const s = createTimeScale();
    s.setViewport(VIEWPORT);
    s.setRange(0, 100);
    for (const x of [0, 123.5, PLOT_W / 2, PLOT_W]) {
      const index = s.toIndex(x);
      s.zoomAt(x, 2.5);
      expect(s.toX(index)).toBeCloseTo(x, 6);
    }
    const span = s.range();
    expect(span.to).toBeGreaterThan(span.from);
  });

  it("keeps the same invariance while zooming out", () => {
    const s = createTimeScale();
    s.setViewport(VIEWPORT);
    s.setRange(0, 100);
    for (const x of [0, 300.25, PLOT_W]) {
      const index = s.toIndex(x);
      s.zoomAt(x, 0.4);
      expect(s.toX(index)).toBeCloseTo(x, 6);
    }
  });

  it("translates content by dx pixels per panBy dx", () => {
    const s = createTimeScale();
    s.setViewport(VIEWPORT);
    s.setRange(0, 100);
    const width = s.barWidth();
    const index = 12.34;
    const x0 = s.toX(index);
    s.panBy(37.5);
    expect(s.toX(index) - x0).toBeCloseTo(37.5, 6);
    expect(s.barWidth()).toBeCloseTo(width, 9);
    s.panBy(-100);
    expect(s.toX(index) - x0).toBeCloseTo(37.5 - 100, 6);
  });

  it("clamps barWidth to the near-zero floor and the 1500 px cap only", () => {
    const s = createTimeScale();
    s.setViewport(VIEWPORT);
    s.setRange(0, 100);
    for (let k = 0; k < 60; k += 1) {
      s.zoomAt(PLOT_W / 2, 2);
    }
    expect(s.barWidth()).toBeCloseTo(1500, 6);
    expect(s.barWidth()).toBeLessThanOrEqual(1500 + 1e-6);
    for (let k = 0; k < 240; k += 1) {
      s.zoomAt(PLOT_W / 2, 0.5);
    }
    /* The zoom-out floor is effectively infinite (1e-7 px per bar) so the
       range never clips: far past the old 0.05 floor the range keeps growing
       and stays finite/ordered. */
    expect(s.barWidth()).toBeCloseTo(1e-7, 12);
    expect(s.barWidth()).toBeGreaterThanOrEqual(1e-7 - 1e-12);
    const r = s.range();
    expect(Number.isFinite(r.from) && Number.isFinite(r.to)).toBe(true);
    expect(r.to).toBeGreaterThan(r.from);
    expect(r.to - r.from).toBeGreaterThan(1e6);
  });

  it("survives setViewport before/after ranges and resize", () => {
    const s = createTimeScale();
    expect(Number.isFinite(s.toX(0))).toBe(true); // before any setViewport
    s.setViewport(VIEWPORT);
    s.setRange(0, 50);
    expect(s.toX(50)).toBeCloseTo(PLOT_W, 9);
    s.setViewport({ ...VIEWPORT, width: 500 });
    const widerPlot = 500 - VIEWPORT.priceAxisWidth;
    expect(s.toX(50)).toBeCloseTo(widerPlot, 6);
    const r = s.range();
    expect(r.from).toBeCloseTo(0, 9);
    expect(r.to).toBeCloseTo(50, 9);
    s.setViewport(VIEWPORT);
    expect(s.toX(0)).toBeCloseTo(0, 9);
  });

  it("stays finite on a degenerate tiny viewport", () => {
    const s = createTimeScale();
    s.setViewport({ width: 10, height: 8, priceAxisWidth: 64, timeAxisHeight: 24 });
    expect(Number.isFinite(s.barWidth())).toBe(true);
    expect(Number.isFinite(s.toX(0))).toBe(true);
    expect(Number.isFinite(s.toIndex(10))).toBe(true);
    s.zoomAt(1, 2);
    s.panBy(5);
    const r = s.range();
    expect(Number.isFinite(r.from) && Number.isFinite(r.to)).toBe(true);
    expect(r.to).toBeGreaterThan(r.from);
  });
});

describe("createPriceScale", () => {
  it("maps the fitted range onto [plotBottom..plotTop] inverted", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(0, 100, 0);
    expect(p.toY(0)).toBeCloseTo(PLOT_H, 9);
    expect(p.toY(100)).toBeCloseTo(0, 9);
    expect(p.toY(50)).toBeCloseTo(PLOT_H / 2, 9);
    expect(p.toPrice(0)).toBeCloseTo(100, 9);
    expect(p.toPrice(PLOT_H)).toBeCloseTo(0, 9);
  });

  it("pads the fitted range (default 8%, explicit values honored)", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(0, 100);
    expect(p.range().min).toBeCloseTo(-8, 9);
    expect(p.range().max).toBeCloseTo(108, 9);
    p.fit(0, 100, 0.2);
    expect(p.range().min).toBeCloseTo(-20, 9);
    expect(p.range().max).toBeCloseTo(120, 9);
  });

  it("round-trips price <-> y for float values", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(10, 20, 0.05);
    const price = 17.3;
    expect(p.toPrice(p.toY(price))).toBeCloseTo(price, 6);
    const y = 123.4;
    expect(p.toY(p.toPrice(y))).toBeCloseTo(y, 6);
  });

  it("keeps the price under the cursor invariant while zooming", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(0, 100, 0);
    for (const y of [0, 200.5, PLOT_H / 2, PLOT_H]) {
      const price = p.toPrice(y);
      p.zoomAt(y, 2);
      expect(p.toY(price)).toBeCloseTo(y, 6);
    }
    const y = 321.75;
    const price = p.toPrice(y);
    p.zoomAt(y, 0.5);
    expect(p.toY(price)).toBeCloseTo(y, 6);
    const r = p.range();
    expect(r.max - r.min).toBeCloseTo(12.5, 6); // 100 -> /16 -> /0.5
  });

  it("translates content by dy pixels per panBy dy without changing span", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(0, 100, 0);
    const price = 42;
    const y0 = p.toY(price);
    p.panBy(-13.7);
    expect(p.toY(price) - y0).toBeCloseTo(-13.7, 6);
    expect(p.range().max - p.range().min).toBeCloseTo(100, 9);
    p.panBy(50);
    expect(p.toY(price) - y0).toBeCloseTo(-13.7 + 50, 6);
  });

  it("guards degenerate min == max (expand 1% or ±1, then pad)", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(50, 50);
    expect(p.range().min).toBeLessThan(50);
    expect(p.range().max).toBeGreaterThan(50);
    expect(p.range().min).toBeCloseTo(50 - 0.5 - 0.08, 9);
    expect(p.range().max).toBeCloseTo(50 + 0.5 + 0.08, 9);

    p.fit(0, 0);
    expect(p.range().min).toBeCloseTo(-1.16, 9);
    expect(p.range().max).toBeCloseTo(1.16, 9);
  });

  it("normalizes inverted ranges and non-finite inputs", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(100, 0);
    expect(p.range().min).toBeCloseTo(-8, 9);
    expect(p.range().max).toBeCloseTo(108, 9);

    p.fit(Number.NaN, Number.NaN);
    let r = p.range();
    expect(Number.isFinite(r.min) && Number.isFinite(r.max)).toBe(true);
    expect(r.max).toBeGreaterThan(r.min);

    p.fit(Number.NaN, 55);
    r = p.range();
    expect(Number.isFinite(r.min) && Number.isFinite(r.max)).toBe(true);
    expect(r.min).toBeLessThan(55);
    expect(r.max).toBeGreaterThan(55);
  });

  it("survives setViewport before/after ranges", () => {
    const p = createPriceScale();
    expect(Number.isFinite(p.toY(0))).toBe(true); // before any setViewport
    p.setViewport(VIEWPORT);
    p.fit(0, 100, 0);
    p.setViewport({ ...VIEWPORT, height: 200 });
    expect(p.toY(0)).toBeCloseTo(200 - VIEWPORT.timeAxisHeight, 9);
    expect(p.toY(100)).toBeCloseTo(0, 9);
  });

  it("stays finite on a degenerate tiny viewport with extreme zoom", () => {
    const p = createPriceScale();
    p.setViewport({ width: 10, height: 8, priceAxisWidth: 64, timeAxisHeight: 24 });
    p.fit(1, 2, 0);
    expect(Number.isFinite(p.toY(1))).toBe(true);
    expect(Number.isFinite(p.toPrice(1))).toBe(true);
    for (let k = 0; k < 50; k += 1) {
      p.zoomAt(0, 2);
    }
    const r = p.range();
    expect(Number.isFinite(r.min) && Number.isFinite(r.max)).toBe(true);
    expect(r.max).toBeGreaterThan(r.min);
  });
});

describe("priceMapperFor — price-scale modes", () => {
  it("maps log mode monotonically with min/max pinned to the plot edges", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(10, 1000, 0);
    const m = priceMapperFor(p, "log");
    expect(m.mode).toBe("log");
    expect(m.toY(10)).toBeCloseTo(PLOT_H, 6);
    expect(m.toY(1000)).toBeCloseTo(0, 6);
    // The geometric midpoint sits at the pixel midpoint in log space.
    expect(m.toY(Math.sqrt(10 * 1000))).toBeCloseTo(PLOT_H / 2, 6);
    let prev = Number.POSITIVE_INFINITY;
    for (const v of [10, 20, 50, 100, 400, 1000]) {
      const y = m.toY(v);
      expect(y).toBeLessThan(prev);
      prev = y;
    }
    for (const y of [0, 100.5, PLOT_H]) {
      expect(m.toY(m.toPrice(y))).toBeCloseTo(y, 6);
    }
  });

  it("falls back to linear when the visible range is not strictly positive", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(-5, 20, 0);
    const m = priceMapperFor(p, "log");
    expect(m.mode).toBe("linear");
    expect(m.toY(20)).toBeCloseTo(p.toY(20), 9);
    expect(m.toY(-5)).toBeCloseTo(p.toY(-5), 9);
  });

  it("returns NaN — never a lie — for non-positive prices in log mode", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(10, 100, 0);
    const m = priceMapperFor(p, "log");
    expect(Number.isNaN(m.toY(0))).toBe(true);
    expect(Number.isNaN(m.toY(-1))).toBe(true);
  });

  it("percent mode keeps the affine geometry (only the labels change)", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(0, 100, 0);
    const m = priceMapperFor(p, "percent");
    expect(m.mode).toBe("percent");
    expect(m.toY(42)).toBeCloseTo(p.toY(42), 9);
    expect(m.toPrice(123.4)).toBeCloseTo(p.toPrice(123.4), 9);
  });

  it("defaults to linear when no mode is given", () => {
    const p = createPriceScale();
    p.setViewport(VIEWPORT);
    p.fit(0, 100, 0);
    const m = priceMapperFor(p);
    expect(m.mode).toBe("linear");
    expect(m.toY(42)).toBeCloseTo(p.toY(42), 9);
  });

  it("percentFromBase computes % change from the anchor close", () => {
    expect(percentFromBase(110, 100)).toBeCloseTo(10, 9);
    expect(percentFromBase(90, 100)).toBeCloseTo(-10, 9);
    expect(percentFromBase(100, 100)).toBe(0);
    expect(percentFromBase(121, 110)).toBeCloseTo(10, 9);
    // Degenerate inputs return NaN so callers fall back to price labels.
    expect(Number.isNaN(percentFromBase(10, 0))).toBe(true);
    expect(Number.isNaN(percentFromBase(Number.NaN, 100))).toBe(true);
    expect(Number.isNaN(percentFromBase(10, Number.POSITIVE_INFINITY))).toBe(true);
  });
});
