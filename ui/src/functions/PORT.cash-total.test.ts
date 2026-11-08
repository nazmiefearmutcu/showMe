import { describe, expect, it } from "vitest";
import { overlayLiveTotals } from "./PORT";

type Totals = Parameters<typeof overlayLiveTotals>[0];
type Enriched = Parameters<typeof overlayLiveTotals>[1];

const enriched = [
  { symbol: "AAPL", quantity: 10, avg_cost: 100, last: 150, market_value: 1500 },
] as unknown as Enriched;

describe("overlayLiveTotals cash (PORT#2 foreign cash)", () => {
  it("adds base-currency cash that includes foreign balances", () => {
    const totals = {
      market_value: 2000,
      cost_basis: 2000,
      unrealized_pnl: 0,
      cash: 0,
      cash_total_base: 150,
    } as unknown as Totals;

    const out = overlayLiveTotals(totals, enriched, true);

    expect(out?.total_equity).toBe(1650);
  });

  it("withholds total_equity when the backend could not convert a cash balance", () => {
    const totals = {
      market_value: 2000,
      cost_basis: 2000,
      unrealized_pnl: 0,
      cash: 0,
      cash_total_base: null,
    } as unknown as Totals;

    const out = overlayLiveTotals(totals, enriched, true);

    expect(out?.total_equity).toBeNull();
  });

  it("falls back to stable cash for payloads without cash_total_base", () => {
    const totals = {
      market_value: 2000,
      cost_basis: 2000,
      unrealized_pnl: 0,
      cash: 1000,
    } as unknown as Totals;

    const out = overlayLiveTotals(totals, enriched, true);

    expect(out?.total_equity).toBe(2500);
  });
});
