/**
 * DPF — Dark Pool / ATS Volume.
 *
 * FINRA-reported weekly off-exchange (ATS) share volume + estimated dark-pool
 * percent of total. Header: weeks segmented control + status pill + refresh.
 * Body: KPI ribbon (weeks, latest ATS volume, latest dark-pool %, avg dark-pool
 * %) + dense weekly table with source_mode pill.
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
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface DPFRow {
  weekStartDate?: string;
  ats_share_volume?: number;
  ats_trade_count?: number;
  estimated_total_volume?: number;
  dark_pool_pct?: number;
  source_mode?: string;
  data_warning?: string;
}

interface DPFData {
  status?: string;
  reason?: string;
  weekly?: DPFRow[];
  rows?: DPFRow[];
  history?: DPFRow[];
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

const WEEKS_OPTIONS = [
  { value: 4, label: "4w" },
  { value: 8, label: "8w" },
  { value: 12, label: "12w" },
  { value: 26, label: "26w" },
] as const;
const WEEKS_IDS = WEEKS_OPTIONS.map((o) => o.value);

export function DPFPane({ code, symbol }: FunctionPaneProps) {
  const [weeks, setWeeks] = usePersistentOption<number>(
    "showme.dpf.weeks",
    WEEKS_IDS,
    12,
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<DPFData>({
    code,
    symbol: effectiveSymbol,
    params: { weeks },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: DPFRow[] = useMemo(
    () =>
      (payload?.weekly && payload.weekly.length
        ? payload.weekly
        : payload?.rows ?? []) as DPFRow[],
    [payload],
  );

  const stats = useMemo(() => deriveStats(rows), [rows]);
  const status = payload?.status ?? "—";
  const isLive = state === "ok" && status === "ok";

  const COLS: DataGridColumn<DPFRow>[] = useMemo(
    () => [
      {
        key: "weekStartDate",
        header: "Week start",
        width: 124,
        render: (r) => (
          <span style={monoPrimaryStyle}>
            {String(r.weekStartDate ?? "—").slice(0, 10)}
          </span>
        ),
      },
      {
        key: "ats_share_volume",
        header: "ATS volume",
        numeric: true,
        width: 132,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtCompact(r.ats_share_volume)}</span>
        ),
      },
      {
        key: "ats_trade_count",
        header: "Trades",
        numeric: true,
        width: 96,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtCompact(r.ats_trade_count)}</span>
        ),
      },
      {
        key: "estimated_total_volume",
        header: "Est. total",
        numeric: true,
        width: 124,
        render: (r) => (
          <span style={monoMutedStyle}>
            {fmtCompact(r.estimated_total_volume)}
          </span>
        ),
      },
      {
        key: "dark_pool_pct",
        header: "Dark %",
        numeric: true,
        width: 92,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtPct(r.dark_pool_pct)}</span>
        ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 196,
        render: (r) =>
          r.source_mode ? (
            <Pill
              tone={
                r.source_mode.includes("stale") || r.data_warning
                  ? "warn"
                  : r.source_mode.includes("model") ||
                      r.source_mode.includes("labelled")
                    ? "muted"
                    : "accent"
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
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="DPF needs an equity / ETF ticker." icon="⌖" />
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
  ) : rows.length === 0 ? (
    <Empty
      title="No FINRA weeks returned"
      body={payload?.reason ?? "Provider returned no ATS rows for this window."}
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="DPF KPI ribbon">
        <StatCard
          label="Weeks"
          value={String(rows.length)}
          caption={`AS OF ${(rows[0]?.weekStartDate ?? "").slice(0, 10) || "—"}`}
          tone="neutral"
        />
        <StatCard
          label="Latest ATS vol"
          value={fmtCompact(stats.latestAts)}
          caption={`PREV ${fmtCompact(stats.prevAts)}`}
          tone={stats.atsDelta >= 0 ? "positive" : "negative"}
          trend={stats.atsTrend}
        />
        <StatCard
          label="Latest dark %"
          value={fmtPct(stats.latestPct)}
          caption={`AVG ${fmtPct(stats.avgPct)}`}
          tone="neutral"
          trend={stats.pctTrend}
        />
        <StatCard
          label="Total ATS"
          value={fmtCompact(stats.totalAts)}
          caption={`${rows.length}W WINDOW`}
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.weekStartDate ?? ""}-${i}`}
        density="compact"
        ariaLabel="DPF weekly ATS volume"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Dark Pool / ATS — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${rows.length} weeks`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} wk
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              <SegmentedControl
                label="WEEKS"
                value={weeks}
                options={WEEKS_OPTIONS}
                onChange={setWeeks}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh ATS feed"
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
          <StatusSection label="weeks" value={weeks} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface DPFStats {
  latestAts: number | null;
  prevAts: number | null;
  atsDelta: number;
  totalAts: number | null;
  latestPct: number | null;
  avgPct: number | null;
  atsTrend: number[];
  pctTrend: number[];
}

function deriveStats(rows: DPFRow[]): DPFStats {
  if (!rows.length) {
    return {
      latestAts: null,
      prevAts: null,
      atsDelta: 0,
      totalAts: null,
      latestPct: null,
      avgPct: null,
      atsTrend: [],
      pctTrend: [],
    };
  }
  const atsVals = rows
    .map((r) => (typeof r.ats_share_volume === "number" ? r.ats_share_volume : null))
    .filter((v): v is number => v != null && Number.isFinite(v));
  const pctVals = rows
    .map((r) => (typeof r.dark_pool_pct === "number" ? r.dark_pool_pct : null))
    .filter((v): v is number => v != null && Number.isFinite(v));
  const latestAts = atsVals[0] ?? null;
  const prevAts = atsVals[1] ?? null;
  const total = atsVals.reduce((acc, v) => acc + v, 0);
  const avg = pctVals.length ? pctVals.reduce((a, v) => a + v, 0) / pctVals.length : null;
  // Reverse for chronological order in sparkline.
  return {
    latestAts,
    prevAts,
    atsDelta:
      latestAts != null && prevAts ? ((latestAts - prevAts) / prevAts) * 100 : 0,
    totalAts: atsVals.length ? total : null,
    latestPct: pctVals[0] ?? null,
    avgPct: avg,
    atsTrend: atsVals.slice(0, 22).reverse(),
    pctTrend: pctVals.slice(0, 22).reverse(),
  };
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
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function fmtPct(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n.toFixed(2)}%`;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
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
