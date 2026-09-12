/**
 * SAT — Satellite & alt-data tile.
 *
 * Bloomberg `MAP<GO>` / alt-data analogue. The backend manifest declares
 * SAT shows real imagery or an explicit unavailable card — it never fakes
 * a tile. Until a SentinelHub / Planet credential is configured the sidecar
 * returns `data_mode='not_configured'` with `rows=[]`. This pane therefore
 * leans on KEYLESS public layers it CAN render honestly:
 *
 *   - Imagery: NASA EOSDIS GIBS WMS true-colour mosaic (no key required),
 *     consumed from the payload's top-level `tile_url` (mirrored in
 *     `true_color_tile.url`) with a hatched "tile unavailable" panel on
 *     image error — never a fabricated fallback tile.
 *   - Conditions: Open-Meteo current + daily values (no key required) from
 *     the payload's `conditions.*` object, surfaced as a location summary
 *     card + a small metric table.
 *
 * Everything is driven from the real envelope (`data.data`). When the
 * provider is in `not_configured` / reference mode that is shown verbatim
 * via an honest source pill + a notice — never disguised as live.
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
import { useUtcStamp } from "@/lib/useUtcStamp";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

/* ----------------------------- payload types ------------------------------ */

/** Real top-level tile mirrored from the producer (`sat.py: true_color_tile`). */
interface SATTrueColorTile {
  label?: string;
  url?: string;
  is_satellite?: boolean;
}

/** Real conditions object emitted by the producer (`sat.py: conditions`). */
interface SATConditions {
  current_temp_c?: number | null;
  current_cloud_pct?: number | null;
  /** Open-Meteo wind_speed_10m — its default unit is km/h (verified empirically). */
  current_wind_ms?: number | null;
  weather_code?: number | string | null;
  daily_cloud_mean_pct?: number | null;
  daily_temp_max_c?: number | null;
  daily_temp_min_c?: number | null;
  daily_precip_mm?: number | null;
  source?: string;
}

interface SATRow {
  metric?: string;
  capture_utc?: string;
  aoi?: string;
  layer?: string;
  cloud_pct?: number;
  tile_url?: string;
  value?: string | number;
  detail?: string;
  source?: string;
}

interface SATLocation {
  key?: string;
  id?: string;
  label?: string;
  name?: string;
}

interface SATPayload {
  status?: string;
  data_mode?: string;
  aoi?: string;
  aoi_label?: string;
  layer?: string;
  bbox_label?: string;
  capture_date?: string;
  tile_url?: string;
  true_color_tile?: SATTrueColorTile;
  conditions?: SATConditions;
  cloud_pct?: number | null;
  reason?: string | null;
  degraded_reason?: string | null;
  rows?: SATRow[];
  locations?: SATLocation[];
  methodology?: string;
  as_of?: string;
}

/* ----------------------------- AOI presets -------------------------------- */
// Mirror the manifest `aoi` options so the control offers a stable choice set
// even before the backend echoes a `locations` list.
const AOIS = [
  { id: "cushing_ok", label: "Cushing OK" },
  { id: "singapore_strait", label: "Singapore" },
  { id: "shanghai_port", label: "Shanghai" },
  { id: "rotterdam_port", label: "Rotterdam" },
  { id: "saudi_ras_tanura", label: "Ras Tanura" },
  { id: "iowa_corn_belt", label: "Iowa Corn" },
] as const;
const AOI_IDS = AOIS.map((a) => a.id);

const REFRESH_MS = 60_000;

