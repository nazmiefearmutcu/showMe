/**
 * Drawing-tool pure helpers + pixel-space hit test.
 *
 * The helpers never touch the DOM; the mapper stubs below are the exact
 * `(index) => x` / `(price) => y` functions the renderer would pass, so the
 * hit test contract (same space as the paint) is pinned here.
 */
import { describe, expect, it } from "vitest";
import {
  addHline,
  addTrend,
  clearDrawings,
  hitTestDrawing,
  removeDrawing,
  type Drawing,
} from "./drawings";

/** 1 bar index = 10 px; 1 price unit = 1 px (inverted y as on a chart). */
const toX = (index: number): number => index * 10;
const toY = (price: number): number => 200 - price;

describe("addHline", () => {
  it("appends a finite-priced hline with a unique id (immutably)", () => {
    const before: Drawing[] = [];
    const after = addHline(before, 123.45);
    expect(before).toHaveLength(0);
    expect(after).toHaveLength(1);
    expect(after[0].kind).toBe("hline");
    expect(after[0].price).toBe(123.45);
    expect(after[0].id).toBeTruthy();
    const again = addHline(after, 130);
    expect(again).toHaveLength(2);
    expect(again[0].id).not.toBe(again[1].id);
  });

  it("ignores non-finite prices", () => {
    const list: Drawing[] = [];
    expect(addHline(list, Number.NaN)).toBe(list);
    expect(addHline(list, Number.POSITIVE_INFINITY)).toBe(list);
  });
});

describe("addTrend", () => {
  it("appends a trendline and copies its points", () => {
    const p1 = { index: 1, price: 100 };
    const p2 = { index: 5, price: 120 };
    const list = addTrend([], p1, p2);
    expect(list).toHaveLength(1);
    expect(list[0].kind).toBe("trend");
    expect(list[0].p1).toEqual({ index: 1, price: 100 });
    expect(list[0].p2).toEqual({ index: 5, price: 120 });
    p1.price = -1; // mutating the caller's object must not touch the drawing
    expect(list[0].p1?.price).toBe(100);
  });

  it("ignores degenerate points", () => {
    const list: Drawing[] = [];
    expect(addTrend(list, { index: Number.NaN, price: 1 }, { index: 2, price: 3 })).toBe(list);
    expect(addTrend(list, { index: 1, price: 1 }, { index: 2, price: Number.NaN })).toBe(list);
  });
});

describe("removeDrawing / clearDrawings", () => {
  it("removes only the matching id", () => {
    const a = addHline([], 10)[0];
    const b = addHline([a], 20)[1];
    const trimmed = removeDrawing([a, b], a.id);
    expect(trimmed).toHaveLength(1);
    expect(trimmed[0].id).toBe(b.id);
  });

  it("keeps the list intact for an unknown id", () => {
    const a = addHline([], 10)[0];
    const same = removeDrawing([a], "nope");
    expect(same).toHaveLength(1);
    expect(same[0]).toBe(a);
  });

  it("clearDrawings returns an empty list", () => {
    expect(clearDrawings()).toEqual([]);
  });
});

describe("hitTestDrawing", () => {
  it("hits an hline within the tolerance band and misses outside it", () => {
    const line = addHline([], 150)[0]; // y = 50
    expect(hitTestDrawing(line, 0, 50, toX, toY, 6)).toBe(true);
    expect(hitTestDrawing(line, 999, 55.9, toX, toY, 6)).toBe(true);
    expect(hitTestDrawing(line, 999, 56.1, toX, toY, 6)).toBe(false);
    expect(hitTestDrawing(line, 12, 44, toX, toY, 2)).toBe(false);
  });

  it("rejects malformed drawings and coordinates", () => {
    expect(hitTestDrawing({ id: "x", kind: "hline" }, 0, 0, toX, toY, 6)).toBe(false);
    const line = addHline([], 150)[0];
    expect(hitTestDrawing(line, Number.NaN, 50, toX, toY, 6)).toBe(false);
    expect(hitTestDrawing(line, 0, Number.NaN, toX, toY, 6)).toBe(false);
    expect(hitTestDrawing({ id: "y", kind: "trend", p1: { index: 0, price: 0 } }, 0, 0, toX, toY, 6)).toBe(
      false,
    );
  });

  it("hits a trendline near the segment (endpoints + midpoint) and misses far away", () => {
    const trend = addTrend([], { index: 1, price: 100 }, { index: 10, price: 150 })[0];
    // Endpoints map to (10, 100) and (100, 50).
    expect(hitTestDrawing(trend, 10, 100, toX, toY, 4)).toBe(true);
    expect(hitTestDrawing(trend, 100, 50, toX, toY, 4)).toBe(true);
    expect(hitTestDrawing(trend, 55, 75, toX, toY, 4)).toBe(true); // midpoint
    expect(hitTestDrawing(trend, 55, 90, toX, toY, 4)).toBe(false);
  });

  it("treats a degenerate trend (p1 == p2) as a point", () => {
    const dot = addTrend([], { index: 3, price: 77 }, { index: 3, price: 77 })[0];
    expect(hitTestDrawing(dot, 30, 123, toX, toY, 2)).toBe(true);
    expect(hitTestDrawing(dot, 30, 140, toX, toY, 2)).toBe(false);
  });

  it("clamps the segment hit to the drawn extent (no infinite extrapolation)", () => {
    const trend = addTrend([], { index: 1, price: 100 }, { index: 10, price: 150 })[0];
    // (190, 0) lies exactly on the infinite line through p1 -> p2, but beyond
    // the drawn segment, so it must miss.
    expect(hitTestDrawing(trend, 190, 0, toX, toY, 4)).toBe(false);
  });
});
