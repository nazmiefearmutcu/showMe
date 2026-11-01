import type { Observation, Payload } from "./types";
import { safeReference } from "./types";

const FIELDS: (keyof Observation)[] = [
  "period",
  "period_start",
  "period_end",
  "source_id",
  "source_name",
  "scope",
  "geography",
  "frequency",
  "metric",
  "stage",
  "unit",
  "value",
  "status",
  "is_partial",
  "coverage_cutoff",
  "published_at",
  "retrieved_at",
  "snapshot_id",
  "vintage",
  "methodology_version",
  "methodology",
  "geography_basis",
  "date_basis",
  "sector",
  "financing_scope",
  "coverage_note",
  "source_url",
  "data_mode",
  "underlying_access_date",
  "publication_id",
  "publication_table",
  "global_total_basis",
];
export function csvCell(value: unknown): string {
  if (value == null) return "";
  let text = String(value);
  // Text only: real numeric values retain their type/value in exports.
  const isControl = (ch: string) =>
    ch.charCodeAt(0) <= 31 || (ch.charCodeAt(0) >= 127 && ch.charCodeAt(0) <= 159);
  let prefix = 0;
  let controlPrefix = false;
  while (prefix < text.length && (/\s/.test(text[prefix]) || isControl(text[prefix]))) {
    controlPrefix ||= isControl(text[prefix]);
    prefix += 1;
  }
  if (
    typeof value === "string" &&
    ("=+-@".includes(text[prefix] ?? "\uffff") || controlPrefix)
  )
    text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
function exportRows(payload: Payload) {
  return payload.rows.map((row) =>
    Object.fromEntries(
      FIELDS.map((key) => [
        key,
        key === "source_url" ? (safeReference(row[key]) ?? null) : (row[key] ?? null),
      ]),
    ),
  );
}
export function exportCSV(payload: Payload): string {
  return [
    FIELDS.join(","),
    ...exportRows(payload).map((row) => FIELDS.map((key) => csvCell(row[key])).join(",")),
  ].join("\r\n");
}
export function exportJSON(payload: Payload): string {
  return JSON.stringify(
    {
      query: payload.query,
      status: payload.status,
      methodology: payload.methodology,
      coverage: payload.coverage,
      rows: exportRows(payload),
      comparison: payload.comparison,
      sources: payload.sources.map((source) => ({
        source_id: source.source_id,
        source_name: source.source_name,
        access_mode: source.access_mode,
        access_status: source.access_status,
        source_url: safeReference(source.source_url),
        terms_url: safeReference(source.terms_url),
        lineage: source.lineage,
        validation_summary: source.validation_summary,
        published_at: source.published_at,
        underlying_access_date: source.underlying_access_date,
      })),
      snapshots: payload.snapshots,
    },
    null,
    2,
  );
}
export function download(contents: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
