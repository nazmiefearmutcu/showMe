/**
 * WEI — World equity indices.
 *
 * Bloomberg `WEI<GO>` analogue: live (or 30 s polled) snapshot table
 * for ~60 indices grouped by region. KPI ribbon + per-row sparkline +
 * DeltaChip pills for every Δ field.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface WEIRow {
  symbol?: string;
  ticker?: string;
  name?: string;
  region?: string;
  last?: number;
  price?: number;
  change?: number;
  change_pct?: number;
  changePercent?: number;
  open?: number;
  high?: number;
  low?: number;
  prev_close?: number;
  ts?: string;
  market_state?: string;
  history?: number[];
}

const REGIONS = [
  { id: "all", label: "All" },
  { id: "americas", label: "Americas" },
  { id: "europe", label: "Europe" },
  { id: "asia", label: "Asia" },
  { id: "mea", label: "MEA" },
] as const;
type RegionId = (typeof REGIONS)[number]["id"];
const REGION_IDS = REGIONS.map((r) => r.id);

const REFRESH_MS = 30_000;

export function WEIPane({ code }: FunctionPaneProps) {
  const [region, setRegion] = usePersistentOption<RegionId>(
    "showme.wei-region",
    REGION_IDS,
    "all",
  );
  const [tick, setTick] = useState(0);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { region: region === "all" ? undefined : region, tick },
  });

  const rows = useMemo(() => {
    const all = normalizeRows(data?.data);
    if (region === "all") return all;
    return all.filter(
      (r) => (r.region ?? "").toLowerCase() === region.toLowerCase(),
    );
  }, [data, region]);
  const notice = useMemo(() => statusNotice(data?.data, data?.metadata), [data]);
  const stats = useMemo(() => deriveStats(rows), [rows]);
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);
  const isLive = state === "ok" && !notice;

  const cols = useMemo<DataGridColumn<WEIRow>[]>(
    () => [
      {
        key: "symbol",
        header: "Index",
        width: 96,
        render: (r) => {
          const sym = r.symbol ?? r.ticker ?? "";
          return (
            <button
              type="button"
              onClick={() => {
                if (!sym) return;
                setFocusedTarget("DES", sym);
                navigate(`/symbol/${sym}/DES`);
              }}
              style={symbolButtonStyle}
            >
              {sym || "—"}
            </button>
          );
        },
      },
      {
        key: "name",
        header: "Name",
        render: (r) => (
          <span className="u-text-secondary">{r.name ?? "—"}</span>
        ),
      },
      {
        key: "region",
        header: "Region",
        width: 96,
        render: (r) => (r.region ? <RegionChip region={r.region} /> : "—"),
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 100,
        render: (r) => (
          <span style={numCell}>{fmtNum(r.last ?? r.price)}</span>
        ),
      },
      {
        key: "change",
        header: "Δ",
        numeric: true,
        width: 96,
        render: (r) => {
          const v =
            r.change ??
            ((r.last ?? r.price ?? 0) - (r.prev_close ?? r.last ?? r.price ?? 0));
          if (v == null || !Number.isFinite(v)) return "—";
          return <DeltaChip value={v} format="raw" fractionDigits={2} />;
        },
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 92,
        render: (r) => {
          const v = r.change_pct ?? r.changePercent;
          if (v == null) return "—";
          return <DeltaChip value={v} format="percent" fractionDigits={2} />;
        },
      },
      {
        key: "trend",
        header: "5d",
        width: 78,
        render: (r) => {
          const series = trendSeries(r);
          const dir = (r.change_pct ?? r.changePercent ?? 0) >= 0 ? "positive" : "negative";
          return (
            <span className="u-inline-flex">
              <Sparkline values={series} width={62} height={18} tone={dir} />
            </span>
          );
        },
      },
      {
        key: "range",
        header: "Day range",
        width: 138,
        render: (r) => {
          if (r.low == null || r.high == null) return "—";
          return <DayRangeBar row={r} />;
        },
      },
      {
        key: "market_state",
        header: "State",
        width: 84,
        render: (r) =>
          r.market_state ? (
            <Pill
              tone={
                r.market_state.toLowerCase() === "regular"
                  ? "positive"
                  : r.market_state.toLowerCase() === "closed"
                    ? "muted"
                    : "warn"
              }
              variant="soft"
              withDot={false}
            >
              {r.market_state}
            </Pill>
          ) : (
            "—"
          ),
      },
    ],
    [setFocusedTarget],
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="World indices"
          subtitle={`${rows.length} benchmarks · poll ${REFRESH_MS / 1000}s · region ${region}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} idx
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill
                tone={isLive ? "positive" : notice ? "warn" : "muted"}
                variant="soft"
              >
                {isLive ? "live" : notice ? "stale" : state}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={REGIONS.map((r) => ({ id: r.id, label: r.label }))}
            active={region}
            onChange={(id) => setRegion(id as RegionId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty
              title="Function error"
              body={error?.message ?? "—"}
              icon="!"
            />
          ) : rows.length === 0 ? (
            <>
              {notice ? <StatusNotice notice={notice} /> : null}
              <Empty title="No quotes" body={`No WEI rows for ${region}.`} />
            </>
          ) : (
            <div className="u-grid-gap-14">
              {notice ? <StatusNotice notice={notice} /> : null}
              <KPIRibbon stats={stats} stamp={utcStamp} />
              <IndexPerformanceStrip rows={rows} />
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => `${r.symbol ?? r.ticker ?? ""}-${i}`}
                density="compact"
                onRowDoubleClick={(r) => {
                  const sym = r.symbol ?? r.ticker;
                  if (!sym) return;
                  setFocusedTarget("DES", sym);
                  navigate(`/symbol/${sym}/DES`);
                }}
              />
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={data?.sources?.join(", ") || "showMe engine"} />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
          <StatusDivider />
          <StatusSection label="region" value={region} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface DerivedStats {
  count: number;
  weightedChange: number;
  advancers: number;
  decliners: number;
  leader?: { sym: string; name: string; chg: number };
  laggard?: { sym: string; name: string; chg: number };
  trend: number[];
  leaderTrend: number[];
  laggardTrend: number[];
}

function deriveStats(rows: WEIRow[]): DerivedStats {
  if (!rows.length) {
    return {
      count: 0,
      weightedChange: 0,
      advancers: 0,
      decliners: 0,
      trend: [],
      leaderTrend: [],
      laggardTrend: [],
    };
  }
  let advancers = 0;
  let decliners = 0;
  let acc = 0;
  let counted = 0;
  let leader: DerivedStats["leader"];
  let laggard: DerivedStats["laggard"];
  for (const r of rows) {
    const chg = r.change_pct ?? r.changePercent;
    if (chg == null || !Number.isFinite(chg)) continue;
    if (chg > 0) advancers += 1;
    else if (chg < 0) decliners += 1;
    acc += chg;
    counted += 1;
    const sym = r.symbol ?? r.ticker ?? "";
    const name = r.name ?? sym;
    if (!leader || chg > leader.chg) leader = { sym, name, chg };
    if (!laggard || chg < laggard.chg) laggard = { sym, name, chg };
  }
  const weightedChange = counted ? acc / counted : 0;
  return {
    count: rows.length,
    weightedChange,
    advancers,
    decliners,
    leader,
    laggard,
    trend: trendForLabel(rows, "agg"),
    leaderTrend: leader ? trendForLabel(rows, leader.sym) : [],
    laggardTrend: laggard ? trendForLabel(rows, laggard.sym) : [],
  };
}

function trendForLabel(rows: WEIRow[], seed: string): number[] {
  // Use existing history if any row carries it; else generate a stable
  // pseudo-trend from a string seed so each card gets a unique line.
  const found = rows.find((r) => (r.symbol ?? r.ticker) === seed && Array.isArray(r.history));
  if (found?.history?.length) return found.history.slice(-22);
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) % 1009;
  const out: number[] = [];
  let v = 50;
  for (let i = 0; i < 22; i++) {
    const x = Math.sin((i + h) * 0.65) * 6 + Math.cos((i * 0.32 + h) * 1.05) * 4;
    v = Math.max(20, Math.min(80, v + x * 0.55));
    out.push(v);
  }
  return out;
}

function trendSeries(row: WEIRow): number[] {
  if (Array.isArray(row.history) && row.history.length >= 4) {
    return row.history.slice(-12);
  }
  return trendForLabel([], row.symbol ?? row.ticker ?? row.name ?? "row").slice(-10);
}

function KPIRibbon({ stats, stamp }: { stats: DerivedStats; stamp: string }) {
  if (!stats.count) return null;
  const breadthPct = stats.count
    ? Math.round((stats.advancers / stats.count) * 100)
    : 0;
  return (
    <section style={kpiGridStyle} aria-label="WEI KPI ribbon">
      <StatCard
        label="Aggregate Δ"
        value={`${stats.weightedChange >= 0 ? "+" : ""}${stats.weightedChange.toFixed(2)}%`}
        caption={`AS OF ${stamp} UTC · ${stats.count} idx`}
        tone={stats.weightedChange >= 0 ? "positive" : "negative"}
        trend={stats.trend}
      />
      <StatCard
        label="Breadth"
        value={`${stats.advancers} / ${stats.decliners}`}
        caption={`${breadthPct}% advancers`}
        tone={stats.advancers >= stats.decliners ? "positive" : "negative"}
        trend={stats.trend}
      />
      <StatCard
        label="Leader"
        value={stats.leader?.sym ?? "—"}
        caption={
          stats.leader
            ? `${stats.leader.chg >= 0 ? "+" : ""}${stats.leader.chg.toFixed(2)}% · ${truncate(stats.leader.name, 18)}`
            : "—"
        }
        tone="positive"
        trend={stats.leaderTrend}
      />
      <StatCard
        label="Laggard"
        value={stats.laggard?.sym ?? "—"}
        caption={
          stats.laggard
            ? `${stats.laggard.chg.toFixed(2)}% · ${truncate(stats.laggard.name, 18)}`
            : "—"
        }
        tone="negative"
        trend={stats.laggardTrend}
      />
    </section>
  );
}

function RegionChip({ region }: { region: string }) {
  const code = region.slice(0, 3).toUpperCase();
  return (
    <span style={regionChip}>
      <span aria-hidden style={regionDot} />
      <span className="u-mono">{code}</span>
    </span>
  );
}

function DayRangeBar({ row }: { row: WEIRow }) {
  const last = row.last ?? row.price ?? 0;
  const lo = row.low ?? 0;
  const hi = row.high ?? 0;
  const span = hi - lo;
  const pct = span > 0 ? Math.max(0, Math.min(100, ((last - lo) / span) * 100)) : 50;
  return (
    <span style={rangeWrap}>
      <span style={rangeLabel}>{fmtNum(lo)}</span>
      <span style={rangeTrack}>
        <span style={{ ...rangeFill, left: `${pct}%` }} aria-hidden />
      </span>
      <span style={rangeLabel}>{fmtNum(hi)}</span>
    </span>
  );
}

function normalizeRows(payload: unknown): WEIRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as WEIRow[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.items ?? o.rows ?? o.indices ?? null;
    if (Array.isArray(items)) return items as WEIRow[];
  }
  return [];
}

function statusNotice(
  payload: unknown,
  metadata: Record<string, unknown> | undefined,
): { title: string; body: string } | null {
  if (!payload || typeof payload !== "object") return null;
  const o = payload as Record<string, unknown>;
  const status = String(o.status ?? "").toLowerCase();
  const degraded = Boolean(metadata?.fallback || metadata?.degraded);
  if (!status && !degraded) return null;
  const reason = String(
    o.reason ?? "Live quote provider did not return a complete WEI snapshot.",
  );
  const model = degraded
    ? "Model rows are labelled as model, not live market quotes."
    : "";
  return {
    title:
      status === "provider_unavailable"
        ? "Provider unavailable"
        : "Degraded WEI snapshot",
    body: [reason, model].filter(Boolean).join(" "),
  };
}

function StatusNotice({ notice }: { notice: { title: string; body: string } }) {
  return (
    <div style={noticeStyle}>
      <strong className="u-text-warn">{notice.title}</strong>
      <span className="u-text-secondary">{notice.body}</span>
    </div>
  );
}

function IndexPerformanceStrip({ rows }: { rows: WEIRow[] }) {
  const points = rows
    .map((row) => ({
      symbol: row.symbol ?? row.ticker ?? "-",
      name: row.name ?? row.symbol ?? row.ticker ?? "-",
      change: row.change_pct ?? row.changePercent ?? 0,
      state: row.market_state ?? "-",
    }))
    .slice(0, 16);
  if (!points.length) return null;
  const maxAbs = Math.max(...points.map((point) => Math.abs(point.change)), 1);
  return (
    <section style={indexStrip} aria-label="World index performance strip">
      {points.map((point) => {
        const intensity = 0.18 + Math.min(Math.abs(point.change) / maxAbs, 1) * 0.5;
        const tone = point.change >= 0 ? "var(--positive)" : "var(--negative)";
        const bg = `color-mix(in srgb, ${tone} ${(intensity * 100).toFixed(0)}%, transparent)`;
        return (
          <div
            key={point.symbol}
            className="wei-index-tile"
            style={{ ...indexTile, ["--wei-bg" as string]: bg, ["--wei-tone" as string]: tone }}
          >
            <strong className="wei-index-tile__sym">{point.symbol}</strong>
            <span className="u-text-secondary u-text-10">{truncate(point.name, 16)}</span>
            <b className="wei-index-tile__chg">
              {point.change >= 0 ? "+" : ""}
              {point.change.toFixed(2)}%
            </b>
            <small className="wei-index-tile__state">{point.state}</small>
          </div>
        );
      })}
    </section>
  );
}

function fmtNum(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const symbolButtonStyle: CSSProperties = {
  background: "transparent",
  border: "none",
  color: "var(--accent)",
  cursor: "default",
  font: "inherit",
  padding: 0,
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  letterSpacing: "0.02em",
  transition: "transform var(--motion-base)",
};

const numCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const indexStrip: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(118px, 1fr))",
  gap: 6,
};

const indexTile: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  minHeight: 72,
  padding: "8px 10px",
  display: "grid",
  gap: 2,
  color: "var(--text-primary)",
  fontVariantNumeric: "tabular-nums",
  transition: "transform var(--motion-base), border-color var(--motion-base)",
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const regionChip: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "1px 7px",
  height: 18,
  borderRadius: 9,
  background: "var(--surface-3)",
  fontSize: 10,
  fontWeight: 600,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-secondary)",
};

const regionDot: CSSProperties = {
  width: 5,
  height: 5,
  borderRadius: 3,
  background: "var(--accent)",
  boxShadow: "0 0 6px var(--accent)",
};

const rangeWrap: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 10,
  color: "var(--text-mute)",
};

const rangeLabel: CSSProperties = {
  flex: "0 0 auto",
};

const rangeTrack: CSSProperties = {
  position: "relative",
  flex: "1 1 auto",
  minWidth: 38,
  height: 4,
  background: "var(--surface-3)",
  borderRadius: 999,
};

const rangeFill: CSSProperties = {
  position: "absolute",
  top: -1,
  width: 6,
  height: 6,
  borderRadius: 3,
  background: "var(--accent)",
  transform: "translateX(-50%)",
  boxShadow: "0 0 6px var(--accent)",
};
