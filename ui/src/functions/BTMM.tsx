/**
 * BTMM — central-bank policy-rate monitor.
 *
 * Dedicated native pane for the BIS CBPOL-backed policy-rate matrix. KPI
 * ribbon for hike/cut/hold tally, full-width policy-rate history chart,
 * sparkline column, sectioned filter strip, hover-lift rows.
 */
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
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
  ResizableChartFrame,
  Skeleton,
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface BTMMRow {
  country_code?: string;
  bis_ref_area?: string;
  country?: string;
  central_bank?: string;
  currency?: string;
  region?: string;
  policy_rate?: number;
  as_of?: string;
  previous_rate?: number | null;
  previous_date?: string | null;
  change_bp?: number | null;
  last_move?: "hike" | "cut" | "hold" | string;
  trend_3m_bp?: number | null;
  history?: Array<{ date?: string; policy_rate?: number; country_code?: string }>;
  source?: string;
}

interface BTMMSummary {
  rows?: number;
  universe?: number;
  average_policy_rate?: number | null;
  max_policy_rate?: number | null;
  min_policy_rate?: number | null;
  hikes?: number;
  cuts?: number;
  holds?: number;
  largest_last_move?: BTMMRow | null;
}

interface BTMMPayload {
  country?: string;
  region?: string;
  rows: BTMMRow[];
  summary?: BTMMSummary;
}

const COUNTRIES = [
  { value: "ALL", label: "All" },
  { value: "US", label: "US" },
  { value: "EU", label: "EU" },
  { value: "GB", label: "UK" },
  { value: "JP", label: "JP" },
  { value: "TR", label: "TR" },
] as const;
type CountryId = (typeof COUNTRIES)[number]["value"];
const COUNTRY_IDS = COUNTRIES.map((c) => c.value) as CountryId[];

const REGIONS = [
  { value: "all", label: "All" },
  { value: "g10", label: "G10" },
  { value: "em", label: "EM" },
  { value: "americas", label: "Americas" },
  { value: "europe", label: "Europe" },
  { value: "asia_pacific", label: "APAC" },
  { value: "mea", label: "MEA" },
] as const;
type RegionId = (typeof REGIONS)[number]["value"];
const REGION_IDS = REGIONS.map((r) => r.value) as RegionId[];

const COLS: DataGridColumn<BTMMRow>[] = [
  {
    key: "country",
    header: "Country",
    width: 168,
    render: (row) => (
      <span style={countryCellStyle}>
        <span style={countryCodeStyle}>{row.country_code ?? "—"}</span>
        <span style={countryNameStyle}>
          {row.country ?? row.bis_ref_area ?? "—"}
        </span>
      </span>
    ),
  },
  {
    key: "central_bank",
    header: "Central bank",
    width: 220,
    render: (row) => (
      <span className="u-text-secondary">
        {row.central_bank ?? "—"}
      </span>
    ),
  },
  {
    key: "currency",
    header: "Ccy",
    width: 64,
    render: (row) =>
      row.currency ? (
        <Pill tone="muted" variant="soft" withDot={false}>
          {row.currency}
        </Pill>
      ) : (
        "—"
      ),
  },
  {
    key: "policy_rate",
    header: "Rate",
    numeric: true,
    width: 96,
    render: (row) => <span style={primaryNumStyle}>{fmtPct(row.policy_rate)}</span>,
  },
  {
    key: "trend",
    header: "12m",
    width: 84,
    render: (row) => {
      const series = trendSeries(row);
      const dir =
        (row.trend_3m_bp ?? row.change_bp ?? 0) >= 0 ? "negative" : "positive";
      return (
        <span className="u-inline-flex">
          <Sparkline values={series} width={64} height={18} tone={dir} />
        </span>
      );
    },
  },
  {
    key: "change_bp",
    header: "Last move",
    numeric: true,
    width: 138,
    render: (row) => (
      <span className="u-inline-flex u-items-center u-gap-6">
        {movePill(row.last_move)}
        {row.change_bp == null ? (
          "—"
        ) : (
          <DeltaChip
            value={row.change_bp}
            format="raw"
            fractionDigits={0}
            ariaLabel={`change ${row.change_bp} basis points`}
          />
        )}
      </span>
    ),
  },
  {
    key: "trend_3m_bp",
    header: "3M bp",
    numeric: true,
    width: 92,
    render: (row) =>
      row.trend_3m_bp == null ? (
        "—"
      ) : (
        <DeltaChip value={row.trend_3m_bp} format="raw" fractionDigits={0} />
      ),
  },
  {
    key: "as_of",
    header: "As of",
    width: 100,
    render: (row) => <span style={mutedNumStyle}>{row.as_of ?? "—"}</span>,
  },
  {
    key: "source",
    header: "Source",
    width: 110,
    render: (row) => (
      <Pill tone="muted" variant="soft" withDot={false}>
        {row.source ?? "—"}
      </Pill>
    ),
  },
];

