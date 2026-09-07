/**
 * RV — Relative Valuation (peer multiples comp table).
 *
 * Body: a comp sheet over the target + peer set returned by the backend —
 * market cap, P/E, fwd P/E, P/B, P/S, EV/EBITDA, ROE, ROA, D/E, div yield
 * and the target's PE rank/percentile. A "Median (peer set, computed)" row
 * is derived client-side from the RETURNED rows (never fabricated) and each
 * metric's best value in the peer set is tinted (lowest for valuation
 * multiples / leverage, highest for returns and yield).
 *
 * Data honesty: when the provider is unavailable the backend returns a
 * single null row; the pane renders an explicit provider-unavailable state
 * listing the resolved peer set instead of an empty comp sheet.
 */
import { useMemo, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface RVRow {
  symbol?: string;
  marketCap?: number | null;
  pe?: number | null;
  fwd_pe?: number | null;
  pb?: number | null;
  ps?: number | null;
  ev_ebitda?: number | null;
  roe?: number | null;
  roa?: number | null;
  debt_equity?: number | null;
  div_yield?: number | null;
  rank_pe?: number | null;
  percentile_pe?: number | null;
  is_target?: boolean;
  is_median_row?: boolean;
  source_mode?: string;
}

interface RVData {
  status?: string;
  rows?: RVRow[];
  peers?: string[];
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

type Better = "low" | "high";

interface MetricDef {
  key: keyof RVRow;
  header: string;
  better: Better;
  fmt: (v: unknown) => string;
}

const METRICS: MetricDef[] = [
  { key: "marketCap", header: "Mkt cap", better: "low", fmt: (v) => fmtCompact(v) },
  { key: "pe", header: "P/E", better: "low", fmt: (v) => fmtMult(v) },
  { key: "fwd_pe", header: "Fwd P/E", better: "low", fmt: (v) => fmtMult(v) },
  { key: "pb", header: "P/B", better: "low", fmt: (v) => fmtMult(v) },
  { key: "ps", header: "P/S", better: "low", fmt: (v) => fmtMult(v) },
  { key: "ev_ebitda", header: "EV/EBITDA", better: "low", fmt: (v) => fmtMult(v) },
  { key: "roe", header: "ROE", better: "high", fmt: (v) => fmtRatioPct(v) },
  { key: "roa", header: "ROA", better: "high", fmt: (v) => fmtRatioPct(v) },
  { key: "debt_equity", header: "D/E", better: "low", fmt: (v) => fmtDePct(v) },
  { key: "div_yield", header: "Div yld", better: "high", fmt: (v) => fmtRatioPct(v) },
];

const MEDIAN_LABEL = "Median (peer set, computed)";

export function RVPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const { state, data, error, refetch } = useFunction<RVData>({
    code,
    symbol: effectiveSymbol,
    params: {},
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: RVRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const providerDown =
    state === "ok" &&
    (status === "provider_unavailable" ||
      (rows.length === 1 && rows[0].source_mode === "provider_unavailable"));

  const target = rows.find((r) => r.is_target) ?? null;
  const medianRow = useMemo(() => computeMedianRow(rows), [rows]);
  const bestByMetric = useMemo(() => computeBestByMetric(rows), [rows]);
  const cheapestPeer = useMemo(() => {
    const peers = rows.filter((r) => !r.is_target && finite(r.pe) != null);
    if (!peers.length) return null;
    return peers.reduce((a, b) => ((finite(a.pe) ?? Infinity) <= (finite(b.pe) ?? Infinity) ? a : b));
  }, [rows]);

  const COLS: DataGridColumn<RVRow>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 200,
        render: (r) =>
          r.is_median_row ? (
            <span style={medianLabelStyle}>{MEDIAN_LABEL}</span>
          ) : (
            <span style={monoStrongStyle}>
              {r.symbol ?? "—"}
              {r.is_target ? (
                <Pill tone="accent" variant="soft" withDot={false}>
                  target
                </Pill>
              ) : null}
            </span>
          ),
      },
      ...METRICS.map(
        (m): DataGridColumn<RVRow> => ({
          key: String(m.key),
          header: m.header,
          numeric: true,
          width: m.key === "marketCap" ? 116 : 96,
          render: (r) => {
            if (r.is_median_row) {
              return <span style={monoMedianStyle}>{m.fmt(r[m.key])}</span>;
            }
            const best = bestByMetric.get(String(m.key)) === r.symbol;
            return (
              <span
                className={best ? "rv-best" : undefined}
                style={best ? bestCellStyle : monoPrimaryStyle}
                title={
                  best
                    ? m.better === "low"
                      ? "Lowest in peer set"
                      : "Highest in peer set"
                    : undefined
                }
              >
                {m.fmt(r[m.key])}
              </span>
            );
          },
        }),
      ),
      {
        key: "rank_pe",
        header: "PE rank",
        numeric: true,
        width: 104,
        render: (r) =>
          r.is_median_row ? (
            <span style={monoMedianStyle}>—</span>
          ) : (
            <span style={monoMutedStyle}>
              {finite(r.rank_pe) != null
                ? `${finite(r.rank_pe)} · ${finite(r.percentile_pe)?.toFixed(0) ?? "—"}pct`
                : "—"}
            </span>
          ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 150,
        render: (r) =>
          r.is_median_row ? (
            <span style={monoMedianStyle}>computed</span>
          ) : r.source_mode ? (
            <Pill
              tone={
                (r.source_mode ?? "").includes("unavailable") ? "warn" : "muted"
              }
              variant="soft"
              withDot={false}
            >
              {r.source_mode}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [bestByMetric],
  );

  const targetPeDeltaPct = useMemo(() => {
    const tpe = finite(target?.pe);
    const mpe = finite(medianRow.pe);
    if (tpe == null || mpe == null || mpe === 0) return null;
    return ((tpe - mpe) / mpe) * 100;
  }, [target, medianRow]);

  const tableRows: RVRow[] = useMemo(
    () => (rows.length ? [...rows, { ...medianRow, is_median_row: true }] : []),
    [rows, medianRow],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="RV needs an equity ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
    </div>
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
  ) : providerDown || rows.length === 0 ? (
    <Empty
      title="Provider unavailable"
      body={
        payload?.peers?.length
          ? `Peer set resolved (${payload.peers.join(", ")}) but multiples could not be fetched. Retry when the refdata provider recovers.`
          : "No peer multiples were returned for this symbol."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="RV KPI ribbon">
        <StatCard
          label="Peer set"
          value={String(rows.length)}
          caption={payload?.peers?.slice(0, 4).join(" ") ?? "—"}
          tone="neutral"
        />
        <StatCard
          label="Target P/E"
          value={fmtMult(target?.pe)}
          caption={
            targetPeDeltaPct != null
              ? `${targetPeDeltaPct >= 0 ? "+" : ""}${targetPeDeltaPct.toFixed(1)}% VS MEDIAN`
              : "VS MEDIAN —"
          }
          tone={targetPeDeltaPct == null ? "neutral" : targetPeDeltaPct <= 0 ? "positive" : "negative"}
        />
        <StatCard
          label="PE percentile"
          value={finite(target?.percentile_pe) != null ? `${finite(target?.percentile_pe)?.toFixed(0)}th` : "—"}
          caption="LOWER = CHEAPER"
          tone="neutral"
        />
        <StatCard
          label="Cheapest peer"
          value={cheapestPeer?.symbol ?? "—"}
          caption={`P/E ${fmtMult(cheapestPeer?.pe)}`}
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={tableRows}
        rowKey={(r, i) => `${r.symbol ?? ""}-${r.is_median_row ? "med" : i}`}
        density="compact"
        ariaLabel="RV peer multiples comp table"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Relative Valuation — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} vs ${rows.filter((r) => !r.is_target).length} peers`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} names
              </Pill>
              <Pill
                tone={status === "ok" ? "positive" : "warn"}
                variant="soft"
              >
                {status === "ok" ? "live" : status}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh comp table"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="median" value="computed" tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── derived rows ──────────────────────────────────────────────────── */

/** Median per metric across the RETURNED rows (client-side derivation). */
function computeMedianRow(rows: RVRow[]): RVRow {
  const out: RVRow = { symbol: MEDIAN_LABEL };
  const writable = out as unknown as Record<string, unknown>;
  for (const m of METRICS) {
    const vals = rows
      .map((r) => finite(r[m.key]))
      .filter((v): v is number => v != null)
      .sort((a, b) => a - b);
    if (!vals.length) {
      writable[String(m.key)] = null;
      continue;
    }
    const mid = Math.floor(vals.length / 2);
    writable[String(m.key)] =
      vals.length % 2 === 1 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
  }
  return out;
}

/** Best symbol per metric according to the metric direction. */
function computeBestByMetric(rows: RVRow[]): Map<string, string | undefined> {
  const best = new Map<string, string | undefined>();
  if (rows.length < 2) return best;
  for (const m of METRICS) {
    let bestSym: string | undefined;
    let bestVal: number | null = null;
    for (const r of rows) {
      const v = finite(r[m.key]);
      if (v == null || !r.symbol) continue;
      if (
        bestVal == null ||
        (m.better === "low" && v < bestVal) ||
        (m.better === "high" && v > bestVal)
      ) {
        bestVal = v;
        bestSym = r.symbol;
      }
    }
    best.set(String(m.key), bestSym);
  }
  return best;
}

/* ── formatting ────────────────────────────────────────────────────── */

function fmtMult(v: unknown): string {
  const n = finite(v);
  return n == null ? "—" : n.toFixed(2);
}

/** ROE/ROA/yield arrive as fractions (0.25 = 25%); normalize honestly. */
function fmtRatioPct(v: unknown): string {
  const n = finite(v);
  if (n == null) return "—";
  const pct = Math.abs(n) <= 3 ? n * 100 : n;
  return `${pct.toFixed(1)}%`;
}

/** yfinance debtToEquity is percent-like (145 = 145%); normalize. */
function fmtDePct(v: unknown): string {
  const n = finite(v);
  if (n == null) return "—";
  const pct = Math.abs(n) <= 15 ? n * 100 : n;
  return `${pct.toFixed(1)}%`;
}

function fmtCompact(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function finite(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const bestCellStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--positive)",
  fontWeight: 700,
  background: "var(--positive-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "1px 4px",
};

const medianLabelStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontStyle: "italic",
  fontSize: "var(--font-size-xs)",
};

const monoMedianStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
  fontStyle: "italic",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
