/**
 * GP RSI regression — Wilder seed must be an average, not a sum.
 *
 * The pre-fix rsiSeries seeded the Wilder recurrence with the SUM of the
 * first `period` gains/losses. The RSI ratio at the seed bar is unaffected,
 * but the carried state stays 14x too large and decays only as (13/14)^n,
 * so short windows (1M = 21 bars) showed an RSI many points too high.
 */
import { describe, expect, it } from "vitest";
import { rsiSeries } from "./GP";

// Classic 21-bar close series (Wilder-style RSI(14) worked example).
const CLOSES = [
  44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.1, 45.42, 45.84, 46.08, 45.89,
  46.03, 45.61, 46.28, 46.28, 46.0, 46.03, 46.41, 46.22, 45.64, 46.21,
];

/** Independent reference: SMA seed over the first `period` changes, then
 *  Wilder smoothing avg = (prev * (period - 1) + current) / period. */
function referenceWilderRsi(closes: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  const rsiOf = (avgGain: number, avgLoss: number) =>
    avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    gainSum += Math.max(d, 0);
    lossSum += Math.max(-d, 0);
  }
  let avgGain = gainSum / period;
  let avgLoss = lossSum / period;
  out[period] = rsiOf(avgGain, avgLoss);
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = rsiOf(avgGain, avgLoss);
  }
  return out;
}

describe("GP rsiSeries (Wilder RSI, average seed)", () => {
  it("matches the Wilder reference on every bar of a 21-bar window", () => {
    const got = rsiSeries(CLOSES, 14);
    const want = referenceWilderRsi(CLOSES, 14);
    expect(got).toHaveLength(CLOSES.length);
    for (let i = 0; i < CLOSES.length; i++) {
      if (want[i] == null) {
        expect(got[i]).toBeNull();
      } else {
        expect(got[i], `bar ${i}`).toBeCloseTo(want[i] as number, 6);
      }
    }
  });

  it("reports the Wilder value on the last bar of the short window", () => {
    const got = rsiSeries(CLOSES, 14);
    const want = referenceWilderRsi(CLOSES, 14);
    expect(got[CLOSES.length - 1] as number).toBeCloseTo(
      want[CLOSES.length - 1] as number,
      6,
    );
  });
});
