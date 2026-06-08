/**
 * WEI — World equity indices.
 *
 * Bloomberg `WEI<GO>` analogue: live (or 30 s polled) snapshot table
 * for ~60 indices grouped by region. KPI ribbon + per-row sparkline +
 * DeltaChip pills for every Δ field.
 */
import { useMemo, useState, type CSSProperties } from "react";
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
import { formatNumber, formatMissing } from "@/lib/format";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { useWorkspace } from "@/lib/workspace";
import { maxAbsOf } from "@/lib/maxOf";
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
  // Bundle D / PERF-04. `useVisibilityTick` pauses the 30s poll on hidden tabs.
  const tick = useVisibilityTick(REFRESH_MS);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { region: region === "all" ? undefined : region, tick },
  });

  // P4: local sort state for the grid (DataGrid is presentation-only —
  // we own the ordering and pass sortBy/sortDir/onSort through).
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: "change_pct",
    dir: "none",
  });

  const baseRows = useMemo(() => {
    const all = normalizeRows(data?.data);
    if (region === "all") return all;
    return all.filter(
      (r) => (r.region ?? "").toLowerCase() === region.toLowerCase(),
    );
  }, [data, region]);
  const rows = useMemo(
    () => sortRows(baseRows, sort.key, sort.dir),
    [baseRows, sort],
  );
  const notice = useMemo(() => statusNotice(data?.data, data?.metadata), [data]);
  // P2: model/fallback detection — true when the payload is the
  // deterministic world-index model, not live market quotes.
  const isModel = useMemo(
    () => isModelData(baseRows, data?.data, data?.metadata),
    [baseRows, data],
  );
  const stats = useMemo(() => deriveStats(rows), [rows]);
  // P2: prefer the server-stamped data freshness (`as_of`) over the client
  // wall clock so the header reflects REAL data age, not render time.
  const asOf = useMemo(() => extractAsOf(data?.data), [data]);
  const utcStamp = useMemo(
    () => asOf ?? new Date().toISOString().slice(11, 16),
    [asOf, tick],
  );
  const isLive = state === "ok" && !notice && !isModel;

  function onSort(key: string) {
    setSort((prev) => {
      if (prev.key !== key) return { key: key as SortKey, dir: "descending" };
      // Cycle: descending → ascending → none (back to natural order).
      const next: SortDir =
        prev.dir === "descending"
          ? "ascending"
          : prev.dir === "ascending"
            ? "none"
            : "descending";
      return { key: key as SortKey, dir: next };
    });
  }

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
              aria-label={sym ? `View ${sym} details` : "View index details"}
              onClick={() => {
                if (!sym) return;
                setFocusedTarget("DES", sym);
                navigate(`/symbol/${sym}/DES`);
              }}
              className="wei-symbol-button"
            >
              {sym || formatMissing}
            </button>
          );
        },
      },
      {
        key: "name",
        header: "Name",
        render: (r) => (
          <span className="u-text-secondary">{r.name ?? formatMissing}</span>
        ),
      },
      {
        key: "region",
        header: "Region",
        width: 96,
        render: (r) => (r.region ? <RegionChip region={r.region} /> : formatMissing),
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        sortable: true,
        width: 100,
        render: (r) => (
          <span className="terminal-grid-numeric">{fmtIndex(r.last ?? r.price)}</span>
        ),
      },
      {
        key: "change",
        header: "Δ",
        numeric: true,
        sortable: true,
        width: 96,
        render: (r) => {
          const v = rowChange(r);
          if (v == null || !Number.isFinite(v)) return formatMissing;
          return (
            <span className="terminal-grid-numeric">
              <DeltaChip value={v} format="raw" fractionDigits={2} />
            </span>
          );
        },
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        sortable: true,
        width: 92,
        render: (r) => {
          const v = r.change_pct ?? r.changePercent;
          if (v == null) return formatMissing;
          return (
            <span className="terminal-grid-numeric">
              <DeltaChip value={v} format="percent" fractionDigits={2} />
            </span>
          );
        },
      },
      {
        key: "trend",
        header: "5d",
        width: 78,
        render: (r) => {
          // P2 honesty: a real intraday series (r.history) renders at full
          // opacity; otherwise the line is procedural — de-emphasize it and
          // mark it data-synthetic so it can't masquerade as real history.
          const real = hasRealHistory(r);
          const series = trendSeries(r);
          const dir =
            (r.change_pct ?? r.changePercent ?? 0) >= 0 ? "positive" : "negative";
          return (
            <span
              className={real ? "wei-spark wei-spark--real" : "wei-spark wei-spark--synthetic"}
              data-synthetic={real ? "false" : "true"}
              title={
                real
                  ? "Intraday history"
                  : "Illustrative trend — no real history available"
              }
            >
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
          if (r.low == null || r.high == null) return formatMissing;
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
            formatMissing
          ),
      },
    ],
    [setFocusedTarget],
  );

  const sortDir: SortDir = sort.dir;
  const sortBy = sort.dir === "none" ? undefined : sort.key;

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
                tone={isLive ? "positive" : isModel || notice ? "warn" : "muted"}
                variant="soft"
              >
                {isLive ? "live" : isModel ? "model" : notice ? "stale" : state}
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
              {isModel ? <ModelDataBadge /> : null}
              {notice ? <StatusNotice notice={notice} /> : null}
              <Empty title="No quotes" body={`No WEI rows for ${region}.`} />
            </>
          ) : (
            <div className="u-grid-gap-14">
              {isModel ? <ModelDataBadge /> : null}
              {notice ? <StatusNotice notice={notice} /> : null}
              <KPIRibbon stats={stats} stamp={utcStamp} />
              <IndexPerformanceStrip rows={rows} onPick={(sym) => {
                setFocusedTarget("DES", sym);
                navigate(`/symbol/${sym}/DES`);
              }} />
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => `${r.symbol ?? r.ticker ?? ""}-${i}`}
                density="compact"
                sortBy={sortBy}
                sortDir={sortDir}
                onSort={onSort}
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
    <section
      style={kpiGridStyle}
      className="terminal-grid-numeric"
      aria-label="WEI KPI ribbon"
    >
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
        value={stats.leader?.sym ?? formatMissing}
        caption={
          stats.leader
            ? `${stats.leader.chg >= 0 ? "+" : ""}${stats.leader.chg.toFixed(2)}% · ${truncate(stats.leader.name, 18)}`
            : formatMissing
        }
        tone="positive"
        trend={stats.leaderTrend}
      />
      <StatCard
        label="Laggard"
        value={stats.laggard?.sym ?? formatMissing}
        caption={
          stats.laggard
            ? `${stats.laggard.chg.toFixed(2)}% · ${truncate(stats.laggard.name, 18)}`
            : formatMissing
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
    <span style={rangeWrap} className="terminal-grid-numeric">
      <span style={rangeLabel}>{fmtIndex(lo)}</span>
      <span style={rangeTrack}>
        <span style={{ ...rangeFill, left: `${pct}%` }} aria-hidden />
      </span>
      <span style={rangeLabel}>{fmtIndex(hi)}</span>
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
  // Honesty fix: a healthy live snapshot (status "ok"/"" and not degraded)
  // must NOT raise a "Degraded WEI snapshot" notice. Only surface the
  // banner for genuinely non-OK or degraded payloads.
  const okStatus = status === "" || status === "ok";
  if (okStatus && !degraded) return null;
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

/** Stable, prominent "model data — not live" banner. */
function ModelDataBadge() {
  return (
    <div className="wei-model-badge" role="status" aria-label="Model data — not live">
      <span className="wei-model-badge__dot" aria-hidden />
      <strong>Model data — not live</strong>
      <span className="u-text-secondary">
        These rows are a deterministic world-index model, not live market quotes.
      </span>
    </div>
  );
}

// ── Sort ────────────────────────────────────────────────────────────────
type SortKey = "last" | "change" | "change_pct";
type SortDir = "ascending" | "descending" | "none";

function rowChange(r: WEIRow): number | undefined {
  if (r.change != null && Number.isFinite(r.change)) return r.change;
  const last = r.last ?? r.price;
  const prev = r.prev_close;
  if (last == null || prev == null) return undefined;
  return last - prev;
}

function sortValue(r: WEIRow, key: SortKey): number | undefined {
  if (key === "last") return r.last ?? r.price;
  if (key === "change") return rowChange(r);
  return r.change_pct ?? r.changePercent;
}

function sortRows(rows: WEIRow[], key: SortKey, dir: SortDir): WEIRow[] {
  if (dir === "none") return rows;
  const factor = dir === "ascending" ? 1 : -1;
  // Stable sort; missing values always sink to the bottom regardless of dir.
  return [...rows]
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      const va = sortValue(a.r, key);
      const vb = sortValue(b.r, key);
      const aMissing = va == null || !Number.isFinite(va);
      const bMissing = vb == null || !Number.isFinite(vb);
      if (aMissing && bMissing) return a.i - b.i;
      if (aMissing) return 1;
      if (bMissing) return -1;
      if (va !== vb) return (va < vb ? -1 : 1) * factor;
      return a.i - b.i;
    })
    .map((x) => x.r);
}

