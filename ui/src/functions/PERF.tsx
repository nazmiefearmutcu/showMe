/**
 * PERF — Cumulative performance pane. Sub-system I.
 *
 * Top: 4-pill KPI strip — Leader / Top gainer / Laggard / Top loser — each
 * tracks its own semantic so the user can read "top by PnL ranking" vs
 * "worst loser" without one masking the other (H-SUP-1 fix).
 *
 * Middle: sortable leaderboard DataGrid (sort/clipboard/CSV).
 * Right (when bot selected): equity curve <svg> (no external chart lib).
 *
 * Polling is driven by `useBotEcosystemPolling` so this pane and BOTS stay
 * frame-aligned (BUG #10 fix).  The legacy 15s setInterval was removed.
 *
 * Terminal-grade pass (honesty, data sufficiency, a11y, display, states):
 *   F1 — equity curve disclosed as a SIMULATED relative curve seeded at the
 *        returned starting_equity ($10k); a warn marker shows when the live
 *        bot was sized on the fallback equity (equity_source === fallback_10k).
 *   F2 — surfaced risk metrics (sharpe/sortino/profit_factor/expectancy/max
 *        consec losses) with the sample size N, de-emphasised + caveated when
 *        N is small (ratios from few trades are unreliable). "inf" → "∞".
 *   F3 — display correctness: drawdown reads as a negative LOSS (red); all
 *        toFixed replaced with format.ts helpers; P&L sign-coloured.
 *   F4 — full a11y: grid aria-labels + scope headers; SVG role=img +
 *        aria-label + sr-only summary; refresh aria-busy/disabled; KPI pills
 *        named; keyboard-operable rows; single pane-level sr-only role=status
 *        summary gated by a ref.
 *   F5 — Skeleton on first load, design-system Empty states, last-updated
 *        freshness indicator from generated_at; honest "—" when absent.
 *
 * F10 (fix lane, audit A1): leaderboard + trades migrated to the DataGrid kit
 * (sort/clipboard/CSV); Turkish comments and legacy Turkish test-ids renamed.
 */
import { useMemo } from "react";
import {
  usePerformanceStore,
  type LeaderboardEntry,
  type PerformanceMetrics,
  type TradeRow,
} from "@/lib/performance-store";
import { useBotEcosystemPolling } from "@/lib/useBotEcosystemPolling";
import {
  formatCurrency,
  formatNumber,
  formatPercent,
  formatPrice,
  formatSignedCurrency,
  formatMissing,
} from "@/lib/format";
import { maxOf, minOf } from "@/lib/maxOf";
import { isKaosRecord } from "@/lib/kaos-venues";
import { KaosEngineBadge } from "@/functions/KaosBadges";
import {
  buildGridCsv,
  DataGrid,
  downloadGridCsv,
  Empty,
  gridCsvFilename,
  Pill,
  SkeletonRow,
  type DataGridColumn,
  type GridCsvColumn,
} from "@/design-system";

// Sentinel the backend stamps onto a SignalEntry whose live order was sized on
// the fallback equity ($10k) rather than real broker equity. Mirrors BOT/BOTS.
const FALLBACK_EQUITY_SOURCE = "fallback_10k";

// F2 — ratios (sharpe/sortino/profit_factor) computed from fewer than this
// many round-trips are statistically unreliable; we de-emphasise + caveat them
// rather than presenting them as confident figures.
const MIN_RELIABLE_N = 20;

function _pnlClass(n: number): string | undefined {
  if (n > 0) return "u-text-positive";
  if (n < 0) return "u-text-negative";
  return undefined;
}

// F10 — the trades view window; the CSV export always covers every trade.
const TRADES_WINDOW = 50;

