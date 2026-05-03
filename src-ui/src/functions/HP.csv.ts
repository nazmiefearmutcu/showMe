export interface HPRow {
  date?: string;
  ts?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  adj_close?: number;
  adjClose?: number;
  volume?: number;
}

export function buildCsv(rows: HPRow[]): string {
  const header = ["date", "open", "high", "low", "close", "adj_close", "volume"];
  const lines = [header.join(",")];
  for (const r of rows) {
    lines.push(
      [
        csvCell(fmtDate(r.date ?? r.ts)),
        csvCell(r.open),
        csvCell(r.high),
        csvCell(r.low),
        csvCell(r.close),
        csvCell(r.adj_close ?? r.adjClose),
        csvCell(r.volume),
      ].join(","),
    );
  }
  return lines.join("\n");
}

function fmtDate(v: string | undefined): string {
  if (!v) return "—";
  try {
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return v.slice(0, 10);
    return d.toISOString().slice(0, 10);
  } catch {
    return v;
  }
}

function csvCell(v: unknown): string {
  if (v == null || v === "") return "";
  const s = String(v);
  if (s.includes(",") || s.includes('"') || s.includes("\n")) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}