// ── Data honesty helpers ─────────────────────────────────────────────────
/** True when a row carries a usable real intraday series. */
function hasRealHistory(r: WEIRow): boolean {
  return Array.isArray(r.history) && r.history.length >= 4;
}

/** Extract server data-freshness (`as_of`) as an HH:MM UTC stamp, if present. */
function extractAsOf(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const raw = (payload as Record<string, unknown>).as_of;
  if (typeof raw !== "string" || !raw) return undefined;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString().slice(11, 16);
}

/**
 * Detect model / fallback data: the deterministic world-index template the
 * backend returns when the live provider is unavailable. Treated as model
 * when the metadata flags it degraded/fallback, the payload source mode is
 * the template, or every row is explicitly market_state "model".
 */
function isModelData(
  rows: WEIRow[],
  payload: unknown,
  metadata: Record<string, unknown> | undefined,
): boolean {
  if (metadata?.degraded === true || metadata?.fallback === true) return true;
  const o = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const mode = String(o.source_mode ?? "").toLowerCase();
  if (mode === "world_index_template") return true;
  if (String(o.status ?? "").toLowerCase() === "provider_unavailable") return true;
  if (rows.length && rows.every((r) => (r.market_state ?? "").toLowerCase() === "model")) {
    return true;
  }
  return false;
}

