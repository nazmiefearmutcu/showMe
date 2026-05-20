/**
 * ECO — Economic calendar (this week + this month).
 *
 * Surfaces ShowMe's ECO function. Surprise vs forecast highlight + impact
 * pill, KPI ribbon for high-impact prints, calendar-shaped right rail.
 */
import { useMemo, type CSSProperties, type ReactNode } from "react";
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
  StatCard,
  StatusDivider,
  StatusSection,
  Tabs,
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

interface EcoEvent {
  date?: string;
  ts?: string;
  time?: string;
  country?: string;
  region?: string;
  event?: string;
  name?: string;
  importance?: string | number;
  forecast?: number | string;
  actual?: number | string;
  previous?: number | string;
  unit?: string;
  surprise?: number;
}

const RANGES = [
  { id: "week", label: "This week", days: 7 },
  { id: "month", label: "This month", days: 30 },
] as const;
type RangeId = (typeof RANGES)[number]["id"];
const RANGE_IDS = RANGES.map((r) => r.id);
const COUNTRIES = [
  { value: "US", label: "US" },
  { value: "EU", label: "EU" },
  { value: "UK", label: "UK" },
  { value: "TR", label: "TR" },
] as const;
const COUNTRY_IDS = COUNTRIES.map((item) => item.value);
const IMPORTANCE = [
  { value: "all", label: "All" },
  { value: "high", label: "High" },
  { value: "medium", label: "Med" },
] as const;
const IMPORTANCE_IDS = IMPORTANCE.map((item) => item.value);

