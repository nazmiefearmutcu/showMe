/**
 * TXNS — Bloomberg-grade transaction ledger.
 *
 * Dense ledger table with side pills (BUY/LONG positive, SELL/SHORT
 * accent-tinted), DeltaChip realized P&L, and a top KPI strip
 * (realized total / wins / losses / avg P&L per trade). Reads closed-trade
 * history from Round 22's portfolio.db over `/api/state/trades`.
 *
 * Terminal-grade honesty pass (page-by-page campaign):
 *   H1 — provenance disclosure: these rows are trade history IMPORTED into
 *        the local portfolio.db (a historical snapshot), NOT live broker
 *        fills and NOT ShowMe bot trades.
 *   H2 — each row's `source` (e.g. "showme_import") is surfaced in a column.
 *   H3 — the `mode` column is relabelled "Kayıt" and its pill carries a
 *        tooltip clarifying that "writable" = an editable DB record, NOT a
 *        live-trading mode.
 *   B-UI — `generated_at` from the API drives a "Son güncelleme" indicator.
 *   D1/D2 — formatting via format.ts helpers + `terminal-grid-numeric`.
 *   A1–A5 — DataGrid aria-label, symbol aria-labels, role=status error,
 *        wired column sorting, CSV aria-label + result count honesty.
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
import {
  formatMissing,
  formatNumber,
  formatPrice,
} from "@/lib/format";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { buildTradeCsv } from "./TXNS.csv";
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

// H3 — honest tooltip: `mode` is a DB-edit-permission flag, NOT a live vs
// shadow trading mode. Spelled out so "writable" never reads as "live".
const MODE_TOOLTIP =
  "writable = DB'de düzenlenebilir kayıt; canlı işlem anlamına gelmez";

type SortKey =
  | "closed_at"
  | "symbol"
  | "realized_pnl"
  | "quantity"
  | "entry_price"
  | "exit_price";
type SortDir = "ascending" | "descending";

export function TXNSPane({ code, symbol }: FunctionPaneProps) {
  const [filter, setFilter] = useState(symbol ?? "");
  const [limit, setLimit] = usePersistentOption<RowLimit>(
    "showme.txns-limit",
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
  const [source, setSource] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A3 — DataGrid column sort. Default = closed_at descending (newest first).
  const [sortBy, setSortBy] = useState<SortKey>("closed_at");
  const [sortDir, setSortDir] = useState<SortDir>("descending");
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
        setSource(res.source ?? null);
        setGeneratedAt(res.generated_at ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [filter, limit, tick]);

  // A3 — cycle a sortable header: same key flips direction; new key starts
  // descending (the natural "biggest / newest first" default for a blotter).
  const onSort = (key: string) => {
    const k = key as SortKey;
    if (sortBy === k) {
      setSortDir((d) => (d === "descending" ? "ascending" : "descending"));
    } else {
      setSortBy(k);
      setSortDir("descending");
    }
  };

  // A3 — comparator (follows PORT.tsx): missing values sink to the bottom
  // regardless of direction; strings compare locale-insensitively.
  const sortedRows = useMemo(() => {
    if (!rows) return rows;
    const dir = sortDir === "ascending" ? 1 : -1;
    const numeric = (r: StateTrade): number | undefined => {
      switch (sortBy) {
        case "realized_pnl":
          return r.realized_pnl;
        case "quantity":
          return r.quantity;
        case "entry_price":
          return r.entry_price;
        case "exit_price":
          return r.exit_price;
        default:
          return undefined;
      }
    };
    return [...rows].sort((a, b) => {
      if (sortBy === "symbol") {
        return a.symbol.localeCompare(b.symbol) * dir;
      }
      if (sortBy === "closed_at") {
        const av = a.closed_at ?? a.opened_at ?? "";
        const bv = b.closed_at ?? b.opened_at ?? "";
        if (!av && !bv) return 0;
        if (!av) return 1;
        if (!bv) return -1;
        return av.localeCompare(bv) * dir;
      }
      const av = numeric(a);
      const bv = numeric(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * dir;
    });
  }, [rows, sortBy, sortDir]);

  const cols = useMemo<DataGridColumn<StateTrade>[]>(
    () => [
      {
        key: "closed_at",
        header: "Closed",
        width: 140,
        sortable: true,
        render: (r) => (
          <span className="tran-date-cell">
            {fmtDate(r.closed_at ?? r.opened_at)}
          </span>
        ),
      },
      {
        key: "symbol",
        header: "Symbol",
        width: 92,
        sortable: true,
        render: (r) => (
          <button
            type="button"
            aria-label={`${r.symbol} detayları`}
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
            {r.side ?? formatMissing}
          </Pill>
        ),
      },
      {
        key: "quantity",
        header: "Qty",
        numeric: true,
        width: 86,
        sortable: true,
        render: (r) => (
          <span className="terminal-grid-numeric">
            {formatNumber(r.quantity, 4)}
          </span>
        ),
      },
      {
        key: "entry_price",
        header: "Entry",
        numeric: true,
        width: 92,
        sortable: true,
        render: (r) => (
          <span className="terminal-grid-numeric">
            {formatPrice(r.entry_price)}
          </span>
        ),
      },
      {
        key: "exit_price",
        header: "Exit",
        numeric: true,
        width: 92,
        sortable: true,
        render: (r) => (
          <span className="terminal-grid-numeric">
            {formatPrice(r.exit_price)}
          </span>
        ),
      },
      {
        key: "realized_pnl",
        header: "Realized",
        numeric: true,
        width: 124,
        sortable: true,
        render: (r) => {
          if (r.realized_pnl == null || !Number.isFinite(r.realized_pnl))
            return (
              <span className="u-text-mute terminal-grid-numeric">
                {formatMissing}
              </span>
            );
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
        // H3 — relabelled "Kayıt" (record) so the column never implies a
        // live-trading mode. The pill carries an accessible label + title
        // tooltip spelling out what "writable" actually means.
        key: "mode",
        header: "Kayıt",
        width: 96,
        render: (r) => (
          // Pill is a closed-prop design-system primitive, so the accessible
          // label + tooltip live on a wrapper element it renders inside.
          <span
            title={MODE_TOOLTIP}
            aria-label={`Kayıt: ${r.mode ?? formatMissing} — ${MODE_TOOLTIP}`}
            data-testid="txns-mode-cell"
          >
            <Pill
              tone={r.mode === "writable" ? "warn" : "muted"}
              variant="soft"
              withDot={false}
            >
              {r.mode ?? formatMissing}
            </Pill>
          </span>
        ),
      },
      {
        // H2 — per-row provenance. Honest "—" when absent; CSV exports the
        // same field so the export stays consistent with the grid.
        key: "source",
        header: "Kaynak",
        width: 120,
        render: (r) => (
          <span className="u-text-secondary" data-testid="txns-source-cell">
            {r.source ?? formatMissing}
          </span>
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
  const visibleCount = rows?.length ?? 0;
  const lastUpdated = generatedAt ? fmtClock(generatedAt) : formatMissing;
  // A5 — distinguish an empty portfolio.db (0 total) from a filter that
  // simply matched nothing (M rows exist but none match).
  const emptyDb = total === 0;

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
              {/* A5 — visible / total count, honest. */}
              <Pill tone="muted" variant="soft" withDot={false}>
                {visibleCount} / {total} rows
              </Pill>
              {/* B-UI — freshness indicator from the API's generated_at.
                  Wrapper carries the testid/title since Pill is closed-prop. */}
              <span
                data-testid="txns-last-updated"
                title="Bu yanıtın sunulduğu zaman (içe aktarma zamanı değil)"
              >
                <Pill tone="muted" variant="soft" withDot={false}>
                  Son güncelleme: {lastUpdated}
                </Pill>
              </span>
              <RowLimitControl
                value={limit}
                onChange={(next) => setLimit(next as RowLimit)}
                disabled={rows == null}
              />
              <LoadStatePill
                state={rows == null ? "loading" : error ? "error" : "ok"}
              />
              <RefreshButton
                loading={rows == null}
                onClick={() => setTick((t) => t + 1)}
                title="Refresh trades"
              />
              <button
                type="button"
                className="btn btn--accent"
                disabled={!rows?.length}
                aria-label={
                  rows?.length
                    ? `${rows.length} işlemi CSV olarak indir`
                    : "İndirilecek işlem yok"
                }
                onClick={() => rows && downloadCsv(filter || "all", rows)}
                title="Download CSV"
              >
                CSV
              </button>
            </FunctionControlGroup>
          }
        />
        {/* H1 — provenance disclosure. Concise + honest: these are IMPORTED
            historical trades, not live broker fills nor ShowMe bot trades. */}
        <div
          className="txns-provenance u-text-secondary"
          data-testid="txns-provenance"
        >
          Bu kayıtlar yerel <code>portfolio.db</code>
          {source ? (
            <>
              {" "}(<code>{source}</code>)
            </>
          ) : null}{" "}
          içine <strong>içe aktarılmış</strong> işlem geçmişidir — tarihsel bir
          anlık görüntü; canlı broker emirleri veya ShowMe bot işlemleri{" "}
          <strong>değildir</strong>.
        </div>
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
          {error ? (
            // A2 — async error is an announced live region, mirroring PERF.
            // Checked before the loading skeleton so a fetch rejection (which
            // never repopulates `rows`) surfaces instead of spinning forever.
            <div role="status" className="u-text-negative" data-testid="txns-error">
              <Empty title="State unavailable" body={error} icon="!" />
            </div>
          ) : rows == null ? (
            <Skeleton height={300} />
          ) : sortedRows && sortedRows.length === 0 ? (
            // A5 — empty-db vs filtered-empty are different stories.
            <Empty
              title={emptyDb ? "portfolio.db boş" : "Filtreyle eşleşen yok"}
              body={
                emptyDb
                  ? "İçe aktarılmış işlem kaydı yok. portfolio.db'ye işlem aktarıldığında burada listelenir."
                  : `portfolio.db'de ${total} kayıt var ama hiçbiri geçerli filtreyle eşleşmiyor.`
              }
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
                rows={sortedRows ?? []}
                rowKey={(r) => r.trade_id ?? `${r.symbol}-${r.id}`}
                density="compact"
                ariaLabel="İşlem defteri"
                sortBy={sortBy}
                sortDir={sortDir}
                onSort={onSort}
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
            <span>oldest · {fmtDate(oldestRow.closed_at ?? oldestRow.opened_at)}</span>
          ) : null}
          <span>fee model · gross of fees</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * D1 — robust date formatter. Parses to a real Date and renders the local
 * "YYYY-MM-DD HH:MM"; only when parsing fails do we fall back to the raw
 * string trimmed to a sane length (no fragile blind ISO-slicing of a value
 * that might not be ISO at all).
 */
function fmtDate(v: string | undefined): string {
  if (!v) return formatMissing;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v.length > 19 ? v.slice(0, 19) : v;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** B-UI — compact HH:MM clock for the freshness indicator. */
function fmtClock(v: string): string {
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return formatMissing;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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
