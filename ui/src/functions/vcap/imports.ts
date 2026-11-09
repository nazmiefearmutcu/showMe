import type { Dataset } from "./types";

export const MAX_BYTES = 2_000_000;
export const MAX_ROWS = 10_000;
export const METADATA_COLUMNS = [
  "schema_version",
  "source_id",
  "source_name",
  "source_url",
  "published_at",
  "methodology",
  "methodology_version",
  "geography_basis",
  "date_basis",
  "sector",
];
export const OBSERVATION_COLUMNS = [
  "scope",
  "geography",
  "period",
  "metric",
  "stage",
  "unit",
  "value",
  "status",
  "coverage_note",
  "financing_scope",
];
export const CSV_COLUMNS = [...METADATA_COLUMNS, ...OBSERVATION_COLUMNS];

/** RFC 4180 cells, including BOM, escaped quotes and embedded newlines. */
export function parseCSV(text: string): string[][] {
  if (new TextEncoder().encode(text).length > MAX_BYTES)
    throw new Error("File exceeds 2 MB.");
  const input = text.replace(/^\uFEFF/, "");
  const rows: string[][] = [];
  let row: string[] = [],
    cell = "",
    quoted = false,
    closed = false;
  const finishRow = () => {
    row.push(cell);
    cell = "";
    closed = false;
    if (row.some((value) => value.trim() !== "")) rows.push(row);
    row = [];
    if (rows.length > MAX_ROWS + 1) throw new Error("CSV exceeds 10,000 observations.");
  };
  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i];
    if (quoted) {
      if (ch === '"') {
        if (input[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
          closed = true;
        }
      } else cell += ch;
    } else if (ch === '"') {
      if (cell !== "" || closed)
        throw new Error(`Unexpected quote near CSV row ${rows.length + 1}.`);
      quoted = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
      closed = false;
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && input[i + 1] === "\n") i += 1;
      finishRow();
    } else {
      if (closed)
        throw new Error(
          `Unexpected text after a quoted CSV cell near row ${rows.length + 1}.`,
        );
      cell += ch;
    }
  }
  if (quoted) throw new Error("CSV has an unclosed quoted cell.");
  if (cell !== "" || row.length || closed) finishRow();
  return rows;
}

export function csvDataset(text: string): Dataset {
  const [rawHeader, ...rows] = parseCSV(text);
  if (!rawHeader || !rows.length)
    throw new Error("CSV needs the template header and at least one observation.");
  const header = rawHeader.map((value) => value.trim());
  if (new Set(header).size !== header.length)
    throw new Error("CSV has duplicate column names.");
  const required = CSV_COLUMNS.filter(
    (key) => !["source_name", "coverage_note", "financing_scope"].includes(key),
  );
  for (const name of required)
    if (!header.includes(name)) throw new Error(`Missing CSV column: ${name}.`);
  const records = rows.map((row, index) => {
    if (row.length !== header.length)
      throw new Error(
        `CSV row ${index + 2} has ${row.length} cells; expected ${header.length}.`,
      );
    return Object.fromEntries(header.map((key, i) => [key, row[i]]));
  });
  const first = records[0];
  for (const [index, record] of records.entries()) {
    for (const key of METADATA_COLUMNS)
      if ((record[key] ?? "") !== (first[key] ?? ""))
        throw new Error(
          `CSV row ${index + 2}: repeated ${key} must match the first observation.`,
        );
  }
  const metadata = Object.fromEntries(
    METADATA_COLUMNS.map((key) => [key, first[key] ?? ""]),
  );
  const observations = records.map((record, index) => {
    const value = record.value.trim();
    if (
      value !== "" &&
      value.toLowerCase() !== "null" &&
      !/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value)
    )
      throw new Error(
        `CSV row ${index + 2}: value must be a nonnegative number, blank or null.`,
      );
    return Object.fromEntries(
      OBSERVATION_COLUMNS.flatMap<[string, unknown]>((key) => {
        if (key === "value")
          return [
            [key, value === "" || value.toLowerCase() === "null" ? null : Number(value)],
          ];
        if (["coverage_note", "financing_scope"].includes(key) && !record[key]?.trim())
          return [];
        return [[key, record[key]]];
      }),
    );
  });
  return validateDataset({
    ...metadata,
    schema_version: Number(metadata.schema_version),
    observations,
  });
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
export function validateDataset(value: unknown): Dataset {
  if (!object(value)) throw new Error("JSON must contain a dataset object.");
  if (value.schema_version !== 1) throw new Error("schema_version must be 1.");
  for (const field of METADATA_COLUMNS.filter(
    (key) => !["schema_version", "source_name"].includes(key),
  )) {
    if (typeof value[field] !== "string" || !value[field].trim())
      throw new Error(`Fill in dataset ${field}.`);
  }
  if (!Array.isArray(value.observations) || !value.observations.length)
    throw new Error("Add at least one observation to the dataset.");
  if (value.observations.length > MAX_ROWS)
    throw new Error("Dataset exceeds 10,000 observations.");
  for (const [i, obs] of value.observations.entries()) {
    if (!object(obs)) throw new Error(`Observation ${i + 1} must be an object.`);
    for (const key of [
      "scope",
      "geography",
      "period",
      "metric",
      "stage",
      "unit",
      "status",
    ]) {
      if (typeof obs[key] !== "string" || !obs[key])
        throw new Error(`Observation ${i + 1}: ${key} is required.`);
    }
    if (!(
      obs.value === null ||
      (typeof obs.value === "number" && Number.isFinite(obs.value) && obs.value >= 0)
    ))
      throw new Error(
        `Observation ${i + 1}: value must be a finite nonnegative number or null.`,
      );
    if ((obs.value === null) !== (obs.status === "missing"))
      throw new Error(
        `Observation ${i + 1}: a null value requires missing status, and missing status requires null.`,
      );
  }
  if (new TextEncoder().encode(JSON.stringify(value)).length > MAX_BYTES)
    throw new Error("Dataset exceeds the 2 MB JSON limit.");
  return value as unknown as Dataset;
}
export function parseImport(text: string, filename: string): Dataset {
  if (new TextEncoder().encode(text).length > MAX_BYTES)
    throw new Error("File exceeds 2 MB.");
  if (filename.toLowerCase().endsWith(".csv")) return csvDataset(text);
  if (!filename.toLowerCase().endsWith(".json"))
    throw new Error("Choose a .json or .csv file.");
  let raw: unknown;
  try {
    raw = JSON.parse(text.replace(/^\uFEFF/, ""));
  } catch {
    throw new Error("Invalid JSON. Check quotes, commas and the dataset wrapper.");
  }
  return validateDataset(object(raw) && "dataset" in raw ? raw.dataset : raw);
}
export function emptyJSONTemplate(sourceId: string) {
  return JSON.stringify(
    {
      schema_version: 1,
      source_id: sourceId === "custom" ? "custom_example" : sourceId,
      source_name: null,
      source_url: null,
      published_at: null,
      methodology: null,
      methodology_version: null,
      geography_basis: null,
      date_basis: null,
      sector: null,
      observations: [],
    },
    null,
    2,
  );
}