// F10 (audit A1) — leaderboard CSV columns. Raw numbers (not formatted
// strings) so spreadsheets receive values.
const LEADERBOARD_CSV_COLUMNS: GridCsvColumn<LeaderboardEntry>[] = [
  { key: "symbol", header: "Symbol", value: (e) => e.symbol },
  { key: "bot_id", header: "Bot ID", value: (e) => e.bot_id },
  { key: "mode", header: "Mode", value: (e) => e.mode },
  { key: "enabled", header: "Enabled", value: (e) => e.enabled },
  { key: "trade_count", header: "Trades", value: (e) => e.trade_count },
  { key: "win_rate", header: "Win rate", value: (e) => e.win_rate },
  { key: "total_pnl", header: "Total PnL", value: (e) => e.total_pnl },
  { key: "max_drawdown", header: "Max drawdown", value: (e) => e.max_drawdown },
  { key: "sharpe", header: "Sharpe", value: (e) => e.sharpe ?? "" },
  { key: "sortino", header: "Sortino", value: (e) => e.sortino ?? "" },
  { key: "profit_factor", header: "Profit factor", value: (e) => e.profit_factor ?? "" },
];

const TRADE_CSV_COLUMNS: GridCsvColumn<TradeRow>[] = [
  { key: "entry_time", header: "Entry time", value: (t) => t.entry_time },
  { key: "entry_price", header: "Entry price", value: (t) => t.entry_price },
  { key: "exit_time", header: "Exit time", value: (t) => t.exit_time },
  { key: "exit_price", header: "Exit price", value: (t) => t.exit_price },
  { key: "qty", header: "Qty", value: (t) => t.qty },
  { key: "pnl", header: "PnL", value: (t) => t.pnl },
  { key: "pnl_pct", header: "PnL %", value: (t) => t.pnl_pct },
];

const TRADE_COLUMNS: DataGridColumn<TradeRow>[] = [
  {
    key: "entry_time",
    header: "Entry",
    width: 140,
    sortable: true,
    sortValue: (t) => t.entry_time,
    render: (t) => t.entry_time.slice(0, 16),
  },
  {
    key: "entry_price",
    header: "@",
    width: 100,
    numeric: true,
    align: "right",
    sortable: true,
    sortValue: (t) => t.entry_price,
    render: (t) => formatPrice(t.entry_price),
  },
  {
    key: "exit_time",
    header: "Exit",
    width: 140,
    sortable: true,
    sortValue: (t) => t.exit_time,
    render: (t) => t.exit_time.slice(0, 16),
  },
  {
    key: "exit_price",
    header: "@",
    width: 100,
    numeric: true,
    align: "right",
    sortable: true,
    sortValue: (t) => t.exit_price,
    render: (t) => formatPrice(t.exit_price),
  },
  {
    key: "pnl",
    header: "PnL",
    width: 100,
    numeric: true,
    align: "right",
    sortable: true,
    sortValue: (t) => t.pnl,
    render: (t) => (
      <span className={_pnlClass(t.pnl)}>{formatSignedCurrency(t.pnl)}</span>
    ),
  },
  {
    key: "pnl_pct",
    header: "%",
    width: 80,
    numeric: true,
    align: "right",
    sortable: true,
    sortValue: (t) => t.pnl_pct,
    render: (t) => (
      <span className={_pnlClass(t.pnl_pct)}>{formatPercent(t.pnl_pct, { signed: true })}</span>
    ),
  },
];

/**
 * F2 — render a metric that may arrive as the string "inf"/"-inf" (the backend
 * _safe_float guard emits these when there are no losses). "∞" reads honestly;
 * a non-finite numeric falls back to the em-dash sentinel.
 */
function formatRatio(value: number | string | undefined, digits = 2): string {
  if (value === "inf") return "∞";
  if (value === "-inf") return "-∞";
  if (typeof value !== "number" || !Number.isFinite(value)) return formatMissing;
  // Fixed decimals so ratios read consistently ("2.10", not "2.1"). Uses the
  // shared format.ts helper instead of a raw .toFixed() (page-spec).
  return formatNumber(value, digits, { minimumFractionDigits: digits });
}

function KPI({ label, value, fmt }: {
  label: string; value: number; fmt: (v: number) => string;
}) {
  return (
    <div>
      <div style={{ fontSize: "var(--font-size-2xs)" }} className="u-text-secondary">{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600 }} className={_pnlClass(value)}>
        {fmt(value)}
      </div>
    </div>
  );
}

