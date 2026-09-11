/**
 * Grid CSV helpers — the shared export path for DataGrid-backed panes.
 *
 * Panes used to hand-roll per-pane CSV builders (`HP.csv.ts`, `TXNS.csv.ts`).
 * New panes (EVTS and friends) use these generic helpers instead:
 *
 *   const csv = buildGridCsv(columns, rows);
 *   downloadGridCsv(`evts-${symbol}.csv`, csv);
 *
 * `columns[].value` is the export accessor (raw numbers preferred over
 * formatted strings — spreadsheets should receive numbers, not "1,234.50").
 */
export interface GridCsvColumn<T> {
  key: string;
  /** CSV header label (plain text). */
  header: string;
  /** Raw value accessor; defaults to `row[column.key]`. */
  value?: (row: T) => unknown;
}

/** RFC-4180-ish escaping: quote when the field contains , " \r or \n. */
export function csvEscape(value: unknown): string {
  let text: string;
  if (value == null) text = "";
  else if (typeof value === "number") text = Number.isFinite(value) ? String(value) : "";
  else if (typeof value === "boolean") text = value ? "true" : "false";
  else if (Array.isArray(value)) text = value.map((v) => (v == null ? "" : String(v))).join(" / ");
  else text = String(value);
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

/** Build the full CSV document (header row + one row per record). */
export function buildGridCsv<T>(columns: GridCsvColumn<T>[], rows: T[]): string {
  const header = columns.map((c) => csvEscape(c.header)).join(",");
  const lines = rows.map((row) =>
    columns
      .map((c) => {
        const raw = c.value
          ? c.value(row)
          : (row as unknown as Record<string, unknown>)[c.key];
        return csvEscape(raw);
      })
      .join(","),
  );
  return [header, ...lines].join("\n");
}

/**
 * Trigger a client-side CSV download. Returns false in environments with no
 * Blob/URL support (jsdom) instead of throwing — callers stay crash-free.
 */
export function downloadGridCsv(filename: string, csv: string): boolean {
  if (typeof document === "undefined" || typeof URL === "undefined") return false;
  if (typeof URL.createObjectURL !== "function") return false;
  try {
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 0);
    return true;
  } catch {
    return false;
  }
}

/** Dated export filename: `<base>-YYYY-MM-DD.csv`. */
export function gridCsvFilename(base: string, now: Date = new Date()): string {
  return `${base}-${now.toISOString().slice(0, 10)}.csv`;
}
