import { describe, expect, it } from "vitest";
import { buildTradeCsv } from "./TXNS.csv";
import type { StateTrade } from "@/lib/state";

const sample: StateTrade[] = [
  {
    id: 1,
    trade_id: "t1",
    symbol: "AAPL",
    side: "LONG",
    quantity: 10,
    entry_price: 180,
    exit_price: 195,
    realized_pnl: 150,
    opened_at: "2026-04-01T10:00:00Z",
    closed_at: "2026-04-15T16:00:00Z",
    mode: "read_only",
    source: "showme_import",
  },
  {
    id: 2,
    trade_id: "t,with,commas",
    symbol: "MSFT",
    side: "SHORT",
    quantity: 5,
    realized_pnl: -50,
    mode: "writable",
  },
];

describe("TXNS buildTradeCsv", () => {
  it("emits the canonical header row", () => {
    const lines = buildTradeCsv([]).split("\n");
    expect(lines[0]).toBe(
      "trade_id,symbol,side,quantity,entry_price,exit_price,realized_pnl,opened_at,closed_at,mode,source",
    );
  });

  it("renders a fully-populated row with raw numeric cells", () => {
    const lines = buildTradeCsv([sample[0]]).split("\n");
    expect(lines[1]).toBe(
      "t1,AAPL,LONG,10,180,195,150,2026-04-01T10:00:00Z,2026-04-15T16:00:00Z,read_only,showme_import",
    );
  });

  it("RFC4180 escapes commas inside trade_id", () => {
    const lines = buildTradeCsv([sample[1]]).split("\n");
    expect(lines[1].startsWith('"t,with,commas",MSFT,SHORT,5,,,-50,,,writable')).toBe(true);
  });
});
