/**
 * TRAN — Bloomberg-grade transaction ledger.
 *
 * Dense ledger table with side pills (BUY/LONG positive, SELL/SHORT
 * accent-tinted), DeltaChip realized P&L, and a top KPI strip
 * (realized total / wins / losses / avg P&L per trade). Reads closed-trade
 * history from Round 22's portfolio.db over `/api/state/trades`.
 *
 * ⚠ S13 BUG HUNT 2026-05-17 — this pane is currently NOT registered in
 * `ui/src/functions/registry.tsx`'s PANES map. The official function
 * code `TRAN` corresponds to "Earnings Call Transcripts" in
 * `ui/src/functions/static-index.ts:773` and is backed by
 * `backend/showme/engine/functions/news/tran.py`, so registering this
 * implementation under TRAN would override the correct earnings surface
 * with an unrelated trade blotter. Leave this file in-tree until a new
 * fn-code is allocated for "Trade Blotter" (e.g. BLTR / TXNS); at that
 * point this component should be renamed and re-wired. Until then the
 * file is intentionally orphaned dead code, kept so the trade-blotter
 * design is recoverable without a git archaeology session.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ChangeText,
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
  Field,
  FieldRow,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
} from "@/design-system";
import { listTrades, type StateTrade } from "@/lib/state";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
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
  // Bundle D / PERF-04. Manual tick (used by the Refresh button) blended
  // with `useVisibilityTick` so background tabs no longer poll the trades
  // endpoint every minute.
  const [manualTick, setManualTick] = useState(0);
  const visTick = useVisibilityTick(REFRESH_MS);
  const tick = manualTick + visTick;
  const setTick = (next: ((prev: number) => number) | number) => {
    setManualTick((prev) => (typeof next === "function" ? next(prev) : next));
  };
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

  const cols = useMemo<DataGridColumn<StateTrade>[]>(
    () => [
      {
        key: "closed_at",
        header: "Closed",
        width: 140,
        render: (r) => (
          <span className="tran-date-cell">{fmtDate(r.closed_at ?? r.opened_at)}</span>
        ),
      },
      {
        key: "symbol",
        header: "Symbol",
        width: 92,
        render: (r) => (
          <button
            type="button"
            onClick={() => {
              setFocusedTarget("DES", r.symbol);
              navigate(`/symbol/${r.symbol}/DES`);
            }}
            className="u-symbol-link"
          >
            {r.symbol}
          </button>
        ),
      },
      {
        key: "side",
        header: "Side",
        width: 72,
        render: (r) => (
          <Pill
            tone={
              r.side === "LONG"
                ? "positive"
                : r.side === "SHORT"
                  ? "accent"
                  : "muted"
            }
            variant="soft"
            withDot={false}
          >
            {r.side ?? "—"}
          </Pill>
        ),
      },
      {
        key: "quantity",
        header: "Qty",
        numeric: true,
        width: 86,
        render: (r) => (
          <span style={ledgerNumStyle}>{fmtNum(r.quantity, 4)}</span>
        ),
      },
      {
        key: "entry_price",
        header: "Entry",
        numeric: true,
        width: 92,
        render: (r) => <span style={ledgerNumStyle}>{fmtNum(r.entry_price)}</span>,
      },
      {
        key: "exit_price",
        header: "Exit",
        numeric: true,
        width: 92,
        render: (r) => <span style={ledgerNumStyle}>{fmtNum(r.exit_price)}</span>,
      },
      {
        key: "realized_pnl",
        header: "Realized",
        numeric: true,
        width: 124,
        render: (r) => {
          if (r.realized_pnl == null || !Number.isFinite(r.realized_pnl))
            return <span className="u-text-mute">—</span>;
          return (
            <DeltaChip
              value={r.realized_pnl}
              format="currency"
              fractionDigits={2}
            />
          );
        },
      },
      {
        key: "mode",
        header: "Mode",
        width: 90,
        render: (r) => (
          <Pill
            tone={r.mode === "writable" ? "warn" : "muted"}
            variant="soft"
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
    const avg = closed.length ? realized / closed.length : 0;
    return { realized, wins, losses, n: closed.length, avg };
  }, [rows]);

  const utcNow = new Date().toISOString().slice(11, 16);
  const oldestRow = rows && rows.length ? rows[rows.length - 1] : null;

  return (
    <div className="u-pane-host">
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
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows?.length ?? 0} rows
              </Pill>
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
        <div className="most-tab-strip">
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
              {summary ? (
                <div className="watch-kpi-strip">
                  <StatCard
                    label="Realized P&L"
                    value={
                      <ChangeText value={summary.realized} prefix="$" digits={2} />
                    }
                    caption={`AS OF ${utcNow} UTC`}
                    tone={
                      summary.realized > 0
                        ? "positive"
                        : summary.realized < 0
                          ? "negative"
                          : "neutral"
                    }
                  />
                  <StatCard
                    label="Wins"
                    value={String(summary.wins)}
                    caption={`${summary.n} closed`}
                    tone={summary.wins > summary.losses ? "positive" : "neutral"}
                  />
                  <StatCard
                    label="Losses"
                    value={String(summary.losses)}
                    caption={`win rate ${summary.n ? ((summary.wins / summary.n) * 100).toFixed(0) : "0"}%`}
                    tone={summary.losses > summary.wins ? "negative" : "neutral"}
                  />
                  <StatCard
                    label="Avg P&L / trade"
                    value={
                      <ChangeText value={summary.avg} prefix="$" digits={2} />
                    }
                    caption={`limit ${limit}`}
                    tone={
                      summary.avg > 0
                        ? "positive"
                        : summary.avg < 0
                          ? "negative"
                          : "neutral"
                    }
                  />
                </div>
              ) : null}

              {/* Filter chips */}
              {summary ? (
                <div className="tran-chip-row">
                  <Pill tone="muted" variant="soft" withDot={false}>
                    closed · {summary.n}
                  </Pill>
                  <Pill tone="positive" variant="soft" withDot={false}>
                    wins · {summary.wins}
                  </Pill>
                  <Pill tone="negative" variant="soft" withDot={false}>
                    losses · {summary.losses}
                  </Pill>
                  <Pill
                    tone={summary.realized >= 0 ? "positive" : "negative"}
                    variant="soft"
                    withDot
                  >
                    realized · ${summary.realized.toFixed(2)}
                  </Pill>
                  {filter ? (
                    <Pill tone="accent" variant="soft" withDot={false}>
                      filter · {filter}
                    </Pill>
                  ) : null}
                </div>
              ) : null}

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
          {oldestRow ? (
            <span>
              oldest · {fmtDate(oldestRow.closed_at ?? oldestRow.opened_at)}
            </span>
          ) : null}
          <span>fee model · gross of fees</span>
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

const ledgerNumStyle: React.CSSProperties = {
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 12,
};
