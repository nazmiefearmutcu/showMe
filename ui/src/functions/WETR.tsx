/**
 * WETR — Weather trends for commodity-relevant regions.
 *
 * Sidecar returns `status: ok` when OpenWeather One Call is configured;
 * otherwise `provider_unavailable` with `source_mode: seasonal_model`
 * and a labelled seasonal-model row set. The pane shows the daily grid
 * (HDD/CDD/risk_flag/commodity_impact), a region tab strip, and a
 * provider-status banner so the user never confuses the seasonal-model
 * stub for live OpenWeather data.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
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
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface WETRRow {
  date?: string;
  day?: string;
  location?: string;
  lat?: number;
  lon?: number;
  temp_c?: number;
  precip_mm?: number;
  hdd?: number;
  cdd?: number;
  risk_flag?: string;
  commodity_impact?: string;
  source_mode?: string;
}

interface WETRPayload {
  status?: string;
  reason?: string;
  location?: string;
  lat?: number;
  lon?: number;
  commodity_context?: string;
  source_mode?: string;
  rows?: WETRRow[];
  risk_flags?: string[];
  methodology?: string;
  field_dictionary?: Record<string, string>;
  next_actions?: string[];
}

const LOCATIONS = [
  { id: "US_NORTHEAST", label: "US NE" },
  { id: "US_GULF", label: "US Gulf" },
  { id: "EU_NW", label: "EU NW" },
  { id: "ASIA_EAST", label: "Asia E" },
] as const;
type LocationId = (typeof LOCATIONS)[number]["id"];
const LOCATION_IDS = LOCATIONS.map((l) => l.id);

const REFRESH_MS = 60_000;

export function WETRPane({ code }: FunctionPaneProps) {
  const [location, setLocation] = usePersistentOption<LocationId>(
    "showme.wetr-location",
    LOCATION_IDS,
    "US_NORTHEAST",
  );
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { location, days: 10, tick },
  });

  const payload = useMemo<WETRPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as WETRPayload)
        : {},
    [data?.data],
  );

  const rows = useMemo<WETRRow[]>(
    () => (Array.isArray(payload.rows) ? payload.rows : []),
    [payload.rows],
  );

  const sourceMode = payload.source_mode ?? rows[0]?.source_mode ?? "—";
  const isLive = payload.status === "ok" && sourceMode.includes("openweather");
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);

  const stats = useMemo(() => deriveWeatherStats(rows), [rows]);

  const cols = useMemo<DataGridColumn<WETRRow>[]>(
    () => [
      {
        key: "date",
        header: "Date",
        width: 110,
        render: (r) => (
          <span style={dateCell}>
            {r.date ?? "—"}
            {r.day ? (
              <span className="u-text-mute" style={{ fontSize: "var(--font-size-xs)" }}>
                {r.day}
              </span>
            ) : null}
          </span>
        ),
      },
      {
        key: "temp",
        header: "Temp °C",
        numeric: true,
        width: 100,
        render: (r) => {
          if (r.temp_c == null) return "—";
          const t = r.temp_c;
          const tone =
            t >= 28 ? "var(--negative)" : t <= 5 ? "var(--accent)" : "var(--text-primary)";
          return (
            <span style={{ ...numCell, color: tone, fontWeight: 700 }}>
              {t.toFixed(1)}°
            </span>
          );
        },
      },
      {
        key: "precip",
        header: "Precip mm",
        numeric: true,
        width: 110,
        render: (r) =>
          r.precip_mm == null ? "—" : (
            <span style={numCell}>{r.precip_mm.toFixed(1)}</span>
          ),
      },
      {
        key: "hdd",
        header: "HDD",
        numeric: true,
        width: 80,
        render: (r) =>
          r.hdd == null ? "—" : <span style={numCell}>{r.hdd.toFixed(1)}</span>,
      },
      {
        key: "cdd",
        header: "CDD",
        numeric: true,
        width: 80,
        render: (r) =>
          r.cdd == null ? "—" : <span style={numCell}>{r.cdd.toFixed(1)}</span>,
      },
      {
        key: "risk",
        header: "Risk",
        width: 110,
        render: (r) =>
          r.risk_flag ? (
            <Pill tone={riskTone(r.risk_flag)} variant="soft" withDot={false}>
              {r.risk_flag}
            </Pill>
          ) : (
            <Pill tone="muted" variant="soft" withDot={false}>normal</Pill>
          ),
      },
      {
        key: "impact",
        header: "Commodity impact",
        render: (r) => (
          <span className="u-text-secondary" style={{ fontSize: "var(--font-size-xs)" }}>
            {r.commodity_impact ?? "—"}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Weather · ${payload.location ?? location}`}
          subtitle={`${rows.length} days · ${payload.commodity_context ?? "—"} · ${sourceMode}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>{rows.length} d</Pill>
              <Pill tone="accent" variant="soft" withDot={false}>{utcStamp} UTC</Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live forecast" : "seasonal model"}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={LOCATIONS.map((l) => ({ id: l.id, label: l.label }))}
            active={location}
            onChange={(id) => setLocation(id as LocationId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : rows.length === 0 ? (
            <Empty title="No forecast" body={payload.reason ?? "No WETR rows."} />
          ) : (
            <div className="u-grid-gap-14">
              {!isLive ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">Seasonal model rows</strong>
                  <span className="u-text-secondary">
                    {payload.reason ??
                      "OpenWeather is not configured — rows are a labelled seasonal weather model, not live forecast data."}
                  </span>
                  {payload.next_actions?.length ? (
                    <ul style={hintList}>
                      {payload.next_actions.slice(0, 2).map((a, i) => (
                        <li key={i} className="u-text-mute">{a}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}
              <section style={kpiGrid} aria-label="WETR KPI ribbon">
                <StatCard
                  label="Avg temp"
                  value={`${stats.avgTemp.toFixed(1)}°C`}
                  caption={`${stats.minTemp.toFixed(1)}° → ${stats.maxTemp.toFixed(1)}°`}
                  tone={stats.avgTemp >= 25 ? "negative" : "neutral"}
                />
                <StatCard
                  label="Cumulative HDD"
                  value={stats.totalHdd.toFixed(1)}
                  caption={`${stats.days} days`}
                  tone="neutral"
                />
                <StatCard
                  label="Cumulative CDD"
                  value={stats.totalCdd.toFixed(1)}
                  caption={`${stats.days} days`}
                  tone="negative"
                />
                <StatCard
                  label="Risk days"
                  value={`${stats.riskDays}/${stats.days}`}
                  caption={(payload.risk_flags ?? []).slice(0, 3).join(", ") || "—"}
                  tone={stats.riskDays >= stats.days / 2 ? "negative" : "positive"}
                />
              </section>
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => `${r.date ?? "row"}-${i}`}
                density="compact"
              />
              {payload.methodology ? (
                <div style={methodologyBox}>
                  <strong className="u-text-secondary">Methodology</strong>
                  <span>{payload.methodology}</span>
                </div>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={data?.sources?.join(", ") || sourceMode} />
          <StatusDivider />
          <StatusSection label="location" value={payload.location ?? location} />
          <StatusDivider />
          <StatusSection label="lat/lon" value={`${payload.lat?.toFixed(2) ?? "—"} / ${payload.lon?.toFixed(2) ?? "—"}`} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection label="commodity" value={payload.commodity_context ?? "—"} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface WeatherStats {
  days: number;
  avgTemp: number;
  minTemp: number;
  maxTemp: number;
  totalHdd: number;
  totalCdd: number;
  riskDays: number;
}

function deriveWeatherStats(rows: WETRRow[]): WeatherStats {
  if (!rows.length) {
    return { days: 0, avgTemp: 0, minTemp: 0, maxTemp: 0, totalHdd: 0, totalCdd: 0, riskDays: 0 };
  }
  let tempAcc = 0;
  let tempCount = 0;
  let minTemp = Infinity;
  let maxTemp = -Infinity;
  let totalHdd = 0;
  let totalCdd = 0;
  let riskDays = 0;
  for (const r of rows) {
    if (typeof r.temp_c === "number" && Number.isFinite(r.temp_c)) {
      tempAcc += r.temp_c;
      tempCount += 1;
      if (r.temp_c < minTemp) minTemp = r.temp_c;
      if (r.temp_c > maxTemp) maxTemp = r.temp_c;
    }
    if (typeof r.hdd === "number") totalHdd += r.hdd;
    if (typeof r.cdd === "number") totalCdd += r.cdd;
    if (r.risk_flag && !/normal/i.test(r.risk_flag)) riskDays += 1;
  }
  return {
    days: rows.length,
    avgTemp: tempCount ? tempAcc / tempCount : 0,
    minTemp: Number.isFinite(minTemp) ? minTemp : 0,
    maxTemp: Number.isFinite(maxTemp) ? maxTemp : 0,
    totalHdd,
    totalCdd,
    riskDays,
  };
}

function riskTone(flag: string): "positive" | "warn" | "negative" | "muted" | "accent" {
  const lower = flag.toLowerCase();
  if (lower.includes("severe") || lower.includes("storm") || lower.includes("freeze") || lower.includes("drought"))
    return "negative";
  if (lower.includes("hot") || lower.includes("cold") || lower.includes("wet"))
    return "warn";
  if (lower.includes("normal") || lower.includes("calm")) return "positive";
  return "accent";
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const dateCell: CSSProperties = {
  display: "grid",
  gap: 2,
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-display)",
  fontWeight: 600,
};

const numCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const hintList: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const methodologyBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  display: "grid",
  gap: 6,
};