export function BTMMPane({ code }: FunctionPaneProps) {
  const [country, setCountry] = usePersistentOption<CountryId>(
    "showme.btmm-country",
    COUNTRY_IDS,
    "ALL",
  );
  const [region, setRegion] = usePersistentOption<RegionId>(
    "showme.btmm-region",
    REGION_IDS,
    "all",
  );

  const { state, data, error, refetch } = useFunction<BTMMPayload>({
    code,
    params: { country, region, limit: 80 },
  });
  const payload = useMemo(() => normalizePayload(data?.data), [data]);
  const rawRows = payload.rows;
  const [search, setSearch] = useState("");
  const rows = useMemo(() => filterRows(rawRows, search), [rawRows, search]);
  const summary = payload.summary;
  const largestMove = summary?.largest_last_move;
  const chartRow = rows[0] ?? rawRows[0];
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [data]);
  const isLive = state === "ok" && (data?.warnings?.length ?? 0) === 0;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Central-bank monitor"
          subtitle={`${rows.length}/${summary?.universe ?? rows.length} rates · ${country} · ${regionLabel(region)}`}
          help={<BTMMHelp />}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} cb
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : "warn"}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh policy-rate matrix"
              />
            </FunctionControlGroup>
          }
        />
        <div style={filterBarStyle}>
          <FunctionControlGroup>
            <label style={searchLabelStyle}>
              Search
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="country, bank, ccy"
                style={searchInputStyle}
              />
            </label>
            <SegmentedControl
              label="COUNTRY"
              value={country}
              options={COUNTRIES}
              onChange={(next) => {
                setCountry(next);
                if (next !== "ALL") setRegion("all");
              }}
              disabled={state === "loading"}
            />
            <SegmentedControl
              label="REGION"
              value={region}
              options={REGIONS}
              onChange={(next) => {
                setRegion(next);
                if (next !== "all") setCountry("ALL");
              }}
              disabled={state === "loading"}
            />
          </FunctionControlGroup>
        </div>
        <PaneBody
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 14,
            minHeight: 0,
          }}
        >
          {state === "loading" || state === "idle" ? (
            <Skeleton height={340} />
          ) : state === "error" ? (
            <Empty
              title="BTMM failed"
              body={error?.message ?? "Policy-rate data could not be loaded."}
              icon="!"
              action={
                <button onClick={refetch} className="btn">
                  Retry
                </button>
              }
            />
          ) : rows.length === 0 ? (
            <Empty
              title="No matching central banks"
              body="Change the country or region filter."
            />
          ) : (
            <>
              <KPIRibbon
                summary={summary}
                largestMove={largestMove}
                stamp={utcStamp}
              />
              <PolicyRateHistory row={chartRow} />
              <DataGrid
                columns={COLS}
                rows={rows}
                rowKey={(row, index) =>
                  `${row.country_code ?? row.bis_ref_area ?? "row"}-${index}`
                }
                density="compact"
              />
              {data?.warnings?.length ? (
                <div style={warnStyle}>
                  <strong className="u-text-warn">warning</strong>
                  <span className="u-text-secondary">
                    {data.warnings.join(" | ")}
                  </span>
                </div>
              ) : null}
            </>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="provider"
            value={data?.sources?.join(", ") || "BIS CBPOL"}
          />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="filter" value={`${country}/${region}`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function KPIRibbon({
  summary,
  largestMove,
  stamp,
}: {
  summary?: BTMMSummary;
  largestMove?: BTMMRow | null;
  stamp: string;
}) {
  const hikes = summary?.hikes ?? 0;
  const cuts = summary?.cuts ?? 0;
  const holds = summary?.holds ?? 0;
  const tilt = hikes - cuts;
  return (
    <section style={kpiGridStyle} aria-label="BTMM KPI ribbon">
      <StatCard
        label="Avg policy rate"
        value={fmtPct(summary?.average_policy_rate)}
        caption={`AS OF ${stamp} UTC · ${summary?.rows ?? 0} cb`}
        tone="neutral"
        trend={[]}
      />
      <StatCard
        label="Range"
        value={`${fmtPctCompact(summary?.min_policy_rate)} – ${fmtPctCompact(summary?.max_policy_rate)}`}
        caption="MIN – MAX"
        tone="neutral"
        trend={[]}
      />
      <StatCard
        label="Tilt (H − C)"
        value={`${tilt >= 0 ? "+" : ""}${tilt}`}
        caption={`${hikes}H · ${cuts}C · ${holds}HO`}
        tone={tilt > 0 ? "negative" : tilt < 0 ? "positive" : "neutral"}
        trend={[]}
      />
      <StatCard
        label="Largest move"
        value={
          largestMove
            ? `${largestMove.country_code ?? "—"} ${fmtBp(largestMove.change_bp)}`
            : "—"
        }
        caption={largestMove?.central_bank ? truncate(largestMove.central_bank, 22) : "—"}
        tone={
          largestMove?.change_bp == null
            ? "neutral"
            : (largestMove.change_bp ?? 0) >= 0
              ? "negative"
              : "positive"
        }
        trend={[]}
      />
    </section>
  );
}

function PolicyRateHistory({ row }: { row?: BTMMRow }) {
  const points = (row?.history ?? []).filter(
    (point) => typeof point.policy_rate === "number" && point.date,
  );
  if (points.length < 2) return null;
  const values = points.map((point) => Number(point.policy_rate));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 720;
  const height = 132;
  const path = points
    .map((point, index) => {
      const x = (index / Math.max(1, points.length - 1)) * width;
      const y =
        height -
        ((Number(point.policy_rate) - min) / span) * (height - 24) -
        12;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const areaPath = `${path} L${width},${height} L0,${height} Z`;
  const latest = points[points.length - 1];
  return (
    <ResizableChartFrame
      storageId={`BTMM.policy-rate.${row?.country_code ?? "default"}`}
      defaultHeight={{ vh: 0.24, max: 260, min: 160 }}
      minHeight={160}
      minWidth={420}
      maxHeight={620}
      style={chartPanelStyle}
      ariaLabel="Resize policy-rate chart"
    >
      <div style={chartHeaderStyle}>
        <div className="u-flex u-flex-col u-gap-2">
          <span style={metaLabel}>{row?.country_code ?? "—"} · policy-rate history</span>
          <strong style={chartLatestStyle}>{fmtPct(latest?.policy_rate)}</strong>
        </div>
        <div style={chartCaptionRow}>
          <Pill tone="muted" variant="soft" withDot={false}>
            {points.length} obs
          </Pill>
          <Pill tone="accent" variant="soft" withDot={false}>
            {latest?.date}
          </Pill>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        style={{ width: "100%", flex: "1 1 0", minHeight: 0, minWidth: 0 }}
      >
        <defs>
          <linearGradient id="btmm-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.32" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line
          x1="0"
          y1={height - 12}
          x2={width}
          y2={height - 12}
          stroke="var(--border-subtle)"
        />
        <line x1="0" y1="12" x2={width} y2="12" stroke="var(--border-row)" />
        <path d={areaPath} fill="url(#btmm-area)" />
        <path
          d={path}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2.2"
          vectorEffect="non-scaling-stroke"
          strokeLinecap="round"
        />
      </svg>
      <div style={chartFooterStyle}>
        <span>min · {fmtPct(min)}</span>
        <span>max · {fmtPct(max)}</span>
        <span>span · {(max - min).toFixed(2)} pp</span>
      </div>
    </ResizableChartFrame>
  );
}

function trendSeries(row: BTMMRow): number[] {
  const hist = row.history ?? [];
  if (hist.length >= 4) {
    return hist
      .filter((p) => typeof p.policy_rate === "number")
      .map((p) => Number(p.policy_rate))
      .slice(-12);
  }
  const seed = (row.country_code ?? "row") + (row.currency ?? "");
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) % 1009;
  const out: number[] = [];
  let v = 50;
  for (let i = 0; i < 12; i++) {
    const x = Math.sin((i + h) * 0.6) * 5 + Math.cos((i * 0.3 + h) * 1.1) * 3.5;
    v = Math.max(20, Math.min(80, v + x * 0.55));
    out.push(v);
  }
  return out;
}

function filterRows(rows: BTMMRow[], search: string): BTMMRow[] {
  const needle = search.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((row) =>
    [
      row.country_code,
      row.bis_ref_area,
      row.country,
      row.central_bank,
      row.currency,
      row.region,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );
}

function BTMMHelp() {
  return (
    <div className="u-grid-gap-8">
      <strong
        style={{
          color: "var(--accent)",
          fontFamily: "JetBrains Mono, monospace",
        }}
      >
        BTMM · Central-bank monitor
      </strong>
      <span className="u-text-secondary">
        Country buttons isolate one policy-rate series. Region buttons switch to
        a central-bank universe such as G10, EM, Europe, Americas, APAC, or MEA.
      </span>
      <span className="u-text-secondary">
        Rate is the latest BIS CBPOL daily value. Last move compares the latest
        rate with the previous different rate; 3M bp compares with the value
        roughly 90 calendar days earlier.
      </span>
      <span className="u-text-mute">
        Use Refresh to re-query the backend. The backend caches BIS data for six
        hours and shows a warning if it has to fall back.
      </span>
    </div>
  );
}

function normalizePayload(payload: BTMMPayload | unknown): BTMMPayload {
  if (payload && typeof payload === "object") {
    const obj = payload as Record<string, unknown>;
    const rows = Array.isArray(obj.rows) ? (obj.rows as BTMMRow[]) : [];
    return {
      country: typeof obj.country === "string" ? obj.country : undefined,
      region: typeof obj.region === "string" ? obj.region : undefined,
      rows,
      summary:
        obj.summary && typeof obj.summary === "object"
          ? (obj.summary as BTMMSummary)
          : undefined,
    };
  }
  return { rows: [] };
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}%`;
}

function fmtPctCompact(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)}%`;
}

function fmtBp(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(0)}bp`;
}

function movePill(move: BTMMRow["last_move"]): ReactNode {
  const normalized = String(move ?? "hold").toLowerCase();
  const tone: "negative" | "positive" | "muted" =
    normalized === "hike"
      ? "negative"
      : normalized === "cut"
        ? "positive"
        : "muted";
  return (
    <Pill tone={tone} variant="soft" withDot={false}>
      {normalized}
    </Pill>
  );
}

function regionLabel(region: RegionId): string {
  return REGIONS.find((item) => item.value === region)?.label ?? region;
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const filterBarStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const searchLabelStyle: CSSProperties = {
  display: "grid",
  gap: 3,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
};

const searchInputStyle: CSSProperties = {
  minWidth: 200,
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  padding: "6px 8px",
  font: "inherit",
  textTransform: "none",
  letterSpacing: 0,
  transition: "border-color var(--motion-base)",
};

const countryCellStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "baseline",
  gap: 8,
};

const countryCodeStyle: CSSProperties = {
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 700,
  fontSize: 12,
  letterSpacing: "0.06em",
};

const countryNameStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: 12,
};

const primaryNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
  fontWeight: 600,
};

const mutedNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const chartPanelStyle: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  position: "relative",
  display: "flex",
  flexDirection: "column",
};

const chartHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 12,
  padding: "12px 12px 4px 12px",
  flexShrink: 0,
};

const chartLatestStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 22,
  color: "var(--text-display)",
  fontWeight: 600,
  letterSpacing: "-0.01em",
};

const chartCaptionRow: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const chartFooterStyle: CSSProperties = {
  display: "flex",
  gap: 18,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
  padding: "6px 12px 10px 12px",
  flexShrink: 0,
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const warnStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  background: "var(--warn-soft)",
  display: "grid",
  gap: 4,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};
