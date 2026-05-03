import { describe, expect, it } from "vitest";
import { buildCsv } from "./HP.csv";

describe("HP buildCsv", () => {
  it("emits the header even when rows are empty", () => {
    const csv = buildCsv([]);
    expect(csv.split("\n")).toEqual([
      "date,open,high,low,close,adj_close,volume",
    ]);
  });

  it("formats date to ISO-day and preserves numeric precision", () => {
    const csv = buildCsv([
      {
        date: "2026-04-15T00:00:00Z",
        open: 100,
        high: 110,
        low: 95,
        close: 108,
        adj_close: 108,
        volume: 1_500_000,
      },
    ]);
    const lines = csv.split("\n");
    expect(lines[1]).toBe("2026-04-15,100,110,95,108,108,1500000");
  });

  it("escapes commas and quotes per RFC4180", () => {
    const csv = buildCsv([
      {
        date: "2026-04-30",
        open: 1,
        close: 1,
        // sneak a comma + embedded quote into a numeric-shaped string slot
        // by abusing volume: the helper coerces via String().
        volume: 'oops,"weird"' as unknown as number,
      },
    ]);
    const lines = csv.split("\n");
    // Embedded quotes doubled, comma forces quoted cell.
    expect(lines[1]).toContain('"oops,""weird"""');
  });

  it("substitutes adjClose camelCase when adj_close is missing", () => {
    const csv = buildCsv([
      {
        date: "2026-04-30",
        close: 5,
        adjClose: 4.95,
      },
    ]);
    expect(csv.split("\n")[1]).toBe("2026-04-30,,,,5,4.95,");
  });
});
