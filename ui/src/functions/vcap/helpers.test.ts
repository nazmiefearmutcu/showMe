import { describe, expect, it } from "vitest";
import { axisValue, chartGeometry, periodTime } from "./chart";
import { latestComparableDifference } from "./comparison";
import { csvCell, exportCSV, exportJSON } from "./exports";
import {
  CSV_COLUMNS,
  csvDataset,
  MAX_BYTES,
  parseCSV,
  parseImport,
  validateDataset,
} from "./imports";
import { safeReference, type Observation, type Payload } from "./types";

const dataset = {
  schema_version: 1,
  source_id: "custom_sample",
  source_name: "Licensed source",
  source_url: "https://example.org/research",
  published_at: "2026-10-01",
  methodology: "Company HQ, announced rounds",
  methodology_version: "v1",
  geography_basis: "company_hq",
  date_basis: "announced",
  sector: "all",
  observations: [
    {
      scope: "countries",
      geography: "USA",
      period: "2025",
      metric: "investment",
      stage: "total",
      unit: "USD",
      value: null,
      status: "missing",
    },
  ],
};
function row(period: string, value: number | null): Observation {
  return {
    source_id: "oecd",
    source_name: "OECD",
    scope: "countries",
    geography: "USA",
    period,
    frequency: "annual",
    metric: "investment",
    stage: "total",
    unit: "USD",
    value,
    status: value === null ? "missing" : "reported",
  };
}
function csvFor(values: Record<string, unknown>[]) {
  return [
    CSV_COLUMNS.join(","),
    ...values.map((value) =>
      CSV_COLUMNS.map((key) => {
        const text = String(value[key] ?? "");
        return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
      }).join(","),
    ),
  ].join("\r\n");
}
const record = { ...dataset, ...dataset.observations[0], value: "", coverage_note: "" };

