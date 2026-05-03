/**
 * HP — Historical price (Bloomberg HP<GO> analogue).
 *
 * Symbol + range selector → OHLCV table with CSV export. Range presets
 * mirror ShowMe (`1M / 3M / 6M / 1Y / 5Y / max`) and the table is sortable
 * with a Download CSV button that uses an in-memory Blob — no sidecar
 * round-trip required.
 */
import { useMemo } from "react";
import {
  ChangeText,
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { SymbolBar } from "@/shell/SymbolBar";
import { buildCsv, type HPRow } from "./HP.csv";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const RANGES = [
  { id: "1M", label: "1M", days: 30 },
  { id: "3M", label: "3M", days: 90 },
  { id: "6M", label: "6M", days: 180 },
  { id: "1Y", label: "1Y", days: 365 },
  { id: "5Y", label: "5Y", days: 365 * 5 },
  { id: "max", label: "Max", days: 365 * 25 },
] as const;
type RangeId = (typeof RANGES)[number]["id"];
const RANGE_IDS = RANGES.map((r) => r.id);

const COLS: DataGridColumn<HPRow & { _change?: number; _changePct?: number }>[] =
  [
    {
      key: "date",
      header: "Date",
      width: 110,
      render: (r) => fmtDate(r.date ?? r.ts),
    },
    {
      key: "open",
      header: "Open",
      numeric: true,
      width: 90,
      render: (r) => fmtNum(r.open),
    },
    {
      key: "high",
      header: "High",
      numeric: true,
      width: 90,
      render: (r) => fmtNum(r.high),
    },
    {
      key: "low",
      header: "Low",
      numeric: true,
      width: 90,
      render: (r) => fmtNum(r.low),
    },
    {
      key: "close",
      header: "Close",
      numeric: true,
      width: 90,
      render: (r) => fmtNum(r.close),
    },
    {
      key: "_changePct",
      header: "Δ %",
      numeric: true,
      width: 80,
      render: (r) =>
        r._changePct != null ? (
          <ChangeText value={r._changePct} digits={2} suffix="%" />
        ) : (
          "—"
        ),
    },
    {
      key: "volume",
      header: "Volume",
      numeric: true,
      width: 110,
      render: (r) => fmtCompact(r.volume),
    },
  ];

export function HPPane({ code, symbol }: FunctionPaneProps) {
  const [range, setRange] = usePersistentOption<RangeId>(
    "showme.hp-range",
    RANGE_IDS,
    "3M",
  );
  const days = useMemo(() => RANGES.find((r) => r.id === range)!.days, [range]);
  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { days, range },
    enabled: !!symbol,
  });

  const rows = useMemo(() => decorate(normalizeRows(data?.data)), [data]);

  const stats = useMemo(() => {
    if (!rows.length) return null;
    const closes = rows
      .map((r) => r.close ?? r.adj_close ?? r.adjClose)
      .filter((v): v is number => v != null);
    if (!closes.length) return null;
    const high = Math.max(...closes);
    const low = Math.min(...closes);
    const first = closes[closes.length - 1];
    const last = closes[0];
    const totalPct = first ? ((last - first) / first) * 100 : null;
    return { high, low, totalPct, n: rows.length };
  }, [rows]);

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title={`Historical price${symbol ? ` — ${symbol}` : ""}`}
          subtitle={
            stats
              ? `${stats.n} bars · range Δ ${stats.totalPct?.toFixed(2)}%`
              : "Pick a symbol"
          }
          trailing={
            <FunctionControlGroup>
              <Tabs
                variant="segmented"
                items={RANGES.map((r) => ({ id: r.id, label: r.label }))}
                active={range}
                onChange={(id) => setRange(id as RangeId)}
              />
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!symbol}
                title="Refresh historical price"
              />
              <button
                type="button"
                className="btn btn--accent"
                disabled={!rows.length || !symbol}
                onClick={() => downloadCsv(symbol ?? "data", range, rows)}
                title="Download CSV"
              >
                CSV
              </button>
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={symbol} />
        <PaneBody>
          {!symbol ? (
            <Empty
              title="Pick a symbol"
              body="HP downloads OHLCV rows for one ticker."
              icon="⌖"
            />
          ) : state === "loading" || state === "idle" ? (
            <Skeleton height={320} />
          ) : state === "error" ? (
            <Empty
              title="Function error"
              body={error?.message ?? "—"}
              icon="!"
              action={
                <button onClick={refetch} className="btn">
                  Retry
                </button>
              }
            />
          ) : rows.length === 0 ? (
            <Empty title="No bars" body={`No HP payload for ${symbol}.`} />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {stats && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Pill tone="muted" withDot={false}>
                    bars · {stats.n}
                  </Pill>
                  <Pill tone="positive" withDot={false}>
                    high · {fmtNum(stats.high)}
                  </Pill>
                  <Pill tone="negative" withDot={false}>
                    low · {fmtNum(stats.low)}
                  </Pill>
                  {stats.totalPct != null && (
                    <Pill
                      tone={stats.totalPct >= 0 ? "positive" : "negative"}
                      withDot={false}
                    >
                      total · {stats.totalPct.toFixed(2)}%
                    </Pill>
                  )}
                </div>
              )}
              <DataGrid
                columns={COLS}
                rows={rows}
                rowKey={(r, i) => `${r.date ?? r.ts ?? ""}-${i}`}
                density="compact"
              />
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>range · {range}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function normalizeRows(payload: unknown): HPRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as HPRow[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.bars ?? o.rows ?? o.history ?? o.items ?? o.candles ?? null;
    if (Array.isArray(items)) return items as HPRow[];
  }
  return [];
}

function decorate(rows: HPRow[]): Array<HPRow & { _change?: number; _changePct?: number }> {
  // Rows come back newest-first by convention; if older-first, reverse for delta.
  const sorted = [...rows].sort((a, b) => {
    const ad = new Date(a.date ?? a.ts ?? "").getTime();
    const bd = new Date(b.date ?? b.ts ?? "").getTime();
    return bd - ad;
  });
  return sorted.map((r, i) => {
    const prev = sorted[i + 1];
    if (!prev) return r;
    const c = r.close ?? r.adj_close ?? r.adjClose;
    const p = prev.close ?? prev.adj_close ?? prev.adjClose;
    if (c == null || p == null) return r;
    return { ...r, _change: c - p, _changePct: ((c - p) / p) * 100 };
  });
}

function fmtNum(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function fmtCompact(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
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

function downloadCsv(symbol: string, range: string, rows: HPRow[]): void {
  const csv = buildCsv(rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${symbol}-${range}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
