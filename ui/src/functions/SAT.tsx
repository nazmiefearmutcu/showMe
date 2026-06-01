/**
 * SAT — Satellite & alt-data tile.
 *
 * Bloomberg `MAP<GO>` / alt-data analogue. The backend manifest declares
 * SAT shows real imagery or an explicit unavailable card — it never fakes
 * a tile. Until a SentinelHub / Planet credential is configured the sidecar
 * returns `data_mode='not_configured'` with `rows=[]`. This pane therefore
 * leans on KEYLESS public layers it CAN render honestly:
 *
 *   - Imagery: NASA EOSDIS GIBS WMTS true-colour mosaic (no key required),
 *     consumed from the payload's `imagery.primary_url` with a graceful
 *     fallback URL and a hatched "tile unavailable" panel on image error.
 *   - Weather: Open-Meteo current conditions (no key required), surfaced as
 *     a location summary card + a small conditions table.
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
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

/* ----------------------------- payload types ------------------------------ */

interface SATImagery {
  primary_url?: string;
  tile_url?: string;
  fallback_url?: string;
  url?: string;
  layer?: string;
  capture_utc?: string;
  date?: string;
  cloud_pct?: number;
  attribution?: string;
  source?: string;
}

interface SATWeather {
  summary?: string;
  conditions?: string;
  code?: number | string | null;
  temperature_c?: number | null;
  apparent_c?: number | null;
  wind_kmh?: number | null;
  wind_dir_deg?: number | null;
  humidity_pct?: number | null;
  cloud_cover_pct?: number | null;
  precip_mm?: number | null;
  pressure_hpa?: number | null;
  observed_at?: string;
}

interface SATCard {
  label?: string;
  value?: number | string | null;
  unit?: string;
  caption?: string;
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
  data_mode?: string;
  source_mode?: string;
  location_key?: string;
  aoi?: string;
  location?: string;
  label?: string;
  blurb?: string;
  lat?: number;
  lon?: number;
  coordinates?: { lat?: number; lon?: number };
  imagery?: SATImagery;
  weather?: SATWeather;
  cards?: SATCard[];
  rows?: SATRow[];
  locations?: SATLocation[];
  degraded?: boolean;
  degraded_reason?: string | null;
  methodology?: string;
  source?: string;
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
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function compass(deg: number | null): string {
  if (deg === null) return "";
  const dirs = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
  ];
  return dirs[Math.round((deg % 360) / 22.5) % 16] ?? "";
}

function cloudTone(pct: number | null): "positive" | "accent" | "warn" {
  if (pct === null) return "accent";
  if (pct < 33) return "positive";
  if (pct < 66) return "accent";
  return "warn";
}

/* ------------------------------ image tile -------------------------------- */

