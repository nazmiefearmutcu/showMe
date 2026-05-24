/**
 * UA-HIGH-10 — PORT.tsx field-name drift between exchange adapters.
 *
 * Some exchanges emit `entry_price` / `current_price`; others emit `avg_cost`
 * / `last`. The PORT row renderer used the first pair only, so positions
 * from the second group rendered as `—` for both columns. The tolerant
 * accessors fix this by falling back across the two name pairs.
 */
import { describe, expect, it } from "vitest";

// Mirror of the PORT.tsx helpers — exported via the interface barrel would
// be ideal but keeping this self-contained avoids dragging React + design
// system into the unit test.
interface Position {
  symbol: string;
  avg_cost?: number;
  entry_price?: number;
  last?: number;
  current_price?: number;
}

function positionEntryPrice(p: Position): number | undefined {
  const v = p.entry_price ?? p.avg_cost;
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}
function positionCurrentPrice(p: Position): number | undefined {
  const v = p.current_price ?? p.last;
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

describe("UA-HIGH-10: PORT field-name drift", () => {
  it("reads entry_price when present", () => {
    expect(positionEntryPrice({ symbol: "AAPL", entry_price: 100 })).toBe(100);
  });

  it("falls back to avg_cost when entry_price is missing", () => {
    expect(positionEntryPrice({ symbol: "AAPL", avg_cost: 95 })).toBe(95);
  });

  it("prefers entry_price over avg_cost when both are present", () => {
    expect(
      positionEntryPrice({ symbol: "AAPL", entry_price: 100, avg_cost: 95 }),
    ).toBe(100);
  });

  it("returns undefined when neither price field is set", () => {
    expect(positionEntryPrice({ symbol: "AAPL" })).toBeUndefined();
  });

  it("returns undefined for non-finite price values", () => {
    expect(positionEntryPrice({ symbol: "AAPL", entry_price: Infinity })).toBeUndefined();
    expect(positionEntryPrice({ symbol: "AAPL", avg_cost: NaN })).toBeUndefined();
  });

  it("current_price drift falls back to last", () => {
    expect(positionCurrentPrice({ symbol: "AAPL", last: 110 })).toBe(110);
    expect(positionCurrentPrice({ symbol: "AAPL", current_price: 120, last: 110 })).toBe(120);
    expect(positionCurrentPrice({ symbol: "AAPL" })).toBeUndefined();
  });
});
