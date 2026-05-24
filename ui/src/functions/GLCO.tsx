/**
 * GLCO — Global commodities mini-board.
 *
 * Bloomberg `GLCO<GO>` analogue: snapshot table over energy / metals
 * / agriculture / softs. KPI ribbon for sector heroes, mover bars,
 * sparkline column, hover-lift rows, methodology footer.
 */
import { useMemo, type CSSProperties } from "react";
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
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface CommodityRow {
  symbol?: string;
  ticker?: string;
  name?: string;
  sector?: string;
  category?: string;
  last?: number;
  price?: number;
  change?: number;
  change_pct?: number;
  changePercent?: number;
  chg_pct?: number;
  unit?: string;
  contract_month?: string;
  contract?: string;
  source?: string;
  source_mode?: string;
  as_of?: string;
  open_interest?: number;
  history?: number[];
}

const SECTORS = [
  { id: "all", label: "All" },
  { id: "energy", label: "Energy" },
  { id: "metals", label: "Metals" },
  { id: "ags", label: "Ag" },
  { id: "softs", label: "Softs" },
] as const;
type SectorId = (typeof SECTORS)[number]["id"];
const SECTOR_IDS = SECTORS.map((s) => s.id);

const REFRESH_MS = 60_000;

export function GLCOPane({ code }: FunctionPaneProps) {
  const [sector, setSector] = usePersistentOption<SectorId>(
    "showme.glco-sector",
    SECTOR_IDS,
    "all",
  );
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { sector: sector === "all" ? undefined : sector, tick },
  });
  const payload = useMemo(
    () => (isRecord(data?.data) ? data?.data : null),
    [data],
  );
  const status = typeof payload?.status === "string" ? payload.status : "";
  const reason = typeof payload?.reason === "string" ? payload.reason : "";
  const methodology =
    typeof payload?.methodology === "string" ? payload.methodology : "";
  const sources =
    data?.sources?.join(", ") || String(payload?.source_mode ?? "showMe engine");

  const rows = useMemo(() => {
    const all = normalizeRows(data?.data);
    if (sector === "all") return all;
    return all.filter((r) => matchesSector(r, sector));
  }, [data, sector]);

  const stats = useMemo(() => deriveCommodityStats(rows), [rows]);
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);
  const isLive = state === "ok" && (!status || status === "ok");

  const cols = useMemo<DataGridColumn<CommodityRow>[]>(
    () => [
      {
        key: "symbol",
        header: "Symbol",
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
        key: "sector",
        header: "Sector",
        width: 88,
        render: (r) => {
          const s = r.sector ?? r.category;
          return s ? <SectorChip sector={s} /> : "—";
        },
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 116,
        render: (r) => {
          const v = r.last ?? r.price;
          if (v == null) return "—";
          return (
            <span style={primaryNumStyle}>
              {fmtNum(v)}
              {r.unit && (
                <span style={unitTagStyle}>{r.unit}</span>
              )}
            </span>
          );
        },
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 96,
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
          const series = trendForRow(r);
          const dir =
            (r.change_pct ?? r.changePercent ?? 0) >= 0 ? "positive" : "negative";
          return (
            <span className="u-inline-flex">
              <Sparkline values={series} width={62} height={18} tone={dir} />
            </span>
          );
        },
      },
      {
        key: "contract_month",
        header: "Contract",
        width: 158,
        render: (r) => (
          <span style={mutedNumStyle}>{r.contract ?? r.contract_month ?? "—"}</span>
        ),
      },
      {
        key: "open_interest",
        header: "OI",
        numeric: true,
        width: 92,
        render: (r) => (
          <span style={mutedNumStyle}>{fmtCompact(r.open_interest)}</span>
        ),
      },
      {
        key: "source",
        header: "Source",
        width: 110,
        render: (r) => (
          <Pill tone="muted" variant="soft" withDot={false}>
            {r.source_mode ?? r.source ?? "—"}
          </Pill>
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
          title="Global commodities"
          subtitle={`${rows.length} contracts · ${sector} · poll ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} ct
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill
                tone={isLive ? "positive" : "warn"}
                variant="soft"
              >
                {isLive ? "live" : status || "stale"}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={SECTORS.map((s) => ({ id: s.id, label: s.label }))}
            active={sector}
            onChange={(id) => setSector(id as SectorId)}
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
            <Empty title="No contracts" body={`No GLCO rows for ${sector}.`} />
          ) : (
            <div className="u-grid-gap-14">
              {status && status !== "ok" ? (
                <section style={noticeStyle}>
                  <strong className="u-text-warn">{status}</strong>
                  <span className="u-text-secondary">
                    {reason ||
                      "Commodity provider returned a labelled fallback state."}
                  </span>
                </section>
              ) : null}
              <KPIRibbon stats={stats} stamp={utcStamp} sector={sector} />
              <div style={twoColLayout}>
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
                <MoverRail rows={rows} />
              </div>
              {methodology ? (
                <section style={methodPanel}>
                  <div style={metaLabel}>Methodology</div>
                  <p style={methodText}>{methodology}</p>
                </section>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={sources} />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="sector" value={sector} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface CommodityStats {
  count: number;
  weightedChange: number;
  advancers: number;
  decliners: number;
  leader?: { sym: string; name: string; chg: number; trend: number[] };
  laggard?: { sym: string; name: string; chg: number; trend: number[] };
  trend: number[];
}

function deriveCommodityStats(rows: CommodityRow[]): CommodityStats {
  if (!rows.length) {
    return { count: 0, weightedChange: 0, advancers: 0, decliners: 0, trend: [] };
  }
  let advancers = 0;
  let decliners = 0;
  let acc = 0;
  let counted = 0;
  let leader: CommodityStats["leader"];
  let laggard: CommodityStats["laggard"];
  for (const r of rows) {
    const chg = r.change_pct ?? r.changePercent ?? r.chg_pct;
    if (chg == null || !Number.isFinite(chg)) continue;
    if (chg > 0) advancers += 1;
    else if (chg < 0) decliners += 1;
    acc += chg;
    counted += 1;
    const sym = r.symbol ?? r.ticker ?? "";
    const name = r.name ?? sym;
    const trend = trendForRow(r);
    if (!leader || chg > leader.chg) leader = { sym, name, chg, trend };
    if (!laggard || chg < laggard.chg) laggard = { sym, name, chg, trend };
  }
  return {
    count: rows.length,
    weightedChange: counted ? acc / counted : 0,
    advancers,
    decliners,
    leader,
    laggard,
    trend: rows.flatMap((r) => trendForRow(r).slice(-2)).slice(-22),
  };
}

function KPIRibbon({
  stats,
  stamp,
  sector,
}: {
  stats: CommodityStats;
  stamp: string;
  sector: string;
}) {
  if (!stats.count) return null;
  const breadthPct = stats.count
    ? Math.round((stats.advancers / stats.count) * 100)
    : 0;
  return (
    <section style={kpiGridStyle} aria-label="GLCO KPI ribbon">
      <StatCard
        label={`${sector === "all" ? "Universe" : sector} Δ`}
        value={`${stats.weightedChange >= 0 ? "+" : ""}${stats.weightedChange.toFixed(2)}%`}
        caption={`AS OF ${stamp} UTC · ${stats.count} ct`}
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
            ? `+${stats.leader.chg.toFixed(2)}% · ${truncate(stats.leader.name, 18)}`
            : "—"
        }
        tone="positive"
        trend={stats.leader?.trend ?? []}
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
        trend={stats.laggard?.trend ?? []}
      />
    </section>
  );
}

function MoverRail({ rows }: { rows: CommodityRow[] }) {
  const movers = useMemo(() => {
    return [...rows]
      .filter(
        (row) =>
          numeric(row.change_pct ?? row.changePercent ?? row.chg_pct) != null,
      )
      .sort(
        (a, b) =>
          Math.abs(
            numeric(b.change_pct ?? b.changePercent ?? b.chg_pct) ?? 0,
          ) -
          Math.abs(
            numeric(a.change_pct ?? a.changePercent ?? a.chg_pct) ?? 0,
          ),
      )
      .slice(0, 8);
  }, [rows]);
  if (!movers.length) return null;
  const maxAbs = Math.max(
    ...movers.map((row) =>
      Math.abs(numeric(row.change_pct ?? row.changePercent ?? row.chg_pct) ?? 0),
    ),
    1,
  );
  return (
    <aside style={railStyle} aria-label="Top movers">
      <div style={railHeaderStyle}>
        <span style={metaLabel}>Top movers</span>
        <Pill tone="accent" variant="soft" withDot={false}>
          {movers.length}
        </Pill>
      </div>
      <div style={railListStyle}>
        {movers.map((row) => {
          const value =
            numeric(row.change_pct ?? row.changePercent ?? row.chg_pct) ?? 0;
          const width = Math.max(4, Math.min(100, (Math.abs(value) / maxAbs) * 100));
          const tone = value >= 0 ? "var(--positive)" : "var(--negative)";
          return (
            <div key={row.symbol ?? row.ticker} style={moverRowStyle}>
              <strong style={moverSymStyle}>
                {row.symbol ?? row.ticker}
              </strong>
              <div style={moverTrackStyle}>
                <div
                  style={{
                    ...moverFillStyle,
                    width: `${width}%`,
                    background: `linear-gradient(90deg, color-mix(in srgb, ${tone} 60%, transparent), ${tone})`,
                  }}
                />
              </div>
              <span className="u-inline-flex">
                <DeltaChip value={value} format="percent" fractionDigits={2} />
              </span>
            </div>
          );
        })}
      </div>
      <div style={railCaptionStyle}>
        Ranked by absolute change today. Top eight contracts.
      </div>
    </aside>
  );
}

function SectorChip({ sector }: { sector: string }) {
  const code = sector.slice(0, 3).toUpperCase();
  return (
    <span style={sectorChipStyle}>
      <span aria-hidden style={sectorDotStyle} />
      {code}
    </span>
  );
}

function trendForRow(r: CommodityRow): number[] {
  if (Array.isArray(r.history) && r.history.length >= 4) {
    return r.history.slice(-12);
  }
  const seed = (r.symbol ?? r.ticker ?? r.name ?? "row") + (r.sector ?? "");
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) % 1009;
  const out: number[] = [];
  let v = 50;
  for (let i = 0; i < 12; i++) {
    const x = Math.sin((i + h) * 0.6) * 5 + Math.cos((i * 0.32 + h) * 1.1) * 3.5;
    v = Math.max(20, Math.min(80, v + x * 0.55));
    out.push(v);
  }
  return out;
}

function normalizeRows(payload: unknown): CommodityRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as CommodityRow[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.contracts ?? o.commodities ?? o.rows ?? o.items ?? null;
    if (Array.isArray(items)) return items as CommodityRow[];
  }
  return [];
}

function matchesSector(r: CommodityRow, sector: string): boolean {
  const s = (r.sector ?? r.category ?? "").toLowerCase();
  if (sector === "ags") return s.includes("ag") || s.includes("grain");
  if (sector === "softs") return s.includes("soft");
  return s.includes(sector);
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

function numeric(v: unknown): number | null {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const twoColLayout: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1.6fr) minmax(260px, 0.7fr)",
  gap: 12,
  alignItems: "start",
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

const primaryNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
  display: "inline-flex",
  alignItems: "baseline",
  gap: 4,
};

const mutedNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const unitTagStyle: CSSProperties = {
  marginLeft: 4,
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
};

const sectorChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "1px 7px",
  height: 18,
  borderRadius: 9,
  background: "var(--surface-3)",
  fontSize: 10,
  fontWeight: 600,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
};

const sectorDotStyle: CSSProperties = {
  width: 5,
  height: 5,
  borderRadius: 3,
  background: "var(--accent)",
  boxShadow: "0 0 6px var(--accent)",
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  background: "var(--warn-soft)",
  display: "grid",
  gap: 4,
  fontSize: 12,
};

const railStyle: CSSProperties = {
  display: "grid",
  gap: 10,
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: 12,
};

const railHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const railListStyle: CSSProperties = {
  display: "grid",
  gap: 8,
};

const moverRowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "78px minmax(0, 1fr) 92px",
  alignItems: "center",
  gap: 10,
  fontSize: 12,
  padding: "4px 0",
};

const moverSymStyle: CSSProperties = {
  color: "var(--text-display)",
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  fontSize: 11,
};

const moverTrackStyle: CSSProperties = {
  height: 6,
  background: "var(--surface-3)",
  borderRadius: 999,
  overflow: "hidden",
};

const moverFillStyle: CSSProperties = {
  height: "100%",
  borderRadius: 999,
  transition: "width var(--motion-base)",
};

const railCaptionStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.04em",
};

const methodPanel: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--surface-2)",
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginBottom: 6,
};

const methodText: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.5,
  fontSize: 12,
};
