import type { StateTrade } from "@/lib/state";

export function buildTradeCsv(rows: StateTrade[]): string {
  const header = [
    "trade_id",
    "symbol",
    "side",
    "quantity",
    "entry_price",
    "exit_price",
    "realized_pnl",
    "opened_at",
    "closed_at",
    "mode",
  ];
  const lines = [header.join(",")];
  for (const r of rows) {
    lines.push(
      [
        csvCell(r.trade_id),
        csvCell(r.symbol),
        csvCell(r.side),
        csvCell(r.quantity),
        csvCell(r.entry_price),
        csvCell(r.exit_price),
        csvCell(r.realized_pnl),
        csvCell(r.opened_at),
        csvCell(r.closed_at),
        csvCell(r.mode),
      ].join(","),
    );
  }
  return lines.join("\n");
}

function csvCell(v: unknown): string {
  if (v == null || v === "") return "";
  const s = String(v);
  if (s.includes(",") || s.includes('"') || s.includes("\n")) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}
