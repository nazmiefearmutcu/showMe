/**
 * HNT-07 — `rowsToTimePoints` must hand lightweight-charts ONE Time type
 * per series. A date column mixing date-only cells ("2026-01-15" → string
 * BusinessDay) with date-time cells ("2026-01-16 00:00" → unix-seconds
 * number) used to produce a mixed series, and the sort compared
 * Date.parse milliseconds against unix seconds — `setData` could assert
 * and the series could draw mis-ordered. When both kinds are present the
 * series is normalized to unix-seconds numbers.
 */
import { describe, expect, it } from "vitest";
import { normalizeChartTime, rowsToTimePoints } from "./chart-extract";

describe("rowsToTimePoints — Time type consistency (HNT-07)", () => {
  it("normalizes a mixed date-only / date-time column to unix-seconds numbers, sorted", () => {
    const points = rowsToTimePoints(
      [
        { date: "2026-01-16 00:00", value: 3 },
        { date: "2026-01-15", value: 1 },
        { date: "2026-01-17 09:30", value: 2 },
      ],
      "date",
      "value",
      false,
    );
    expect(points).toHaveLength(3);
    for (const point of points) {
      expect(typeof point.time).toBe("number");
    }
    const times = points.map((p) => p.time as number);
    expect([...times].sort((a, b) => a - b)).toEqual(times);
    /* Sorted by TIME, not by input order: the 15th (date-only cell) sorts
       before the 16th despite being the string-typed row. */
    expect(points.map((p) => p.y)).toEqual([1, 3, 2]);
  });

  it("keeps a pure date-only column as string BusinessDays", () => {
    const points = rowsToTimePoints(
      [
        { date: "2026-01-02", value: 2 },
        { date: "2026-01-01", value: 1 },
      ],
      "date",
      "value",
      false,
    );
    expect(points.map((p) => p.time)).toEqual(["2026-01-01", "2026-01-02"]);
    expect(points.map((p) => p.y)).toEqual([1, 2]);
  });

  it("keeps a pure date-time column as unix-seconds numbers", () => {
    const points = rowsToTimePoints(
      [
        { date: "2026-01-02 00:00", value: 2 },
        { date: "2026-01-01 00:00", value: 1 },
      ],
      "date",
      "value",
      false,
    );
    for (const point of points) {
      expect(typeof point.time).toBe("number");
    }
    expect(points.map((p) => p.y)).toEqual([1, 2]);
  });

  it("normalizes mixed OHLC rows too (open/high/low/close survive)", () => {
    const points = rowsToTimePoints(
      [
        { date: "2026-01-16 00:00", open: 2, high: 4, low: 1, close: 3 },
        { date: "2026-01-15", open: 1, high: 2, low: 0.5, close: 2 },
      ],
      "date",
      "close",
      true,
    );
    expect(points).toHaveLength(2);
    for (const point of points) {
      expect(typeof point.time).toBe("number");
      expect(point.open).toBeDefined();
      expect(point.high).toBeDefined();
      expect(point.low).toBeDefined();
      expect(point.close).toBeDefined();
    }
    expect(points.map((p) => p.close)).toEqual([2, 3]);
  });
});

describe("normalizeChartTime — scalar contract", () => {
  it("passes unix seconds through and down-converts unix milliseconds", () => {
    expect(normalizeChartTime(1_700_000_000)).toBe(1_700_000_000);
    expect(normalizeChartTime(1_700_000_000_000)).toBe(1_700_000_000);
  });

  it("maps a strict date-only string to a BusinessDay string and anything richer to a number", () => {
    expect(normalizeChartTime("2026-01-15")).toBe("2026-01-15");
    expect(typeof normalizeChartTime("2026-01-15 09:30")).toBe("number");
    expect(typeof normalizeChartTime("2026-01-15T09:30:00Z")).toBe("number");
  });

  it("returns null for garbage", () => {
    expect(normalizeChartTime("not a date")).toBeNull();
    expect(normalizeChartTime("")).toBeNull();
    expect(normalizeChartTime(undefined)).toBeNull();
  });
});
