/**
 * HP indicator regression — RSI / MACD / ATR must run oldest -> newest.
 *
 * decorate() returns rows newest-first for the history table, and the right
 * rail used to feed that array straight into computeIndicators(). The EMA,
 * Wilder RSI and true-range recursions then ran backwards in time, so the
 * "last" values belonged to the oldest bar and MACD could flip sign.
 */
import { describe, expect, it } from "vitest";
import { computeIndicators } from "./HP";

type Bar = { date: string; close: number; high: number; low: number };

function makeBars(count: number): Bar[] {
  const bars: Bar[] = [];
  for (let i = 0; i < count; i++) {
    const close = 100 + i * 0.5 + 3 * Math.sin(i);
    bars.push({
      date: new Date(Date.UTC(2026, 0, 1 + i)).toISOString().slice(0, 10),
      close,
      high: close + 1,
      low: close - 1,
    });
  }
  return bars; // oldest first
}

type Input = Parameters<typeof computeIndicators>[0];

/** Independent Wilder RSI reference over an oldest-first close series. */
function referenceWilderRsiLast(closes: number[], period = 14): number {
  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    gainSum += Math.max(d, 0);
    lossSum += Math.max(-d, 0);
  }
  let avgGain = gainSum / period;
  let avgLoss = lossSum / period;
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
  }
  return avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
}

describe("HP computeIndicators is order-independent and chronological", () => {
  const chronological = makeBars(40);
  const newestFirst = [...chronological].reverse();

  it("gives the same RSI, MACD and ATR whether rows arrive newest-first or oldest-first", () => {
    const fromOldest = computeIndicators(chronological as unknown as Input);
    const fromNewest = computeIndicators(newestFirst as unknown as Input);
    expect(fromNewest.rsi).not.toBeNull();
    expect(fromNewest.rsi as number).toBeCloseTo(fromOldest.rsi as number, 9);
    expect(fromNewest.macd as number).toBeCloseTo(fromOldest.macd as number, 9);
    expect(fromNewest.atr as number).toBeCloseTo(fromOldest.atr as number, 9);
  });

  it("reports the chronological Wilder RSI for the last (newest) bar", () => {
    const closes = chronological.map((b) => b.close);
    const got = computeIndicators(newestFirst as unknown as Input);
    expect(got.rsi as number).toBeCloseTo(referenceWilderRsiLast(closes, 14), 6);
  });

  it("keeps the MACD sign of the chronological momentum on a rising series", () => {
    const rising = makeBars(60).map((b, i) => ({ ...b, close: 50 + i * 1.5, high: 51 + i * 1.5, low: 49 + i * 1.5 }));
    const got = computeIndicators([...rising].reverse() as unknown as Input);
    expect(got.macd as number).toBeGreaterThan(0);
  });

  it("sparkline series run oldest -> newest", () => {
    const fromNewest = computeIndicators(newestFirst as unknown as Input);
    const fromOldest = computeIndicators(chronological as unknown as Input);
    expect(fromNewest.rsiSpark).toEqual(fromOldest.rsiSpark);
  });
});
