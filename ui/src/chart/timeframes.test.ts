import { describe, expect, it } from "vitest";
import type { Bar } from "./types";
import {
  TIMEFRAMES,
  liveRefreshMsFor,
  resampleBars,
  timeframeById,
  timeframeSeconds,
} from "./timeframes";

function minuteBars(count: number, startMs = 0): Bar[] {
  return Array.from({ length: count }, (_, i) => {
    const base = 100 + i;
    return {
      t: startMs + i * 60_000,
      o: base,
      h: base + 1,
      l: base - 1,
      c: base + 0.5,
      v: i + 1,
    };
  });
}

describe("TIMEFRAMES catalog", () => {
  it("covers every requested interval with at least 16 entries", () => {
    expect(TIMEFRAMES.length).toBeGreaterThanOrEqual(16);
    const ids = TIMEFRAMES.map((tf) => tf.id);
    for (const expected of [
      "1s",
      "5s",
      "15s",
      "30s",
      "1m",
      "3m",
      "5m",
      "15m",
      "30m",
      "1h",
      "2h",
      "4h",
      "6h",
      "8h",
      "12h",
      "1D",
      "1W",
      "1M",
    ]) {
      expect(ids).toContain(expected);
    }
  });

  it("has unique ids and provider === id", () => {
    const ids = TIMEFRAMES.map((tf) => tf.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const tf of TIMEFRAMES) {
      expect(tf.provider).toBe(tf.id);
      expect(tf.label.length).toBeGreaterThan(0);
      expect(tf.seconds).toBeGreaterThan(0);
      expect(Number.isFinite(tf.seconds)).toBe(true);
    }
  });

  it("keeps the conventional duration constants", () => {
    expect(timeframeSeconds("1m")).toBe(60);
    expect(timeframeSeconds("1h")).toBe(3600);
    expect(timeframeSeconds("1D")).toBe(86_400);
    expect(timeframeSeconds("1W")).toBe(7 * 86_400);
    expect(timeframeSeconds("1M")).toBe(30 * 86_400);
  });

  it("looks up by exact id and rejects unknown / wrong case", () => {
    expect(timeframeById("15m")?.seconds).toBe(900);
    expect(timeframeById("nope")).toBeUndefined();
    expect(timeframeSeconds("nope")).toBeNull();
    // "1m" and "1M" are distinct instruments; lookup must not confuse them.
    expect(timeframeSeconds("1m")).toBe(60);
    expect(timeframeSeconds("1M")).toBe(30 * 86_400);
  });
});

describe("resampleBars", () => {
  it("aggregates 60 x 1m bars into one 1h OHLCV bar", () => {
    const bars = minuteBars(60);
    const out = resampleBars(bars, 3600);
    expect(out).toHaveLength(1);
    expect(out[0].t).toBe(0);
    expect(out[0].o).toBe(100);
    expect(out[0].h).toBe(159 + 1);
    expect(out[0].l).toBe(99);
    expect(out[0].c).toBe(159.5);
    expect(out[0].v).toBe((60 * 61) / 2);
  });

  it("splits on exact bucket boundaries", () => {
    const bars = minuteBars(120);
    const out = resampleBars(bars, 3600);
    expect(out).toHaveLength(2);
    expect(out[0].t).toBe(0);
    expect(out[1].t).toBe(3_600_000);
    expect(out[0].c).toBe(bars[59].c);
    expect(out[1].o).toBe(bars[60].o);
    expect(out[1].c).toBe(bars[119].c);
  });

  it("aligns buckets with a non-aligned first bar", () => {
    const bars = minuteBars(10, 90_000);
    const out = resampleBars(bars, 300);
    // buckets: [0, 300k) -> 90k/150k/210k/270k, [300k, 600k) -> 5 bars, [600k) -> 1 bar
    expect(out.map((b) => b.t)).toEqual([0, 300_000, 600_000]);
    expect(out[0].o).toBe(100);
    expect(out[0].c).toBe(bars[3].c);
    expect(out[1].o).toBe(bars[4].o);
    expect(out[1].c).toBe(bars[8].c);
    expect(out[2].c).toBe(bars[9].c);
    for (const b of out) {
      expect(b.t % 300_000).toBe(0);
    }
  });

  it("passes through when the target is not coarser than the source spacing", () => {
    const bars = minuteBars(5);
    const same = resampleBars(bars, 60);
    expect(same).toHaveLength(5);
    expect(same.map((b) => b.t)).toEqual(bars.map((b) => b.t));
    expect(same).not.toBe(bars);

    const finer = resampleBars(bars, 30);
    expect(finer).toHaveLength(5);
    expect(finer.map((b) => b.c)).toEqual(bars.map((b) => b.c));
  });

  it("returns a sorted copy without mutating the input", () => {
    const bars = minuteBars(3).reverse();
    const original = bars.map((b) => b.t);
    const out = resampleBars(bars, 60);
    expect(out.map((b) => b.t)).toEqual([0, 60_000, 120_000]);
    expect(bars.map((b) => b.t)).toEqual(original);
  });

  it("returns an empty array for empty input", () => {
    expect(resampleBars([], 3600)).toEqual([]);
  });

  it("returns a single bar untouched (sorted copy)", () => {
    const bars = minuteBars(1);
    const out = resampleBars(bars, 3600);
    expect(out).toEqual(bars);
    expect(out).not.toBe(bars);
  });
});

describe("liveRefreshMsFor", () => {
  it("polls EVERY timeframe at 500 ms so no chart reads as a stale website", () => {
    /* Owner: "500ms bütün kapanış zamanları için geçerli olsun". The helper
       no longer varies by interval - every horizon ticks at the same
       real-time cadence, backed by the interval/source-aware cache. */
    expect(liveRefreshMsFor(30_000)).toBe(500);
    expect(liveRefreshMsFor(60_000)).toBe(500);
    expect(liveRefreshMsFor(120_000)).toBe(500);
  });

  it("never exceeds the caller's cadence and never drops below 250 ms", () => {
    expect(liveRefreshMsFor(1_000)).toBe(500);
    expect(liveRefreshMsFor(100)).toBe(250);
  });
});