/* -------------------------------- helpers --------------------------------- */

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmt(v: unknown, digits = 1): string {
  const n = num(v);
  if (n === null) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function cloudTone(pct: number | null): "positive" | "accent" | "warn" {
  if (pct === null) return "accent";
  if (pct < 33) return "positive";
  if (pct < 66) return "accent";
  return "warn";
}

/** WMO weather code → short English label (Open-Meteo `weather_code`). */
const WMO_LABELS: Record<number, string> = {
  0: "Clear sky",
  1: "Mainly clear",
  2: "Partly cloudy",
  3: "Overcast",
  45: "Fog",
  48: "Rime fog",
  51: "Light drizzle",
  53: "Drizzle",
  55: "Dense drizzle",
  56: "Freezing drizzle",
  57: "Freezing drizzle",
  61: "Light rain",
  63: "Rain",
  65: "Heavy rain",
  66: "Freezing rain",
  67: "Freezing rain",
  71: "Light snow",
  73: "Snow",
  75: "Heavy snow",
  77: "Snow grains",
  80: "Light showers",
  81: "Showers",
  82: "Violent showers",
  85: "Snow showers",
  86: "Heavy snow showers",
  95: "Thunderstorm",
  96: "Thunderstorm, hail",
  99: "Thunderstorm, heavy hail",
};

function wmoLabel(code: number | null): string | null {
  if (code === null) return null;
  return WMO_LABELS[code] ?? `WMO code ${code}`;
}

/* ------------------------------ image tile -------------------------------- */

function ImageTile({
  src,
  tileLabel,
  location,
  captureDate,
  layer,
}: {
  src?: string;
  tileLabel?: string;
  location?: string;
  captureDate?: string;
  layer?: string;
}) {
  const [failed, setFailed] = useState(false);

  // Reset when the upstream URL changes (AOI switch / refresh tick).
  useEffect(() => {
    setFailed(false);
  }, [src]);

  const corner = (pos: CSSProperties): CSSProperties => ({ ...cornerTick, ...pos });
  const layerLabel = layer ? layer.replace(/_/g, " ") : "";
  const dateLabel = captureDate ?? "";

  return (
    <div style={imageFrame}>
      <div style={corner({ top: 5, left: 5, borderTop: "1px solid", borderLeft: "1px solid" })} />
      <div style={corner({ top: 5, right: 5, borderTop: "1px solid", borderRight: "1px solid" })} />
      <div style={corner({ bottom: 5, left: 5, borderBottom: "1px solid", borderLeft: "1px solid" })} />
      <div style={corner({ bottom: 5, right: 5, borderBottom: "1px solid", borderRight: "1px solid" })} />

      {src && !failed ? (
        <img
          src={src}
          alt={`Satellite imagery — ${location ?? "AOI"}`}
          style={imageEl}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <div style={imageFallback}>
          <span style={fallbackGlyph}>◛ ◛ ◛</span>
          <span>Imagery tile unavailable</span>
          <span className="u-text-mute">
            {tileLabel ?? "NASA EOSDIS GIBS"}
          </span>
        </div>
      )}

      <div style={imageOverlay}>
        <span style={imageTitle}>{location ?? "—"}</span>
        <span className="u-text-secondary">
          {dateLabel}
          {layerLabel ? ` · ${layerLabel}` : ""}
        </span>
      </div>
    </div>
  );
}

/* --------------------------------- pane ----------------------------------- */

export function SATPane({ code, symbol }: FunctionPaneProps) {
  // Persist as a plain string: backend-echoed location keys are not guaranteed
  // to be one of the static AOI presets, so the stored value must survive a
  // non-preset id without being rejected on the next cold start.
  const [aoi, setAoi] = usePersistentOption<string>(
    "showme.sat-aoi",
    AOI_IDS,
    "cushing_ok",
  );
  // Bundle D / PERF-04. Visibility-aware poll (weather updates slowly).
  const tick = useVisibilityTick(REFRESH_MS);

  // UA-HIGH-16 pattern: `tick` must NOT sit inside `params` — useFunction keys
  // its cache on the serialized params, so a tick in params clears the payload
  // and flashes the skeleton every poll. Refetch from an effect instead.
  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { aoi, layer: "true_color" },
  });
  useEffect(() => {
    if (tick === 0) return; // initial mount handled by useFunction's own load
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  const payload = useMemo<SATPayload>(
    () => (isRecord(data?.data) ? (data?.data as SATPayload) : {}),
    [data?.data],
  );

  const conditions = payload.conditions ?? {};
  const dataMode = payload.data_mode ?? "";
  const isLive = dataMode.toLowerCase() === "live";
  const isNotConfigured = dataMode.toLowerCase() === "not_configured";
  const degraded = isNotConfigured || payload.status === "partial";
  const degradeReason = payload.degraded_reason ?? payload.reason ?? null;
  const warningsList = Array.isArray(data?.warnings) ? data?.warnings : [];

  const rows = useMemo<SATRow[]>(
    () => (Array.isArray(payload.rows) ? payload.rows : []),
    [payload.rows],
  );

  // Prefer backend-provided locations; fall back to the manifest AOI presets.
  const locationChoices = useMemo(() => {
    const fromPayload = Array.isArray(payload.locations) ? payload.locations : [];
    if (fromPayload.length) {
      return fromPayload.map((l) => ({
        id: String(l.key ?? l.id ?? ""),
        label: l.label ?? l.name ?? l.key ?? l.id ?? "—",
      }));
    }
    return AOIS.map((a) => ({ id: a.id as string, label: a.label }));
  }, [payload.locations]);

  // Clamp the active selection to a currently-available choice. When the
  // backend repopulates `locations` with ids that don't match the stored aoi,
  // fall back to the first available location so the Tabs always have an active
  // tab and downstream params/labels stay in sync.
  const choiceIds = useMemo(
    () => locationChoices.map((l) => l.id),
    [locationChoices],
  );
  const effectiveAoi =
    choiceIds.includes(aoi) ? aoi : (choiceIds[0] ?? aoi);

  // Persist the clamp so a stale stored key is healed (and not re-read on the
  // next cold start). Only writes when the stored value is actually orphaned.
  useEffect(() => {
    if (choiceIds.length && !choiceIds.includes(aoi)) {
      setAoi(choiceIds[0]);
    }
  }, [choiceIds, aoi, setAoi]);

  const locationName = payload.aoi_label ?? payload.aoi ?? effectiveAoi;
  const captureDateLabel = payload.capture_date ?? payload.as_of;
  // Conditions: every rendered value maps to a real `conditions.*` key.
  const tempC = num(conditions.current_temp_c);
  const tempMax = num(conditions.daily_temp_max_c);
  const tempMin = num(conditions.daily_temp_min_c);
  const precipMm = num(conditions.daily_precip_mm);
  // Open-Meteo `wind_speed_10m` default unit is km/h (verified against the
  // live provider: default_value / ms_value = 3.597); the backend field name
  // `current_wind_ms` is a misnomer and must not drive the unit label.
  const windKmh = num(conditions.current_wind_ms);
  const cloudDay = num(payload.cloud_pct ?? conditions.daily_cloud_mean_pct);
  const cloudNow = num(conditions.current_cloud_pct);
  const conditionLabel = wmoLabel(num(conditions.weather_code));
  const hasConditions = Object.keys(conditions).length > 0;
  const utcStamp = useUtcStamp(tick);

  const cols = useMemo<DataGridColumn<SATRow>[]>(
    () => [
      {
        key: "metric",
        header: "Metric",
        width: 168,
        render: (r) => (
          <span style={metricCell}>{r.metric ?? r.aoi ?? "—"}</span>
        ),
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 140,
        render: (r) => {
          const v =
            r.value ??
            (r.cloud_pct != null ? `${r.cloud_pct.toFixed(1)}%` : undefined) ??
            r.capture_utc ??
            r.layer;
          return <span style={valueCell}>{v ?? "—"}</span>;
        },
      },
      {
        key: "detail",
        header: "Detail",
        render: (r) => (
          <span className="u-text-secondary">
            {r.detail ?? r.source ?? r.layer ?? "—"}
          </span>
        ),
      },
    ],
    [],
  );

  const hasPayload = Boolean(data?.data) && Object.keys(payload).length > 0;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Satellite & alt-data"
          subtitle={`${locationName} · poll ${REFRESH_MS / 1000}s · ${dataMode || "—"}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill
                tone={isLive ? "positive" : degraded ? "warn" : "muted"}
                variant="soft"
              >
                {isLive
                  ? "live"
                  : isNotConfigured
                    ? "not configured"
                    : dataMode || "reference"}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={locationChoices.map((l) => ({ id: l.id, label: l.label }))}
            active={effectiveAoi}
            onChange={(id) => setAoi(id)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <div className="u-grid-gap-14">
              <Skeleton height={210} />
              <Skeleton height={120} />
              <Skeleton height={140} />
            </div>
          ) : state === "error" ? (
            <Empty
              title="Tile unavailable"
              body={error?.message ?? "Failed to load satellite & weather data."}
              icon="!"
            />
          ) : !hasPayload ? (
            <Empty
              title="No observation"
              body={`No SAT data returned for ${locationName}.`}
            />
          ) : (
            <div className="u-grid-gap-14">
              {isNotConfigured ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">Imagery provider not configured</strong>
                  <span className="u-text-secondary">
                    SentinelHub / Planet credential is absent, so the sidecar
                    returns <code>data_mode=not_configured</code>. The tile below
                    is a keyless NASA GIBS true-colour mosaic and the conditions
                    card is keyless Open-Meteo — both labelled as reference, never
                    presented as a live commercial feed.
                  </span>
                </div>
              ) : null}
              {warningsList.length ? (
                <div style={warningBox}>
                  <strong className="u-text-warn">Provider warnings</strong>
                  <ul style={warningList}>
                    {warningsList.slice(0, 3).map((w, i) => (
                      <li key={i} className="u-text-secondary">
                        {String(w)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <div style={topRow}>
                <ImageTile
                  src={payload.tile_url ?? payload.true_color_tile?.url}
                  tileLabel={payload.true_color_tile?.label}
                  location={locationName}
                  captureDate={captureDateLabel}
                  layer={payload.layer}
                />

                <section style={summaryCard} aria-label="Location weather">
                  <div style={summaryHead}>
                    <div style={summaryLoc}>
                      <span style={locNameStyle}>{locationName}</span>
                      <span style={locBlurbStyle}>
                        {payload.bbox_label ?? "alt-data observation point"}
                      </span>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={bigTemp}>
                        {fmt(tempC)}
                        {tempC !== null ? <span style={tempUnit}>°C</span> : null}
                      </div>
                      {tempMax !== null && tempMin !== null ? (
                        <div style={metaText}>
                          H {fmt(tempMax)}° · L {fmt(tempMin)}°
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div style={condLine}>
                    {conditionLabel ? (
                      <Pill tone={cloudTone(cloudDay)} variant="soft" withDot={false}>
                        {conditionLabel}
                      </Pill>
                    ) : null}
                    {cloudDay !== null ? (
                      <span style={metaText}>{fmt(cloudDay, 0)}% cloud</span>
                    ) : null}
                    {!hasConditions ? (
                      <span style={metaText}>conditions unavailable</span>
                    ) : null}
                  </div>

                  {hasConditions ? (
                    <div style={cardGrid}>
                      <StatCard
                        label="Temp max"
                        value={tempMax !== null ? `${fmt(tempMax)} °C` : "—"}
                        caption={captureDateLabel ? `for ${captureDateLabel}` : undefined}
                        tone="neutral"
                      />
                      <StatCard
                        label="Temp min"
                        value={tempMin !== null ? `${fmt(tempMin)} °C` : "—"}
                        caption={captureDateLabel ? `for ${captureDateLabel}` : undefined}
                        tone="neutral"
                      />
                      <StatCard
                        label="Precip (day)"
                        value={precipMm !== null ? `${fmt(precipMm)} mm` : "—"}
                        caption={captureDateLabel ? `for ${captureDateLabel}` : undefined}
                        tone="neutral"
                      />
                      <StatCard
                        label="Wind (now)"
                        value={windKmh !== null ? `${fmt(windKmh)} km/h` : "—"}
                        caption={conditions.source ?? "open_meteo"}
                        tone="neutral"
                      />
                    </div>
                  ) : null}

                  <div style={metaRow}>
                    {cloudNow !== null ? (
                      <span style={metaText}>now {fmt(cloudNow, 0)}% cloud</span>
                    ) : null}
                  </div>
                </section>
              </div>

              {rows.length ? (
                <DataGrid
                  columns={cols}
                  rows={rows}
                  rowKey={(r, i) => `${r.metric ?? r.aoi ?? "row"}-${i}`}
                  density="compact"
                />
              ) : (
                <Empty
                  title="No conditions table"
                  body="The provider returned no per-metric rows for this AOI."
                />
              )}

              {degraded && degradeReason ? (
                <div style={degradeLine}>⚠ {degradeReason}</div>
              ) : null}

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
          <StatusSection
            label="provider"
            value={data?.sources?.join(", ") || "NASA GIBS · Open-Meteo"}
          />
          <StatusDivider />
          <StatusSection label="mode" value={dataMode || "—"} tone={isLive ? "positive" : "accent"} />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="as of" value={payload.as_of ?? "—"} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* -------------------------------- styles ---------------------------------- */

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const topRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(220px, 1.05fr) minmax(240px, 1fr)",
  gap: 12,
  alignItems: "stretch",
};

const imageFrame: CSSProperties = {
  position: "relative",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  overflow: "hidden",
  minHeight: 210,
  background:
    "linear-gradient(180deg, color-mix(in srgb, var(--accent) 8%, transparent), var(--surface-2))",
  display: "flex",
  flexDirection: "column",
};

const imageEl: CSSProperties = {
  width: "100%",
  height: "100%",
  minHeight: 210,
  objectFit: "cover",
  display: "block",
  filter: "saturate(1.05) contrast(1.02)",
};

const imageOverlay: CSSProperties = {
  position: "absolute",
  left: 0,
  right: 0,
  bottom: 0,
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-end",
  gap: 8,
  padding: "8px 10px",
  background:
    "linear-gradient(0deg, color-mix(in srgb, var(--surface-1, #000) 80%, transparent), transparent)",
  fontSize: 10.5,
  letterSpacing: "0.04em",
  fontFamily: "JetBrains Mono, monospace",
};

const imageTitle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  fontWeight: 700,
  color: "var(--text-display)",
  letterSpacing: "0.02em",
};

const imageFallback: CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: 6,
  padding: 16,
  textAlign: "center",
  color: "var(--text-mute)",
  fontSize: "var(--font-size-sm)",
  minHeight: 210,
  background:
    "repeating-linear-gradient(45deg, color-mix(in srgb, var(--grid-color) 22%, transparent) 0 1px, transparent 1px 9px)",
};

const fallbackGlyph: CSSProperties = {
  fontSize: "var(--font-size-3xl)",
  opacity: 0.55,
  letterSpacing: "0.2em",
};

const cornerTick: CSSProperties = {
  position: "absolute",
  width: 12,
  height: 12,
  borderColor: "var(--accent)",
  opacity: 0.7,
  pointerEvents: "none",
  zIndex: 1,
};

const summaryCard: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: 12,
  minHeight: 0,
};

const summaryHead: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 8,
};

const summaryLoc: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  minWidth: 0,
};

const locNameStyle: CSSProperties = {
  fontSize: "var(--font-size-xl)",
  fontWeight: 700,
  color: "var(--text-display)",
  letterSpacing: "0.01em",
};

const locBlurbStyle: CSSProperties = {
  fontSize: 10.5,
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  fontFamily: "JetBrains Mono, monospace",
};

const bigTemp: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 30,
  fontWeight: 700,
  lineHeight: 1,
  color: "var(--text-display)",
};

const tempUnit: CSSProperties = {
  fontSize: 14,
  color: "var(--text-mute)",
  marginLeft: 1,
};

const condLine: CSSProperties = {
  display: "flex",
  alignItems: "center",
  flexWrap: "wrap",
  gap: 8,
  fontSize: "var(--font-size-md)",
  color: "var(--text-secondary)",
};

const cardGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
  gap: 8,
};

const metaRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 10,
  alignItems: "center",
  marginTop: "auto",
};

const metaText: CSSProperties = {
  fontSize: 10.5,
  color: "var(--text-mute)",
  fontVariantNumeric: "tabular-nums",
  fontFamily: "JetBrains Mono, monospace",
};

const metricCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-display)",
  fontWeight: 600,
};

const valueCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
  fontSize: "var(--font-size-md)",
};

const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
};

const warningList: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const degradeLine: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--negative)",
  letterSpacing: "0.02em",
};

const methodologyBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  display: "grid",
  gap: 6,
  fontSize: "var(--font-size-md)",
};

export default SATPane;
