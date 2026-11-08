import { describe, expect, it } from "vitest";
import { overlayLivePositions, overlayLiveTotals } from "./PORT";

type Positions = Parameters<typeof overlayLivePositions>[0];
type Totals = Parameters<typeof overlayLivePositions>[2];

const snapshot = [
  { symbol: "AAPL", quantity: 10, avg_cost: 100, last: 100, market_value: 1000 },
  { symbol: "MSFT", quantity: 10, avg_cost: 100, last: 100, market_value: 1000 },
] as unknown as Positions;

const totals = {
  market_value: 2000,
  cost_basis: 2000,
  unrealized_pnl: 0,
} as Totals;

describe("overlayLivePositions (PORT#4 live weight denominator)", () => {
  it("weights use the live-adjusted total so they still sum to 100%", () => {
    const out = overlayLivePositions(snapshot, { AAPL: { price: 150, ts: 1 } }, totals);
    const aapl = out.find((p) => p.symbol === "AAPL");
    const msft = out.find((p) => p.symbol === "MSFT");

    expect(aapl?.market_value).toBe(1500);
    // Live total is 1500 + 1000 = 2500, not the stale snapshot 2000.
    expect(aapl?.weight).toBeCloseTo(0.6, 10);
    expect(msft?.weight).toBeCloseTo(0.4, 10);
    expect((aapl?.weight ?? 0) + (msft?.weight ?? 0)).toBeCloseTo(1, 10);
  });

  it("uses the snapshot total when no live tick applies", () => {
    const out = overlayLivePositions(snapshot, {}, totals);

    expect(out[0]?.weight).toBeCloseTo(0.5, 10);
    expect(out[1]?.weight).toBeCloseTo(0.5, 10);
  });

  it("keeps the snapshot denominator when the live sum fails the sanity guard", () => {
    // A live sum more than 3x the snapshot is treated as bad data, the same
    // guard liveTotals applies, so the snapshot total stays the denominator.
    const out = overlayLivePositions(snapshot, { AAPL: { price: 1_000_000, ts: 1 } }, totals);

    expect(out[1]?.weight).toBeCloseTo(1000 / 2000, 10);
  });
});

describe("overlayLiveTotals (PORT#2 total equity under the live overlay)", () => {
  const withCash = {
    market_value: 2000,
    cost_basis: 2000,
    unrealized_pnl: 0,
    cash: 500,
    total_equity: 2500,
  } as Totals;

  it("recomputes total_equity from live market value plus cash", () => {
    const enriched = overlayLivePositions(snapshot, { AAPL: { price: 150, ts: 1 } }, withCash);
    const out = overlayLiveTotals(withCash, enriched, true);

    expect(out?.market_value).toBe(2500);
    // The snapshot equity (2500) must not survive while the marks move.
    expect(out?.total_equity).toBe(3000);
  });

  it("returns the snapshot totals unchanged without a live overlay", () => {
    expect(overlayLiveTotals(withCash, snapshot, false)).toBe(withCash);
  });

  it("withholds total_equity when cash is not tracked", () => {
    const noCash = { market_value: 2000, cost_basis: 2000, unrealized_pnl: 0, total_equity: null } as Totals;
    const enriched = overlayLivePositions(snapshot, { AAPL: { price: 150, ts: 1 } }, noCash);

    expect(overlayLiveTotals(noCash, enriched, true)?.total_equity).toBeNull();
  });

  it("keeps the snapshot reference when the live sum fails the sanity guard", () => {
    const enriched = overlayLivePositions(snapshot, { AAPL: { price: 1_000_000, ts: 1 } }, withCash);

    expect(overlayLiveTotals(withCash, enriched, true)).toBe(withCash);
  });
});