export function ECOPane({ code }: FunctionPaneProps) {
  const [range, setRange] = usePersistentOption<RangeId>(
    "showme.eco-range",
    RANGE_IDS,
    "week",
  );
  const [country, setCountry] = usePersistentOption(
    "showme.eco-country",
    COUNTRY_IDS,
    "US",
  );
  const [importance, setImportance] = usePersistentOption(
    "showme.eco-importance",
    IMPORTANCE_IDS,
    "all",
  );
  const days = useMemo(() => RANGES.find((r) => r.id === range)!.days, [range]);
  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: {
      days,
      country,
      importance: importance === "all" ? undefined : importance,
      live_calendar: true,
    },
  });

  const events = useMemo(
    () => filterEvents(normalizeEvents(data?.data), days),
    [data, days],
  );
  const stats = useMemo(() => deriveEcoStats(events), [events]);
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [data]);
  const isLive = state === "ok";

  const COLS: DataGridColumn<EcoEvent>[] = useMemo(
    () => [
      {
        key: "date",
        header: "When",
        width: 142,
        render: (e) => <WhenCell event={e} />,
      },
      {
        key: "country",
        header: "Region",
        width: 88,
        render: (e) => <CountryChip code={e.country ?? e.region ?? ""} />,
      },
      {
        key: "event",
        header: "Event",
        render: (e) => (
          <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>
            {e.event ?? e.name ?? "—"}
          </span>
        ),
      },
      {
        key: "importance",
        header: "Imp",
        width: 64,
        render: (e) => importanceBadge(e.importance),
      },
      {
        key: "forecast",
        header: "Fcst",
        numeric: true,
        width: 84,
        render: (e) => (
          <span style={mutedNumStyle}>{fmtNum(e.forecast, e.unit)}</span>
        ),
      },
      {
        key: "actual",
        header: "Actual",
        numeric: true,
        width: 88,
        render: (e) => (
          <span style={primaryNumStyle}>{fmtNum(e.actual, e.unit)}</span>
        ),
      },
      {
        key: "previous",
        header: "Prev",
        numeric: true,
        width: 80,
        render: (e) => (
          <span style={mutedNumStyle}>{fmtNum(e.previous, e.unit)}</span>
        ),
      },
      {
        key: "surprise",
        header: "Surprise",
        numeric: true,
        width: 96,
        render: (e) => {
          const surprise = computeSurprise(e);
          if (surprise == null) return "—";
          return <DeltaChip value={surprise} format="raw" fractionDigits={2} />;
        },
      },
    ],
    [],
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Economic calendar"
          subtitle={`${events.length} prints · ${country} · next ${days} days`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {events.length} ev
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : state}
              </Pill>
              <SegmentedControl
                label="COUNTRY"
                value={country}
                options={COUNTRIES}
                onChange={setCountry}
              />
              <SegmentedControl
                label="IMP"
                value={importance}
                options={IMPORTANCE}
                onChange={setImportance}
              />
              <Tabs
                variant="segmented"
                items={RANGES.map((r) => ({ id: r.id, label: r.label }))}
                active={range}
                onChange={(id) => setRange(id as RangeId)}
              />
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh calendar"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
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
          ) : events.length === 0 ? (
            <Empty
              title="Calendar empty"
              body={`${country} · ${importance} · next ${days} days`}
            />
          ) : (
            <div className="u-grid-gap-14">
              <KPIRibbon stats={stats} stamp={utcStamp} />
              <div style={twoColLayout}>
                <DataGrid
                  columns={COLS}
                  rows={events}
                  rowKey={(e, i) => `${e.date ?? e.ts ?? ""}-${i}`}
                  density="compact"
                />
                <NextPrintsRail events={events} />
              </div>
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "showMe engine"}
          />
          <StatusDivider />
          <StatusSection label="filter" value={`${country}/${importance}`} />
          <StatusDivider />
          <StatusSection label="rows" value={events.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="range" value={range} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface EcoStats {
  total: number;
  high: number;
  medium: number;
  countries: number;
  surpriseAvg: number;
  surpriseMax: { abs: number; signed: number; event: string } | null;
  trendImpact: number[];
}

function deriveEcoStats(events: EcoEvent[]): EcoStats {
  if (!events.length) {
    return {
      total: 0,
      high: 0,
      medium: 0,
      countries: 0,
      surpriseAvg: 0,
      surpriseMax: null,
      trendImpact: [],
    };
  }
  let high = 0;
  let medium = 0;
  let surpAcc = 0;
  let surpN = 0;
  let surpriseMax: EcoStats["surpriseMax"] = null;
  const cset = new Set<string>();
  const trend: number[] = [];
  for (const e of events) {
    const text = String(e.importance ?? "").toLowerCase();
    if (text.includes("high") || text === "3" || Number(e.importance) >= 3) high += 1;
    else if (text.includes("med") || text === "2" || Number(e.importance) === 2) medium += 1;
    cset.add((e.country ?? e.region ?? "").toUpperCase());
    const surprise = computeSurprise(e);
    if (surprise != null && Number.isFinite(surprise)) {
      surpAcc += surprise;
      surpN += 1;
      const abs = Math.abs(surprise);
      if (!surpriseMax || abs > surpriseMax.abs) {
        surpriseMax = {
          abs,
          signed: surprise,
          event: e.event ?? e.name ?? "",
        };
      }
      trend.push(surprise);
    }
  }
  return {
    total: events.length,
    high,
    medium,
    countries: cset.size,
    surpriseAvg: surpN ? surpAcc / surpN : 0,
    surpriseMax,
    trendImpact: trend.slice(-22),
  };
}

function KPIRibbon({ stats, stamp }: { stats: EcoStats; stamp: string }) {
  return (
    <section style={kpiGridStyle} aria-label="ECO KPI ribbon">
      <StatCard
        label="Prints"
        value={String(stats.total)}
        caption={`AS OF ${stamp} UTC · ${stats.countries} ccy`}
        tone="neutral"
        trend={[]}
      />
      <StatCard
        label="High impact"
        value={String(stats.high)}
        caption={`${stats.medium} med · ${stats.total - stats.high - stats.medium} low`}
        tone={stats.high > 0 ? "negative" : "neutral"}
        trend={[]}
      />
      <StatCard
        label="Avg surprise"
        value={`${stats.surpriseAvg >= 0 ? "+" : ""}${stats.surpriseAvg.toFixed(2)}`}
        caption="VS CONSENSUS"
        tone={stats.surpriseAvg >= 0 ? "positive" : "negative"}
        trend={stats.trendImpact}
      />
      <StatCard
        label="Largest surprise"
        value={
          stats.surpriseMax
            ? `${stats.surpriseMax.signed >= 0 ? "+" : ""}${stats.surpriseMax.signed.toFixed(2)}`
            : "—"
        }
        caption={
          stats.surpriseMax ? truncate(stats.surpriseMax.event, 22) : "—"
        }
        tone={
          stats.surpriseMax
            ? stats.surpriseMax.signed >= 0
              ? "positive"
              : "negative"
            : "neutral"
        }
        trend={stats.trendImpact}
      />
    </section>
  );
}

function NextPrintsRail({ events }: { events: EcoEvent[] }) {
  const upcoming = useMemo(() => {
    const now = Date.now();
    return events
      .map((e) => ({ e, t: parseTime(e) }))
      .filter((x) => x.t != null && (x.t as number) >= now)
      .sort((a, b) => (a.t as number) - (b.t as number))
      .slice(0, 6);
  }, [events]);
  return (
    <aside style={railStyle} aria-label="Upcoming prints">
      <div style={railHeaderStyle}>
        <span style={sectionTitleStyle}>Next prints</span>
        <Pill tone="accent" variant="soft" withDot={false}>
          {upcoming.length}
        </Pill>
      </div>
      <div style={railListStyle}>
        {upcoming.length === 0 ? (
          <span className="u-text-mute u-text-11">
            No upcoming prints in window.
          </span>
        ) : (
          upcoming.map(({ e }, i) => {
            const country = e.country ?? e.region ?? "—";
            const surprise = computeSurprise(e);
            return (
              <div key={`${e.event ?? e.name}-${i}`} style={railRowStyle}>
                <div style={railCountdownStyle}>
                  <CountryChip code={country} />
                  <span style={railTimeStyle}>{shortWhen(e)}</span>
                </div>
                <div style={railEventStyle}>
                  {truncate(e.event ?? e.name ?? "—", 36)}
                </div>
                <div style={railMetaStyle}>
                  {importanceBadge(e.importance)}
                  {surprise != null ? (
                    <DeltaChip value={surprise} format="raw" fractionDigits={2} />
                  ) : (
                    <span className="u-text-mute u-text-10">
                      pending
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
      <div style={railCaptionStyle}>
        Sorted by next release. Surprise = actual minus forecast at print time.
      </div>
    </aside>
  );
}

function WhenCell({ event }: { event: EcoEvent }): ReactNode {
  const t = parseTime(event);
  if (t == null) return <span className="u-text-mute">{String(event.date ?? event.ts ?? event.time ?? "—").slice(0, 16)}</span>;
  const d = new Date(t);
  const date = d.toISOString().slice(5, 10).replace("-", "/");
  const time = d.toISOString().slice(11, 16);
  return (
    <span style={whenCellStyle}>
      <span style={whenDateStyle}>{date}</span>
      <span style={whenTimeStyle}>{time}</span>
    </span>
  );
}

function CountryChip({ code }: { code: string }) {
  const c = String(code ?? "").slice(0, 3).toUpperCase() || "—";
  return (
    <span style={countryChipStyle}>
      <span aria-hidden style={countryDotStyle} />
      {c}
    </span>
  );
}

function normalizeEvents(payload: unknown): EcoEvent[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as EcoEvent[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.events ?? o.items ?? null;
    if (Array.isArray(items)) return items as EcoEvent[];
  }
  return [];
}

function filterEvents(events: EcoEvent[], days: number): EcoEvent[] {
  const start = Date.now() - 86_400_000;
  const end = Date.now() + days * 86_400_000;
  return events.filter((event) => {
    const raw = event.date ?? event.ts ?? event.time;
    if (!raw) return true;
    const t = new Date(raw).getTime();
    if (Number.isNaN(t)) return true;
    return t >= start && t <= end;
  });
}

function importanceBadge(value: string | number | undefined): ReactNode {
  if (value == null) return "—";
  const text = String(value).toLowerCase();
  const high = text.includes("high") || text === "3" || Number(value) >= 3;
  const med = text.includes("med") || text === "2" || Number(value) === 2;
  const tone: "negative" | "warn" | "muted" = high ? "negative" : med ? "warn" : "muted";
  const label = high ? "high" : med ? "med" : "low";
  return (
    <Pill tone={tone} variant="soft" withDot={false}>
      {label}
    </Pill>
  );
}

function numeric(v: unknown): number | null {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = Number(v.replace(/[%,]/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function computeSurprise(e: EcoEvent): number | null {
  if (typeof e.surprise === "number" && Number.isFinite(e.surprise)) return e.surprise;
  const f = numeric(e.forecast);
  const a = numeric(e.actual);
  if (f != null && a != null) return a - f;
  return null;
}

function fmtNum(v: unknown, unit?: string): string {
  if (v == null || v === "") return "—";
  const n = numeric(v);
  if (n == null) return String(v);
  const u = unit ?? "";
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}${u}`;
}

function parseTime(e: EcoEvent): number | null {
  const raw = e.date ?? e.ts ?? e.time ?? "";
  const t = new Date(String(raw)).getTime();
  return Number.isNaN(t) ? null : t;
}

function shortWhen(e: EcoEvent): string {
  const t = parseTime(e);
  if (t == null) return "—";
  const d = new Date(t);
  return `${d.toISOString().slice(5, 10).replace("-", "/")} ${d.toISOString().slice(11, 16)}`;
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const twoColLayout: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1.6fr) minmax(280px, 0.7fr)",
  gap: 12,
  alignItems: "start",
};

const railStyle: CSSProperties = {
  display: "grid",
  gap: 10,
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
};

const railHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const sectionTitleStyle: CSSProperties = {
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontSize: 10,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const railListStyle: CSSProperties = {
  display: "grid",
  gap: 8,
};

const railRowStyle: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "8px 10px",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  transition: "transform var(--motion-base), border-color var(--motion-base)",
};

const railCountdownStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const railTimeStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-secondary)",
};

const railEventStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--text-primary)",
};

const railMetaStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  marginTop: 2,
};

const railCaptionStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.04em",
};

const whenCellStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "baseline",
  gap: 6,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
};

const whenDateStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontWeight: 500,
};

const whenTimeStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 11,
};

const countryChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "1px 7px",
  height: 18,
  borderRadius: 9,
  background: "var(--surface-3)",
  fontSize: 10,
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  letterSpacing: "0.06em",
  color: "var(--text-secondary)",
  textTransform: "uppercase",
};

const countryDotStyle: CSSProperties = {
  width: 5,
  height: 5,
  borderRadius: 3,
  background: "var(--accent)",
  boxShadow: "0 0 6px var(--accent)",
};

const mutedNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const primaryNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
  fontWeight: 600,
};