/**
 * F4 — equity curve as an accessible <svg>. role="img" + a descriptive
 * aria-label, plus a visually-hidden text summary. The points.length < 2
 * branch returns an honest accessible Empty instead of a bare line.
 *
 * F1 — the curve is SIMULATED + RELATIVE: it is seeded at `startingEquity`
 * (the backend's documented $10k baseline) and compounds net PnL. It is NOT
 * the user's real account balance — disclosed in a caption by the caller.
 */
function EquityCurve({
  points,
  startingEquity,
  width = 480,
  height = 160,
}: {
  points: { t: string; equity: number }[];
  startingEquity: number;
  width?: number;
  height?: number;
}) {
  if (points.length < 2) {
    return (
      <div data-testid="perf-equity-empty">
        <Empty
          title="Not enough trade data"
          body={`At least 2 closed trades are needed for the equity curve (simulated start ${formatCurrency(startingEquity)}).`}
        />
      </div>
    );
  }
  const equities = points.map((p) => p.equity);
  // UA-HIGH-12: stack-safe.
  const min = minOf(equities);
  const max = maxOf(equities);
  const range = max - min || 1;
  const stepX = width / (points.length - 1);
  const pathD = points.map((p, i) => {
    const x = i * stepX;
    const y = height - ((p.equity - min) / range) * height;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const start = equities[0];
  const end = equities[equities.length - 1];
  // F4 — full accessible description so a screen-reader user gets the shape of
  // the curve without seeing the SVG.
  const summary =
    `Simulated equity curve — start ${formatCurrency(start)}, ` +
    `end ${formatCurrency(end)}, low ${formatCurrency(min)}, ` +
    `high ${formatCurrency(max)}.`;
  return (
    <>
      <svg
        role="img"
        aria-label={summary}
        data-testid="perf-equity-svg"
        width={width}
        height={height}
        style={{ border: "1px solid var(--border-card)" }}
      >
        <path d={pathD} stroke="var(--accent-ok)" fill="none" strokeWidth={1.5} />
        <text x={4} y={12} fill="var(--fg-2)" fontSize="9">
          min: {formatCurrency(min)} · max: {formatCurrency(max)}
        </text>
      </svg>
      <span className="u-sr-only" data-testid="perf-equity-summary">{summary}</span>
    </>
  );
}

function BotPill({
  label,
  entry,
  tone,
  signPrefix,
  testId,
}: {
  label: string;
  entry: LeaderboardEntry | undefined;
  tone: "ok" | "err" | "mute";
  signPrefix?: "+" | "";
  testId: string;
}) {
  if (!entry) return null;
  const cls =
    tone === "ok" ? "u-text-positive"
    : tone === "err" ? "u-text-negative"
    : "u-text-secondary";
  // F3 — the explicit-sign currency helper handles the "+" prefix + sentinel.
  // When signPrefix is forced "+" we still want the helper's sign for negatives.
  const valueText = signPrefix === "+"
    ? formatSignedCurrency(entry.total_pnl)
    : formatCurrency(entry.total_pnl);
  // F4 — accessible name so each KPI pill reads as "label: symbol value".
  const accessibleName = `${label}: ${entry.symbol} ${valueText}`;
  return (
    <div data-testid={testId} aria-label={accessibleName}>
      <div style={{ fontSize: "var(--font-size-2xs)" }} className="u-text-secondary">{label}</div>
      <div className={cls}>
        {entry.symbol}: {valueText}
      </div>
    </div>
  );
}

/**
 * F4 — the SINGLE pane-level live region. Announces the at-a-glance leaderboard
 * summary. React's vDOM diffing already leaves an unchanged text node untouched
 * across the 10s poll re-render, so an identical summary is not re-announced —
 * no manual suppression is needed. Visually hidden.
 */
function PerfSummaryLive({ summary }: { summary: string }) {
  return (
    <span className="u-sr-only" role="status" data-testid="perf-summary">
      {summary}
    </span>
  );
}

/**
 * F2 — per-bot risk-metrics table. Surfaces the computed-but-previously-hidden
 * sharpe/sortino/profit_factor/expectancy/max-consec-losses with the sample
 * size N shown prominently. When N is small the ratios are de-emphasised and a
 * caveat title spells out that few-trade ratios are unreliable.
 */
function RiskMetrics({ metrics }: { metrics: PerformanceMetrics }) {
  const n = metrics.trade_count;
  const lowN = n < MIN_RELIABLE_N;
  const caveat = lowN
    ? `Small sample (N=${n}); these ratios are statistically unreliable.`
    : undefined;
  const ratioCls = lowN ? "u-text-secondary" : undefined;
  return (
    <div data-testid="perf-risk-metrics" style={{ margin: "8px 0" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <h4 style={{ margin: "8px 0 4px" }}>Risk metrics</h4>
        {/* F2 — N shown prominently next to the ratios; warn-toned when low. */}
        <span data-testid="perf-sample-size">
          <Pill tone={lowN ? "warn" : "muted"} variant="soft" withDot={false}>
            N={formatNumber(n)}
          </Pill>
        </span>
      </div>
      {lowN && (
        <div
          data-testid="perf-low-sample-warning"
          className="u-text-warn"
          style={{ fontSize: "var(--font-size-sm)", marginBottom: 4 }}
        >
          ⚠ {caveat}
        </div>
      )}
      <table
        className="terminal-grid-numeric"
        aria-label="Bot risk metrics"
        style={{ width: "100%", fontSize: "var(--font-size-sm)" }}
      >
        <caption className="u-sr-only">
          Computed risk ratios — Sharpe, Sortino, profit factor, expectancy
          and consecutive losses; sample size N={n}.
        </caption>
        <thead>
          <tr className="u-text-secondary">
            <th scope="col" align="left">Sharpe</th>
            <th scope="col" align="left">Sortino</th>
            <th scope="col" align="left">Profit factor</th>
            <th scope="col" align="left">Expectancy</th>
            <th scope="col" align="left">Max consecutive losses</th>
          </tr>
        </thead>
        <tbody>
          <tr title={caveat}>
            <td className={ratioCls} data-testid="perf-sharpe">{formatRatio(metrics.sharpe)}</td>
            <td className={ratioCls} data-testid="perf-sortino">{formatRatio(metrics.sortino)}</td>
            <td className={ratioCls} data-testid="perf-profit-factor">
              {formatRatio(metrics.profit_factor)}
            </td>
            <td data-testid="perf-expectancy">
              {metrics.expectancy != null ? formatSignedCurrency(metrics.expectancy) : formatMissing}
            </td>
            <td data-testid="perf-max-consec-losses">
              {metrics.max_consecutive_losses != null
                ? formatNumber(metrics.max_consecutive_losses)
                : formatMissing}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function PERFPane() {
  const leaderboard = usePerformanceStore((s) => s.leaderboard);
  const selected = usePerformanceStore((s) => s.selected);
  const loading = usePerformanceStore((s) => s.loading);
  const generatedAt = usePerformanceStore((s) => s.generatedAt);
  const loadLeaderboard = usePerformanceStore((s) => s.loadLeaderboard);
  const loadBot = usePerformanceStore((s) => s.loadBot);
  const clearSelected = usePerformanceStore((s) => s.clearSelected);
  const error = usePerformanceStore((s) => s.error);

  // BUG #10 — single-source polling across BOTS+PERF.  Replaces the legacy
  // 15s setInterval that desync'd with BOTS' 10s polling.
  useBotEcosystemPolling();

  const totalPnL = leaderboard.reduce((acc, e) => acc + e.total_pnl, 0);

  // H-SUP-1 — four distinct semantics so an all-positive portfolio still
  // shows "Laggard" (the worst-ranked bot, even if positive) and an
  // all-negative portfolio still shows "Leader" (the top-ranked bot, even
  // if negative).  When mixed, all four pills appear independently.
  //
  // The leaderboard is sorted by (-total_pnl, -trade_count) so [0] is the
  // ranking leader and [length-1] is the ranking laggard regardless of sign.
  const topPerformer = leaderboard[0];                                          // always shown
  const bottomPerformer =
    leaderboard.length > 1 ? leaderboard[leaderboard.length - 1] : undefined;   // always shown (if >1 bot)
  const positiveBest = leaderboard.find((b) => b.total_pnl > 0);                // real "Top gainer" (only if exists)
  const negativeWorst =
    [...leaderboard].reverse().find((b) => b.total_pnl < 0);                    // real "Top loser" (only if exists)

  // F5 — first-load skeleton: only while loading AND we have nothing yet.
  const firstLoad = loading && leaderboard.length === 0;

  // F4 — single announced summary; gated inside PerfSummaryLive so the poll
  // doesn't re-announce.
  const summary =
    `${formatNumber(leaderboard.length)} bots, total PnL ${formatSignedCurrency(totalPnL)}` +
    (selected ? `, selected: ${selected.symbol}` : "");

  // F1 — the simulated baseline disclosed near the curve; honest fallback to
  // the documented $10k when an older payload omits starting_equity.
  const startingEquity = selected?.starting_equity ?? 10_000;
  const isFallbackEquity = selected?.equity_source === FALLBACK_EQUITY_SOURCE;

  // F10 (audit A1) — leaderboard columns for the DataGrid kit (sort,
  // clipboard, keyboard-reachable headers). Selection is signalled on the
  // symbol cell (▸ + sr-only "selected") instead of the invalid
  // aria-selected-on-role=button the hand-rolled table used.
  const leaderboardColumns = useMemo<DataGridColumn<LeaderboardEntry>[]>(() => [
    {
      key: "symbol",
      header: "Symbol",
      width: 150,
      sortable: true,
      sortValue: (e) => e.symbol,
      render: (e) => {
        const isSelected = selected?.bot_id === e.bot_id;
        return (
          <span
            data-testid={`perf-row-symbol-${e.bot_id}`}
            data-selected={isSelected ? "true" : undefined}
          >
            {isSelected && <span aria-hidden="true">▸ </span>}
            {e.symbol}
            {isKaosRecord(e) && <KaosEngineBadge />}
            {isSelected && <span className="u-sr-only"> selected</span>}
          </span>
        );
      },
    },
    {
      key: "trade_count",
      header: "Trades",
      width: 80,
      numeric: true,
      align: "right",
      sortable: true,
      sortValue: (e) => e.trade_count,
      render: (e) => formatNumber(e.trade_count),
    },
    {
      key: "win_rate",
      header: "Win %",
      width: 80,
      numeric: true,
      align: "right",
      sortable: true,
      sortValue: (e) => e.win_rate,
      render: (e) => formatPercent(e.win_rate, { fromFraction: true, digits: 0 }),
    },
    {
      key: "total_pnl",
      header: "Total PnL",
      width: 110,
      numeric: true,
      align: "right",
      sortable: true,
      sortValue: (e) => e.total_pnl,
      render: (e) => (
        <span className={_pnlClass(e.total_pnl)}>{formatSignedCurrency(e.total_pnl)}</span>
      ),
    },
    {
      key: "max_drawdown",
      header: "Max DD",
      width: 100,
      numeric: true,
      align: "right",
      sortable: true,
      sortValue: (e) => e.max_drawdown,
      render: (e) => {
        // F3 — drawdown reads as a LOSS: the engine returns a positive
        // magnitude, so we negate for display and colour it red.
        const ddLoss = e.max_drawdown > 0 ? -e.max_drawdown : 0;
        return (
          <span
            data-testid={`perf-row-dd-${e.bot_id}`}
            className={ddLoss < 0 ? "u-text-negative" : undefined}
          >
            {ddLoss < 0 ? formatSignedCurrency(ddLoss) : formatCurrency(0)}
          </span>
        );
      },
    },
  ], [selected?.bot_id]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* F4 — the ONLY pane-level live region for selection/refresh summary. */}
      <PerfSummaryLive summary={summary} />
      <div style={{ display: "flex", gap: 24, alignItems: "center", padding: "8px 16px",
                    borderBottom: "1px solid var(--border-card)" }}>
        <KPI label="Total PnL" value={totalPnL} fmt={(v) => formatSignedCurrency(v)} />
        <KPI label="Bot count" value={leaderboard.length} fmt={(v) => formatNumber(v)} />
        <BotPill
          label="Leader"
          entry={topPerformer}
          tone={topPerformer && topPerformer.total_pnl >= 0 ? "ok" : "err"}
          testId="perf-kpi-leader"
        />
        <BotPill
          label="Top gainer"
          entry={positiveBest}
          tone="ok"
          signPrefix="+"
          testId="perf-kpi-top-gainer"
        />
        <BotPill
          label="Laggard"
          entry={bottomPerformer}
          tone={bottomPerformer && bottomPerformer.total_pnl >= 0 ? "mute" : "err"}
          testId="perf-kpi-laggard"
        />
        <BotPill
          label="Top loser"
          entry={negativeWorst}
          tone="err"
          testId="perf-kpi-top-loser"
        />
        {/* F5 — last-updated freshness indicator from the leaderboard's
            generated_at. Honest "—" when the backend hasn't stamped one. */}
        <span
          data-testid="perf-last-updated"
          className="u-text-secondary"
          style={{ marginLeft: "auto", fontSize: "var(--font-size-sm)" }}
        >
          {generatedAt
            ? `Last updated: ${new Date(generatedAt).toLocaleTimeString()}`
            : `Last updated: ${formatMissing}`}
        </span>
        <button
          data-testid="perf-refresh"
          aria-label="Refresh performance data"
          aria-busy={loading}
          disabled={loading}
          onClick={() => loadLeaderboard()}
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* F4 — async error is an announced live region. role="status" already
          implies aria-live="polite", so no redundant aria-live. Rendered at
          the pane root so a load error with no leaderboard is still visible. */}
      {error && (
        <div
          data-testid="perf-pane-error"
          role="status"
          className="u-text-negative"
          style={{ padding: 8 }}
        >
          {error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: selected ? "1fr 1fr" : "1fr",
                    flex: 1, overflow: "hidden" }}>
        <div style={{ overflowY: "auto", padding: 8 }}>
          <div style={{ display: "flex", alignItems: "center" }}>
            <h4 style={{ margin: 0 }}>Leaderboard</h4>
            <button
              data-testid="perf-export-leaderboard-csv"
              type="button"
              onClick={() =>
                downloadGridCsv(
                  gridCsvFilename("perf-leaderboard"),
                  buildGridCsv(LEADERBOARD_CSV_COLUMNS, leaderboard),
                )
              }
              disabled={leaderboard.length === 0}
              title="Download CSV"
              aria-label={`Download ${leaderboard.length} leaderboard rows as CSV`}
              style={{ marginLeft: "auto" }}
            >
              CSV
            </button>
          </div>
          {firstLoad ? (
            <div data-testid="perf-loading" aria-busy="true">
              {Array.from({ length: 5 }).map((_, i) => (
                <SkeletonRow key={i} columns={5} />
              ))}
            </div>
          ) : leaderboard.length === 0 ? (
            <div data-testid="perf-empty">
              <Empty
                title="No performance data yet"
                body="The leaderboard fills here once a bot ticks and closes a trade."
              />
            </div>
          ) : (
            <div style={{ marginTop: 8 }}>
              <DataGrid
                columns={leaderboardColumns}
                rows={leaderboard}
                rowKey={(e) => e.bot_id}
                density="compact"
                ariaLabel="Performance leaderboard"
                // Keep the backend's (-total_pnl, -trade_count) payload order
                // until the user sorts a header (asc → desc → none).
                defaultSortKey="total_pnl"
                defaultSortDir="none"
                onRowClick={(e) => loadBot(e.bot_id)}
              />
            </div>
          )}
        </div>

        {selected && (
          <div style={{ overflowY: "auto", padding: 8, borderLeft: "1px solid var(--border-card)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h4 style={{ margin: 0 }}>{selected.symbol}</h4>
              <button
                onClick={clearSelected}
                aria-label={`${selected.symbol} close details`}
                style={{ marginLeft: "auto" }}
              >
                Close
              </button>
            </div>
            <div style={{ display: "flex", gap: 16, margin: "8px 0", flexWrap: "wrap" }}>
              <KPI label="Trades" value={selected.metrics.trade_count} fmt={(v) => formatNumber(v)} />
              <KPI label="Win %" value={selected.metrics.win_rate}
                   fmt={(v) => formatPercent(v, { fromFraction: true, digits: 0 })} />
              <KPI label="Total PnL" value={selected.metrics.total_pnl} fmt={(v) => formatSignedCurrency(v)} />
              <KPI label="Avg PnL" value={selected.metrics.avg_pnl} fmt={(v) => formatSignedCurrency(v)} />
              {/* F3 — Max DD as a negative loss, red. */}
              <KPI
                label="Max DD"
                value={selected.metrics.max_drawdown > 0 ? -selected.metrics.max_drawdown : 0}
                fmt={(v) => (v < 0 ? formatSignedCurrency(v) : formatCurrency(0))}
              />
            </div>

            {/* F2 — surfaced risk metrics with sample-size honesty. */}
            <RiskMetrics metrics={selected.metrics} />

            <h4 style={{ margin: "8px 0 4px" }}>Equity curve</h4>
            {/* F1 — disclose the curve is SIMULATED + RELATIVE, not a real
                balance, using the returned starting_equity. */}
            <div
              data-testid="perf-equity-disclaimer"
              className="u-text-secondary"
              style={{ fontSize: "var(--font-size-sm)", marginBottom: 4 }}
            >
              Simulated ({formatCurrency(startingEquity)} start) — a relative
              curve accumulating net PnL; not the real account balance.
            </div>
            {/* F1 — fallback-equity warn marker, mirroring BOT/BOTS. */}
            {isFallbackEquity && (
              <div
                data-testid="perf-equity-fallback-warning"
                title="This live bot's orders were sized with the fallback ($10k) balance instead of the real broker balance; PnL is based on that fallback."
                style={{ marginBottom: 4, display: "inline-block" }}
              >
                <Pill tone="warn" variant="soft" withDot={false}>
                  ⚠ fallback $10k equity
                </Pill>
              </div>
            )}
            <EquityCurve points={selected.equity_curve} startingEquity={startingEquity} />

            <div style={{ display: "flex", alignItems: "center", margin: "8px 0 4px" }}>
              <h4 style={{ margin: 0 }}>Trades ({formatNumber(selected.trades.length)})</h4>
              <button
                data-testid="perf-export-trades-csv"
                type="button"
                onClick={() =>
                  downloadGridCsv(
                    gridCsvFilename(
                      `perf-trades-${selected.symbol.replace(/[^A-Za-z0-9_-]+/g, "-")}`,
                    ),
                    buildGridCsv(TRADE_CSV_COLUMNS, [...selected.trades].reverse()),
                  )
                }
                disabled={selected.trades.length === 0}
                title="Download CSV"
                aria-label={`Download all ${selected.trades.length} trades as CSV`}
                style={{ marginLeft: "auto" }}
              >
                CSV
              </button>
            </div>
            {selected.trades.length > TRADES_WINDOW && (
              <div
                data-testid="perf-trades-window-note"
                className="u-text-secondary"
                style={{ fontSize: "var(--font-size-sm)", marginBottom: 4 }}
              >
                Showing the last {TRADES_WINDOW} trades — the CSV export covers
                all {formatNumber(selected.trades.length)}.
              </div>
            )}
            <DataGrid
              columns={TRADE_COLUMNS}
              rows={selected.trades.slice(-TRADES_WINDOW).reverse()}
              density="compact"
              ariaLabel="Recent trades"
              // Newest-first (see F1 caption below); headers cycle asc → desc → none.
              defaultSortKey="entry_time"
              defaultSortDir="none"
              rowKey={(t, i) => `${t.entry_time}-${t.exit_time}-${i}`}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default PERFPane;