describe("VCAP local import", () => {
  it("parses BOM, quoted commas, escaped quotes and quoted newlines", () => {
    expect(parseCSV('\uFEFFa,b\r\n"one, two","line1\nline2 with ""quote"""\r\n')).toEqual([
      ["a", "b"],
      ["one, two", 'line1\nline2 with "quote"'],
    ]);
  });
  it("preserves blank/null values as missing and numeric zero as zero", () => {
    expect(csvDataset(csvFor([record])).observations[0].value).toBeNull();
    expect(
      csvDataset(csvFor([{ ...record, value: "null" }])).observations[0].value,
    ).toBeNull();
    expect(
      csvDataset(csvFor([{ ...record, value: "0", status: "reported" }])).observations[0]
        .value,
    ).toBe(0);
  });
  it("requires repeated dataset metadata to agree exactly", () => {
    expect(() =>
      csvDataset(
        csvFor([record, { ...record, period: "2024", methodology: "Other basis" }]),
      ),
    ).toThrow(/repeated methodology/);
  });
  it("preserves comma/newline methodology and optional empty coverage", () => {
    const result = csvDataset(
      csvFor([{ ...record, methodology: 'HQ, announced\n"revised"' }]),
    );
    expect(result.methodology).toBe('HQ, announced\n"revised"');
    expect(result.observations[0]).not.toHaveProperty("coverage_note");
  });
  it("rejects malformed cells, duplicate or missing headers and invalid numeric cells", () => {
    expect(() => parseCSV('a\n"unclosed')).toThrow(/unclosed/);
    expect(() => parseCSV('a\n"closed"bad')).toThrow(/after a quoted/);
    expect(() => csvDataset("value,value\n1,2")).toThrow(/duplicate/);
    expect(() => csvDataset("value\n1")).toThrow(/Missing CSV column/);
    expect(() =>
      csvDataset(csvFor([{ ...record, value: "Infinity", status: "reported" }])),
    ).toThrow(/value must be/);
    expect(() =>
      csvDataset(csvFor([{ ...record, value: "=1+2", status: "reported" }])),
    ).toThrow(/value must be/);
  });
  it("accepts dataset JSON or API dataset wrapper; rejects missing required semantics", () => {
    expect(parseImport(JSON.stringify(dataset), "file.json")).toEqual(dataset);
    expect(parseImport(JSON.stringify({ action: "import", dataset }), "file.json")).toEqual(
      dataset,
    );
    expect(() => parseImport("{", "file.json")).toThrow(/Invalid JSON/);
    expect(() => parseImport("{}", "file.exe")).toThrow(/.json or .csv/);
    expect(() => validateDataset({ ...dataset, methodology: null })).toThrow(/methodology/);
    expect(() =>
      validateDataset({
        ...dataset,
        observations: [{ ...dataset.observations[0], value: "" }],
      }),
    ).toThrow(/finite/);
    expect(() =>
      validateDataset({
        ...dataset,
        observations: [{ ...dataset.observations[0], value: null, status: "reported" }],
      }),
    ).toThrow(/missing status/);
  });
  it("bounds file bytes and rows before backend submission", () => {
    expect(() => parseImport(" ".repeat(MAX_BYTES + 1), "large.json")).toThrow(/2 MB/);
    expect(() =>
      validateDataset({
        ...dataset,
        observations: Array.from({ length: 10001 }, () => dataset.observations[0]),
      }),
    ).toThrow(/10,000/);
  });
});
describe("VCAP export safety and provenance", () => {
  it.each(["=SUM(A1)", "+cmd", "-cmd", "@sum", "\tformula", "\rformula", " \t=1", " \ttext", "\u007ftext"])(
    "neutralizes spreadsheet text %j",
    (text) => {
      expect(csvCell(text).replace(/^"/, "").startsWith("'")).toBe(true);
    },
  );
  it("escapes commas/quotes/newlines without changing actual numbers or missing values", () => {
    expect(csvCell('a,"b"\nc')).toBe('"a,""b""\nc"');
    expect(csvCell(null)).toBe("");
    expect(csvCell(0)).toBe("0");
    expect(csvCell(-1)).toBe("-1");
  });
  it("exports exact values, status and vintage, while stripping keyed URLs and unknown fields", () => {
    const payload = {
      status: "ok",
      rows: [
        {
          ...row("2025", 131680318838.1091),
          snapshot_id: "abc",
          published_at: null,
          retrieved_at: "2026-10-31",
          source_url: "https://pro-api.llama.fi/SECRET/api/raises",
          api_key: "SECRET",
        },
      ],
      sources: [],
      snapshots: [],
    } as unknown as Payload;
    const csv = exportCSV(payload),
      json = exportJSON(payload);
    expect(csv).toContain("131680318838.1091");
    expect(csv).toContain("snapshot_id");
    expect(csv).not.toContain("SECRET");
    expect(json).not.toContain("SECRET");
    expect(JSON.parse(json).rows[0].published_at).toBeNull();
    expect(safeReference("javascript:alert(1)")).toBeUndefined();
    expect(safeReference("https://user:pass@example.org/")).toBeUndefined();
    expect(safeReference("https://example.org/report?api_key=secret#key")).toBe(
      "https://example.org/report",
    );
  });
});
describe("VCAP chronological chart geometry", () => {
  it("keeps small percent-GDP axis values distinguishable from zero", () => {
    expect(axisValue(0.000125)).toBe("0.00013");
    expect(axisValue(0)).toBe("0");
  });
  it("keeps null and absent periods as gaps on real time coordinates", () => {
    const geometry = chartGeometry([row("2023", 300), row("2020", 100), row("2021", null)]);
    expect(geometry.marks.map((mark) => mark.row.period)).toEqual(["2020", "2021", "2023"]);
    expect(geometry.marks[1].missing).toBe(true);
    expect(
      (geometry.marks[2].x - geometry.marks[1].x) /
        (geometry.marks[1].x - geometry.marks[0].x),
    ).toBeCloseTo(2, 1);
  });
  it.each([0, null, Number.NaN, Number.POSITIVE_INFINITY])(
    "handles a single observation %s with finite geometry",
    (value) => {
      const geometry = chartGeometry([row("2026", value)]);
      expect(geometry.marks).toHaveLength(1);
      expect(
        [
          geometry.marks[0].x,
          geometry.marks[0].y,
          geometry.marks[0].width,
          geometry.marks[0].height,
        ].every(Number.isFinite),
      ).toBe(true);
      expect(geometry.marks[0].missing).toBe(value !== 0);
    },
  );
  it("separates source/geography series and scales USD without rounding raw values", () => {
    const geometry = chartGeometry([
      row("2025", 4e9),
      { ...row("2025", 2e9), source_id: "custom", source_name: "Other", geography: "GBR" },
    ]);
    expect(geometry.series).toHaveLength(2);
    expect(geometry.marks[0].x).not.toBe(geometry.marks[1].x);
    expect(geometry.divisor).toBe(1e9);
    expect(geometry.axisLabel).toBe("USD billions");
    expect(periodTime(row("2025-Q3", 1))).toBe(Date.UTC(2025, 6, 1));
    expect(periodTime(row("bad", 1))).toBeNull();
  });
});
describe("VCAP comparison permission", () => {
  it("calculates only a backend-approved pair on its latest common numeric period", () => {
    const left =
      "oecd|countries|USA|investment|annual|total|USD|all|company_hq|announced|vc";
    const right = left.replace("oecd|", "other|");
    const observations = [
      {
        ...row("2024", 100),
        sector: "all",
        geography_basis: "company_hq",
        date_basis: "announced",
      },
      {
        ...row("2024", 120),
        source_id: "other",
        sector: "all",
        geography_basis: "company_hq",
        date_basis: "announced",
      },
      {
        ...row("2025", null),
        sector: "all",
        geography_basis: "company_hq",
        date_basis: "announced",
      },
      {
        ...row("2025", 999),
        source_id: "other",
        sector: "all",
        geography_basis: "company_hq",
        date_basis: "announced",
      },
    ];
    const data: Payload = {
      status: "ok",
      rows: observations,
      sources: [],
      snapshots: [],
      comparison: {
        comparable_pairs: [],
        blocked_pairs: [{ left, right, reasons: ["Independent methodology"] }],
      },
    };
    expect(latestComparableDifference(data, left, right)).toBeNull();
    data.comparison!.comparable_pairs = [{ left, right, reason: "Compatible" }];
    expect(latestComparableDifference(data, left, right)).toEqual({
      period: "2024",
      value: 20,
      unit: "USD",
    });
  });
});