function StatusNotice({ notice }: { notice: { title: string; body: string } }) {
  return (
    <div style={noticeStyle}>
      <strong className="u-text-warn">{notice.title}</strong>
      <span className="u-text-secondary">{notice.body}</span>
    </div>
  );
}

function IndexPerformanceStrip({
  rows,
  onPick,
}: {
  rows: WEIRow[];
  onPick?: (symbol: string) => void;
}) {
  const points = rows
    .map((row) => ({
      symbol: row.symbol ?? row.ticker ?? "-",
      name: row.name ?? row.symbol ?? row.ticker ?? "-",
      change: row.change_pct ?? row.changePercent ?? 0,
      state: row.market_state ?? "-",
    }))
    .slice(0, 16);
  if (!points.length) return null;
  // UA-HIGH-12: stack-safe.
  const maxAbs = maxAbsOf(points.map((p) => p.change), 1);
  return (
    <section style={indexStrip} aria-label="World index performance strip">
      {points.map((point) => {
        const intensity = 0.18 + Math.min(Math.abs(point.change) / maxAbs, 1) * 0.5;
        const tone = point.change >= 0 ? "var(--positive)" : "var(--negative)";
        const bg = `color-mix(in srgb, ${tone} ${(intensity * 100).toFixed(0)}%, transparent)`;
        const sign = point.change >= 0 ? "+" : "";
        const pickable = Boolean(onPick && point.symbol && point.symbol !== "-");
        return (
          <button
            key={point.symbol}
            type="button"
            className="wei-index-tile"
            disabled={!pickable}
            aria-label={`${point.symbol} ${sign}${point.change.toFixed(2)}%`}
            onClick={() => pickable && onPick?.(point.symbol)}
            style={{
              ...indexTile,
              ["--wei-bg" as string]: bg,
              ["--wei-tone" as string]: tone,
            }}
          >
            <strong className="wei-index-tile__sym">{point.symbol}</strong>
            <span className="u-text-secondary u-text-10">{truncate(point.name, 16)}</span>
            <b className="wei-index-tile__chg terminal-grid-numeric">
              {sign}
              {point.change.toFixed(2)}%
            </b>
            <small className="wei-index-tile__state">{point.state}</small>
          </button>
        );
      })}
    </section>
  );
}

/**
 * Index-level numeric formatter — thin wrapper over the shared
 * {@link formatNumber} helper pinned to 2 decimals (DRY; replaces the old
 * local `fmtNum`). Missing values render the shared {@link formatMissing}
 * sentinel.
 */
function fmtIndex(v: number | undefined | null): string {
  return formatNumber(v, 2);
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

// P4: responsive KPI ribbon — wraps to fewer columns in a narrow pane
// instead of squeezing four fixed columns.
const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
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
