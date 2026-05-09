/**
 * ECO — Economic calendar (this week + this month).
 *
 * Surfaces ShowMe's ECO function. Surprise vs forecast highlight + impact
 * pill.
 */
import { useMemo } from "react";
import {
  ChangeText,
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
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
  { value: "GB", label: "UK" },
  { value: "TR", label: "TR" },
] as const;
const COUNTRY_IDS = COUNTRIES.map((item) => item.value);
const IMPORTANCE = [
  { value: "all", label: "All" },
  { value: "high", label: "High" },
  { value: "medium", label: "Med" },
] as const;
const IMPORTANCE_IDS = IMPORTANCE.map((item) => item.value);

const COLS: DataGridColumn<EcoEvent>[] = [
  {
    key: "date",
    header: "When",
    width: 130,
    render: (e) => formatWhen(e),
  },
  {
    key: "country",
    header: "Region",
    width: 80,
    render: (e) => e.country ?? e.region ?? "—",
  },
  {
    key: "event",
    header: "Event",
    render: (e) => e.event ?? e.name ?? "—",
  },
  {
    key: "importance",
    header: "Imp",
    width: 60,
    render: (e) => importanceBadge(e.importance),
  },
  {
    key: "forecast",
    header: "Fcst",
    numeric: true,
    width: 80,
    render: (e) => fmtNum(e.forecast, e.unit),
  },
  {
    key: "actual",
    header: "Actual",
    numeric: true,
    width: 80,
    render: (e) => fmtNum(e.actual, e.unit),
  },
  {
    key: "surprise",
    header: "Surprise",
    numeric: true,
    width: 90,
    render: (e) => {
      if (typeof e.surprise === "number") {
        return <ChangeText value={e.surprise} digits={2} />;
      }
      const f = numeric(e.forecast);
      const a = numeric(e.actual);
      if (f != null && a != null) {
        return <ChangeText value={a - f} digits={2} />;
      }
      return "—";
    },
  },
];

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
    params: { days, country, importance: importance === "all" ? undefined : importance, live_calendar: true },
  });

  const events = useMemo(
    () => filterEvents(normalizeEvents(data?.data), days),
    [data, days],
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Economic calendar"
          subtitle={`${events.length} event(s) · ${country} · ${range}`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="COUNTRY"
                value={country}
                options={COUNTRIES}
                onChange={setCountry}
              />
              <SegmentedControl
                label="IMPORTANCE"
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
              action={<button onClick={refetch} className="btn">Retry</button>}
            />
          ) : events.length === 0 ? (
            <Empty
              title="Calendar empty"
              body={`${country} · ${importance} · next ${days} days`}
            />
          ) : (
            <DataGrid
              columns={COLS}
              rows={events}
              rowKey={(e, i) => `${e.date ?? e.ts ?? ""}-${i}`}
              density="compact"
            />
          )}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
          <span>filter · {country}/{importance}</span>
        </PaneFooter>
      </Pane>
    </div>
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

function importanceBadge(value: string | number | undefined): React.ReactNode {
  if (value == null) return "—";
  const text = String(value).toLowerCase();
  const high = text.includes("high") || text === "3" || Number(value) >= 3;
  const med = text.includes("med") || text === "2" || Number(value) === 2;
  const tone = high ? "negative" : med ? "warn" : "muted";
  const label = high ? "high" : med ? "med" : "low";
  return (
    <Pill tone={tone} withDot={false}>
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

function fmtNum(v: unknown, unit?: string): string {
  if (v == null || v === "") return "—";
  const n = numeric(v);
  if (n == null) return String(v);
  const u = unit ?? "";
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}${u}`;
}

function formatWhen(e: EcoEvent): string {
  const raw = e.date ?? e.ts ?? e.time ?? "";
  try {
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return String(raw).slice(0, 16);
    return d.toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return String(raw);
  }
}
