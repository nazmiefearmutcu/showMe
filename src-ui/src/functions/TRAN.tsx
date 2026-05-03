/**
 * TRAN — Trade blotter native pane.
 *
 * Reads the closed-trade history from Round 22's portfolio.db over
 * `/api/state/trades`. Optional symbol filter; CSV export reuses the
 * pattern from HP.tsx.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ChangeText,
  DataGrid,
  type DataGridColumn,
  Empty,
  Field,
  FieldRow,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
} from "@/design-system";
import { listTrades, type StateTrade } from "@/lib/state";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { buildTradeCsv } from "./TRAN.csv";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  RowLimitControl,
} from "./function-controls";
import {
  ROW_LIMITS,
  type RowLimit,
  usePersistentOption,
} from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const REFRESH_MS = 60_000;

export function TRANPane({ code, symbol }: FunctionPaneProps) {
  const [filter, setFilter] = useState(symbol ?? "");
  const [limit, setLimit] = usePersistentOption<RowLimit>(
    "showme.tran-limit",
    ROW_LIMITS,
    200,
  );
  const [tick, setTick] = useState(0);
  const [rows, setRows] = useState<StateTrade[] | null>(null);
  const [total, setTotal] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  useEffect(() => {
    if (symbol) setFilter(symbol);
  }, [symbol]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRows(null);
    listTrades({ limit, symbol: filter || undefined })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [filter, limit, tick]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const cols = useMemo<DataGridColumn<StateTrade>[]>(
    () => [
      {
        key: "closed_at",
        header: "Closed",
        width: 140,
        render: (r) => fmtDate(r.closed_at ?? r.opened_at),
      },
      {
        key: "symbol",
        header: "Symbol",
        width: 90,
        render: (r) => (
          <button
            type="button"
            onClick={() => {
              setFocusedTarget("DES", r.symbol);
              navigate(`/symbol/${r.symbol}/DES`);
            }}
            style={{
              background: "transparent",
              border: "none",
              color: "var(--accent)",
              cursor: "default",
              font: "inherit",
              padding: 0,
              fontWeight: 600,
            }}
          >
            {r.symbol}
          </button>
        ),
      },
      {
        key: "side",
        header: "Side",
        width: 70,
        render: (r) => (
          <Pill
            tone={r.side === "LONG" ? "positive" : r.side === "SHORT" ? "negative" : "muted"}
            withDot={false}
          >
            {r.side}
          </Pill>
        ),
      },
      {
        key: "quantity",
        header: "Qty",
        numeric: true,
        width: 80,
        render: (r) => fmtNum(r.quantity, 4),
      },
      {
        key: "entry_price",
        header: "Entry",
        numeric: true,
        width: 90,
        render: (r) => fmtNum(r.entry_price),
      },
      {
        key: "exit_price",
        header: "Exit",
        numeric: true,
        width: 90,
        render: (r) => fmtNum(r.exit_price),
      },
      {
        key: "realized_pnl",
        header: "Realized",
        numeric: true,
        width: 110,
        render: (r) =>
          r.realized_pnl != null ? (
            <ChangeText value={r.realized_pnl} digits={2} prefix="$" />
          ) : (
            "—"
          ),
      },
      {
        key: "mode",
        header: "Mode",
        width: 90,
        render: (r) => (
          <Pill
            tone={r.mode === "writable" ? "warn" : "muted"}
            withDot={false}
          >
            {r.mode ?? "—"}
          </Pill>
        ),
      },
    ],
    [setFocusedTarget],
  );

  const summary = useMemo(() => {
    if (!rows || rows.length === 0) return null;
    const closed = rows.filter((r) => r.realized_pnl != null);
    const realized = closed.reduce(
      (acc, r) => acc + (Number(r.realized_pnl) || 0),
      0,
    );
    const wins = closed.filter((r) => Number(r.realized_pnl) > 0).length;
    const losses = closed.filter((r) => Number(r.realized_pnl) < 0).length;
    return { realized, wins, losses, n: closed.length };
  }, [rows]);

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Trade blotter"
          subtitle={
            summary
              ? `${summary.n} closed · realized ${summary.realized.toFixed(2)}`
              : `${total} row(s) total`
          }
          trailing={
            <FunctionControlGroup>
              <RowLimitControl
                value={limit}
                onChange={(next) => setLimit(next as RowLimit)}
                disabled={rows == null}
              />
              <LoadStatePill state={rows == null ? "loading" : error ? "error" : "ok"} />
              <RefreshButton
                loading={rows == null}
                onClick={() => setTick((t) => t + 1)}
                title="Refresh trades"
              />
              <button
                type="button"
                className="btn btn--accent"
                disabled={!rows?.length}
                onClick={() =>
                  rows &&
                  downloadCsv(filter || "all", rows)
                }
                title="Download CSV"
              >
                CSV
              </button>
            </FunctionControlGroup>
          }
        />
        <div
          style={{
            padding: "8px 14px",
            borderBottom: "1px solid var(--border-subtle)",
            background: "var(--bg-elev-2)",
          }}
        >
          <FieldRow>
            <Field
              label="Symbol filter"
              placeholder="(all)"
              value={filter}
              onChange={(e) => setFilter(e.target.value.toUpperCase())}
            />
          </FieldRow>
        </div>
        <PaneBody>
          {rows == null ? (
            <Skeleton height={300} />
          ) : error ? (
            <Empty title="State unavailable" body={error} icon="!" />
          ) : rows.length === 0 ? (
            <Empty
              title="No trades yet"
              body={`portfolio.db has ${total} row(s) but none match the current filter.`}
            />
          ) : (
            <>
              {summary && (
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    flexWrap: "wrap",
                    marginBottom: 8,
                  }}
                >
                  <Pill tone="muted" withDot={false}>
                    closed · {summary.n}
                  </Pill>
                  <Pill tone="positive" withDot={false}>
                    wins · {summary.wins}
                  </Pill>
                  <Pill tone="negative" withDot={false}>
                    losses · {summary.losses}
                  </Pill>
                  <Pill
                    tone={summary.realized >= 0 ? "positive" : "negative"}
                    withDot={false}
                  >
                    realized · ${summary.realized.toFixed(2)}
                  </Pill>
                </div>
              )}
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r) => r.trade_id ?? `${r.symbol}-${r.id}`}
                density="compact"
                onRowDoubleClick={(r) => {
                  setFocusedTarget("DES", r.symbol);
                  navigate(`/symbol/${r.symbol}/DES`);
                }}
              />
            </>
          )}
        </PaneBody>
        <PaneFooter>
          <span>refresh · {REFRESH_MS / 1000}s</span>
          <span>filter · {filter || "(all)"}</span>
          <span>limit · {limit}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function fmtDate(v: string | undefined): string {
  if (!v) return "—";
  try {
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return v.slice(0, 16);
    return d.toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return v;
  }
}

function fmtNum(v: number | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function downloadCsv(label: string, rows: StateTrade[]): void {
  const csv = buildTradeCsv(rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `trades-${label}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
