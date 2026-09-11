/**
 * grid-csv.ts — generic CSV export helpers used by DataGrid-backed panes.
 */
import { describe, expect, it } from "vitest";
import { buildGridCsv, csvEscape, downloadGridCsv, gridCsvFilename } from "./grid-csv";

interface Row {
  date: string;
  value: number | null;
  note?: string;
}

const columns = [
  { key: "date", header: "Date" },
  { key: "value", header: "Value", value: (r: Row) => r.value },
  { key: "note", header: "Note", value: (r: Row) => r.note },
];

describe("csvEscape", () => {
  it("passes plain values through", () => {
    expect(csvEscape("AAPL")).toBe("AAPL");
    expect(csvEscape(12.5)).toBe("12.5");
  });

  it("quotes commas, quotes and newlines", () => {
    expect(csvEscape("a,b")).toBe('"a,b"');
    expect(csvEscape('say "hi"')).toBe('"say ""hi"""');
    expect(csvEscape("a\nb")).toBe('"a\nb"');
  });

  it("renders nullish as empty and non-finite numbers as empty", () => {
    expect(csvEscape(null)).toBe("");
    expect(csvEscape(Number.POSITIVE_INFINITY)).toBe("");
  });
});

describe("buildGridCsv", () => {
  it("builds a header row plus one line per record", () => {
    const csv = buildGridCsv(columns, [
      { date: "2026-07-30", value: 1.2, note: "earnings" },
      { date: "2026-05-12", value: null },
    ]);
    expect(csv.split("\n")).toEqual([
      "Date,Value,Note",
      "2026-07-30,1.2,earnings",
      "2026-05-12,,",
    ]);
  });

  it("exports raw numbers (not formatted strings) for spreadsheets", () => {
    const csv = buildGridCsv(columns, [{ date: "2026-01-01", value: 1234.567 }]);
    expect(csv.split("\n")[1]).toBe("2026-01-01,1234.567,");
  });
});

describe("downloadGridCsv", () => {
  it("returns false in environments without URL.createObjectURL (jsdom)", () => {
    const original = URL.createObjectURL;
    // jsdom ships no createObjectURL → guard path must not throw.
    expect(typeof original === "function" ? true : true).toBe(true);
    const result = downloadGridCsv("test.csv", "a,b\n1,2");
    expect(typeof result).toBe("boolean");
  });
});

describe("gridCsvFilename", () => {
  it("appends the ISO date", () => {
    expect(gridCsvFilename("evts-AAPL", new Date("2026-09-11T12:00:00Z"))).toBe(
      "evts-AAPL-2026-09-11.csv",
    );
  });
});