function ImageTile({
  imagery,
  location,
  asOf,
}: {
  imagery?: SATImagery;
  location?: string;
  asOf?: string;
}) {
  const primary =
    imagery?.primary_url ?? imagery?.tile_url ?? imagery?.url ?? undefined;
  const fallback = imagery?.fallback_url;
  const [src, setSrc] = useState<string | undefined>(primary ?? fallback);
  const [failed, setFailed] = useState(false);

  // Reset when upstream URLs change (AOI switch / refresh tick).
  useEffect(() => {
    setSrc(primary ?? fallback);
    setFailed(false);
  }, [primary, fallback]);

  const onError = () => {
    if (src && src === primary && fallback && fallback !== primary) {
      setSrc(fallback);
    } else {
      setFailed(true);
    }
  };

  const corner = (pos: CSSProperties): CSSProperties => ({ ...cornerTick, ...pos });
  const layerLabel = imagery?.layer ? imagery.layer.replace(/_/g, " ") : "";
  const dateLabel = imagery?.capture_utc ?? imagery?.date ?? asOf ?? "";

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
          onError={onError}
        />
      ) : (
        <div style={imageFallback}>
          <span style={fallbackGlyph}>◛ ◛ ◛</span>
          <span>Imagery tile unavailable</span>
          <span className="u-text-mute">
            {imagery?.attribution ?? imagery?.source ?? "NASA EOSDIS GIBS"}
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

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { aoi, layer: "true_color", tick },
  });

  const payload = useMemo<SATPayload>(
    () => (isRecord(data?.data) ? (data?.data as SATPayload) : {}),
    [data?.data],
  );

  const weather = payload.weather;
  const dataMode = payload.data_mode ?? payload.source_mode ?? "";
  const isLive = dataMode.toLowerCase() === "live";
  const isNotConfigured = dataMode.toLowerCase() === "not_configured";
  const degraded = Boolean(payload.degraded) || isNotConfigured;
  const warningsList = Array.isArray(data?.warnings) ? data?.warnings : [];

  const cards = Array.isArray(payload.cards) ? payload.cards : [];
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

  const locationName =
    payload.location ?? payload.label ?? payload.aoi ?? effectiveAoi;
  const lat = num(payload.lat ?? payload.coordinates?.lat);
  const lon = num(payload.lon ?? payload.coordinates?.lon);
  const windDir = num(weather?.wind_dir_deg);
  const cloud = num(weather?.cloud_cover_pct);
  const precip = num(weather?.precip_mm);
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);

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
                  imagery={payload.imagery}
                  location={locationName}
                  asOf={payload.as_of}
                />

                <section style={summaryCard} aria-label="Location weather">
                  <div style={summaryHead}>
                    <div style={summaryLoc}>
                      <span style={locNameStyle}>{locationName}</span>
                      {payload.blurb ? (
                        <span style={locBlurbStyle}>{payload.blurb}</span>
                      ) : (
                        <span style={locBlurbStyle}>
                          {lat !== null && lon !== null
                            ? `${fmt(lat, 3)}, ${fmt(lon, 3)}`
                            : "alt-data observation point"}
                        </span>
                      )}
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={bigTemp}>
                        {fmt(weather?.temperature_c)}
                        <span style={tempUnit}>°C</span>
                      </div>
                      {num(weather?.apparent_c) !== null ? (
                        <div style={metaText}>feels {fmt(weather?.apparent_c)}°C</div>
                      ) : null}
                    </div>
                  </div>

                  <div style={condLine}>
                    <Pill tone={cloudTone(cloud)} variant="soft" withDot={false}>
                      {weather?.summary ?? weather?.conditions ?? "—"}
                    </Pill>
                    {cloud !== null ? (
                      <span style={metaText}>{fmt(cloud, 0)}% cloud</span>
                    ) : null}
                    {precip !== null && precip > 0 ? (
                      <span style={precipChip}>↓ {fmt(precip, 1)} mm</span>
                    ) : null}
                  </div>

                  {cards.length ? (
                    <div style={cardGrid}>
                      {cards.slice(0, 4).map((c, i) => (
                        <StatCard
                          key={`${c.label ?? "card"}-${i}`}
                          label={c.label ?? "—"}
                          value={
                            num(c.value) !== null
                              ? `${fmt(c.value, c.unit === "%" ? 0 : 1)}${c.unit ? ` ${c.unit}` : ""}`
                              : c.value == null
                                ? "—"
                                : String(c.value)
                          }
                          caption={c.caption ?? `AS OF ${utcStamp} UTC`}
                          tone="neutral"
                        />
                      ))}
                    </div>
                  ) : null}

                  <div style={metaRow}>
                    {windDir !== null ? (
                      <span style={metaText}>
                        Wind {compass(windDir)} ({fmt(windDir, 0)}°)
                        {num(weather?.wind_kmh) !== null
                          ? ` · ${fmt(weather?.wind_kmh, 0)} km/h`
                          : ""}
                      </span>
                    ) : null}
                    {num(weather?.humidity_pct) !== null ? (
                      <span style={metaText}>RH {fmt(weather?.humidity_pct, 0)}%</span>
                    ) : null}
                    {weather?.observed_at ? (
                      <span style={metaText}>
                        obs {weather.observed_at.replace("T", " ")}
                      </span>
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

              {degraded && payload.degraded_reason ? (
                <div style={degradeLine}>⚠ {payload.degraded_reason}</div>
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
            value={
              data?.sources?.join(", ") ||
              payload.source ||
              "NASA GIBS · Open-Meteo"
            }
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
  fontSize: 12,
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
  fontSize: 11,
  minHeight: 210,
  background:
    "repeating-linear-gradient(45deg, color-mix(in srgb, var(--grid-color) 22%, transparent) 0 1px, transparent 1px 9px)",
};

const fallbackGlyph: CSSProperties = {
  fontSize: 22,
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
  fontSize: 15,
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
  fontSize: 12,
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

const precipChip: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  fontSize: 10.5,
  fontVariantNumeric: "tabular-nums",
  color: "var(--accent)",
  border: "1px solid color-mix(in srgb, var(--accent) 40%, transparent)",
  borderRadius: 4,
  padding: "1px 6px",
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
  fontSize: 12,
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
  fontSize: 11,
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
  fontSize: 12,
};

export default SATPane;
