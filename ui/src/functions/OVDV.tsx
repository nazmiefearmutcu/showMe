/**
 * OVDV — FX Option Volatility Surface.
 *
 * Bloomberg `OVDV<GO>` analogue / FX cousin of IVOL: the OTC FX
 * implied-vol surface across standard tenors (1W..2Y) × delta buckets
 * (10P / 25P / ATM / 25C / 10C) for a currency pair, rendered as a
 * heatmap grid, with the ATM term-structure line below and KPI cards
 * for the ATM / 25Δ risk-reversal / 25Δ butterfly inputs.
 *
 * The sidecar anchors the ATM curve to LIVE FX realized vol when
 * yfinance history is available (`vol_source === "live_realized_vol"`,
 * `data_mode === "DELAYED_REFERENCE"`), otherwise it labels the surface
 * `reference_fx_vol_model` (`data_mode === "MODELED"`) and emits a
 * warning. The pane surfaces that distinction honestly so a modeled
 * surface is never mistaken for vendor-quoted OTC vols.
 *
 * Payload (data?.data) keys consumed:
 *   pair, as_of, vol_source, data_mode, source_mode, methodology,
 *   warnings[], tenors[], delta_buckets[],
 *   surface[] / rows[] {tenor, delta, vol, vol_decimal, tenor_years, source_mode},
 *   series[] {tenor, tenor_years, vol}, cards{} or cards[] {key,label,value}
 * Envelope keys: sources[], elapsed_ms, warnings[].
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
  Sparkline,
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

interface SurfaceRow {
  tenor?: string;
  delta?: string;
  vol?: number;
  vol_decimal?: number;
  tenor_years?: number;
  source_mode?: string;
}

interface TermPoint {
  tenor?: string;
  tenor_years?: number;
  vol?: number;
}

interface OVDVCard {
  key?: string;
  label?: string;
  value?: number | string | null;
}

interface OVDVPayload {
  pair?: string;
  as_of?: string;
  surface?: SurfaceRow[];
  rows?: SurfaceRow[];
  series?: TermPoint[];
  cards?: OVDVCard[] | Record<string, unknown>;
  vol_source?: string;
  data_mode?: string;
  source_mode?: string;
  tenors?: string[];
  delta_buckets?: string[];
  methodology?: string;
  warnings?: string[];
  // Card-schema slots are also echoed at the top level by the handler.
  atm_vol_pct?: number;
  risk_reversal_25d_pct?: number;
  butterfly_25d_pct?: number;
}

const PAIRS = [
  { id: "EURUSD", label: "EUR/USD" },
  { id: "USDJPY", label: "USD/JPY" },
  { id: "GBPUSD", label: "GBP/USD" },
  { id: "AUDUSD", label: "AUD/USD" },
  { id: "USDCHF", label: "USD/CHF" },
] as const;
type PairId = (typeof PAIRS)[number]["id"];
const PAIR_IDS = PAIRS.map((p) => p.id);

// Canonical delta order across the smile (puts -> ATM -> calls).
const DELTA_ORDER = ["10P", "25P", "ATM", "25C", "10C"];
const REFRESH_MS = 60_000;

export function OVDVPane({ code }: FunctionPaneProps) {
  const [pair, setPair] = usePersistentOption<PairId>(
    "showme.ovdv-pair",
    PAIR_IDS,
    "EURUSD",
  );
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { pair, tick },
  });

  const payload = useMemo<OVDVPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as OVDVPayload)
        : {},
    [data?.data],
  );

  const surface = useMemo<SurfaceRow[]>(() => {
    const raw = Array.isArray(payload.surface)
      ? payload.surface
      : Array.isArray(payload.rows)
        ? payload.rows
        : [];
    return raw.filter((r) => r && typeof r.tenor === "string");
  }, [payload.surface, payload.rows]);

  const series = useMemo<TermPoint[]>(
    () => (Array.isArray(payload.series) ? payload.series : []),
    [payload.series],
  );

  // Distinct tenor rows in chronological order; distinct delta columns.
  const tenors = useMemo<string[]>(() => {
    const seen: string[] = [];
    const fromPayload = Array.isArray(payload.tenors) ? payload.tenors : [];
    for (const t of fromPayload) if (t && !seen.includes(t)) seen.push(t);
    for (const r of surface) {
      if (r.tenor && !seen.includes(r.tenor)) seen.push(r.tenor);
    }
    return seen;
  }, [payload.tenors, surface]);

  const deltas = useMemo<string[]>(() => {
    const present = new Set<string>();
    for (const r of surface) if (r.delta) present.add(r.delta);
    const ordered = DELTA_ORDER.filter((d) => present.has(d));
    // Any non-standard buckets get appended after the canonical ones.
    for (const d of present) if (!ordered.includes(d)) ordered.push(d);
    return ordered.length ? ordered : DELTA_ORDER;
  }, [surface]);

  // Fast lookup: tenor -> delta -> vol(%).
  const cellMap = useMemo(() => {
    const m = new Map<string, Map<string, number>>();
    for (const r of surface) {
      if (!r.tenor || !r.delta || typeof r.vol !== "number") continue;
      if (!m.has(r.tenor)) m.set(r.tenor, new Map());
      m.get(r.tenor)!.set(r.delta, r.vol);
    }
    return m;
  }, [surface]);

  const volStats = useMemo(() => {
    const vals = surface
      .map((r) => r.vol)
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
    if (!vals.length) return { min: 0, max: 0 };
    return { min: Math.min(...vals), max: Math.max(...vals) };
  }, [surface]);

  // Cards may arrive as an array [{key,label,value}] or as a dict {key: value}.
  const cardLookup = useMemo<Record<string, number | undefined>>(() => {
    const out: Record<string, number | undefined> = {};
    const c = payload.cards;
    if (Array.isArray(c)) {
      for (const card of c) {
        if (card && typeof card.key === "string") {
          out[card.key] = toNum(card.value);
        }
      }
    } else if (c && typeof c === "object") {
      for (const [k, v] of Object.entries(c)) out[k] = toNum(v);
    }
    return out;
  }, [payload.cards]);

  const cardVal = (key: string, topLevel?: number): number | undefined =>
    cardLookup[key] ?? toNum(topLevel);

  const dataMode = payload.data_mode ?? payload.source_mode ?? "MODELED";
  const volSource = payload.vol_source ?? "user_inputs";
  const isLive = volSource === "live_realized_vol";

  const warningsList = useMemo<string[]>(() => {
    const fromPayload = Array.isArray(payload.warnings) ? payload.warnings : [];
    const fromEnvelope = Array.isArray(data?.warnings) ? data.warnings : [];
    return [...fromPayload, ...fromEnvelope.map((w) => String(w))];
  }, [payload.warnings, data?.warnings]);

  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);
  const sources =
    data?.sources?.join(", ") || (isLive ? "yfinance" : "reference_fx_vol_model");

  // ATM term-structure points (chronological) for the line + sparkline.
  const term = useMemo<{ tenor: string; vol: number }[]>(() => {
    const pts = series.length
      ? series
      : tenors.map((t) => ({
          tenor: t,
          tenor_years: undefined,
          vol: cellMap.get(t)?.get("ATM"),
        }));
    return pts
      .filter((p) => typeof p.vol === "number" && Number.isFinite(p.vol))
      .map((p) => ({ tenor: p.tenor ?? "—", vol: p.vol as number }));
  }, [series, tenors, cellMap]);

  const atmVals = term.map((p) => p.vol);
  const frontAtm = atmVals[0];
  const backAtm = atmVals[atmVals.length - 1];
  const termSlope =
    frontAtm != null && backAtm != null ? backAtm - frontAtm : null;
  const slopeTone: "neutral" | "positive" | "negative" =
    termSlope == null ? "neutral" : termSlope >= 0 ? "positive" : "negative";

  const rr = cardVal("risk_reversal_25d_pct", payload.risk_reversal_25d_pct);
  const bf = cardVal("butterfly_25d_pct", payload.butterfly_25d_pct);
  const atmFront = cardVal("atm_vol_pct", payload.atm_vol_pct) ?? frontAtm;

  // Delta-grid columns: tenor label + one heat cell per delta bucket.
  const cols = useMemo<DataGridColumn<{ tenor: string }>[]>(() => {
    const tenorCol: DataGridColumn<{ tenor: string }> = {
      key: "tenor",
      header: "Tenor",
      width: 78,
      render: (r) => <span style={tenorCell}>{r.tenor}</span>,
    };
    const deltaCols: DataGridColumn<{ tenor: string }>[] = deltas.map(
      (delta) => ({
        key: `d_${delta}`,
        header: delta,
        numeric: true,
        width: 92,
        render: (r) => {
          const vol = cellMap.get(r.tenor)?.get(delta);
          if (vol == null || !Number.isFinite(vol)) {
            return <span style={emptyCell}>—</span>;
          }
          return (
            <HeatCell
              vol={vol}
              min={volStats.min}
              max={volStats.max}
              emphasis={delta === "ATM"}
            />
          );
        },
      }),
    );
    return [tenorCol, ...deltaCols];
  }, [deltas, cellMap, volStats]);

  const gridRows = useMemo(() => tenors.map((t) => ({ tenor: t })), [tenors]);

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="FX vol surface"
          subtitle={`${payload.pair ?? pair} · ${tenors.length}×${deltas.length} grid · poll ${REFRESH_MS / 1000}s · ${dataMode}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {tenors.length} ten
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live realized vol" : "reference model"}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={PAIRS.map((p) => ({ id: p.id, label: p.label }))}
            active={pair}
            onChange={(id) => setPair(id as PairId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={340} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : surface.length === 0 ? (
            <Empty
              title="No surface"
              body={`No OVDV vol surface for ${payload.pair ?? pair}.`}
            />
          ) : (
            <div className="u-grid-gap-14">
              {!isLive ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">Reference vol model</strong>
                  <span className="u-text-secondary">
                    The ATM term structure is labelled <code>{dataMode}</code> —
                    no live OTC FX vol vendor (or realized-vol history) is
                    configured. The smile wings are modeled from the 25Δ RR / BF
                    inputs. Treat the surface as a labelled reference, not
                    vendor-quoted OTC vols.
                  </span>
                </div>
              ) : null}
              {warningsList.length ? (
                <div style={warningBox}>
                  <strong className="u-text-warn">Provider warnings</strong>
                  <ul style={warningList}>
                    {warningsList.slice(0, 3).map((w, i) => (
                      <li key={i} className="u-text-secondary">
                        {w}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <section style={kpiGrid} aria-label="OVDV KPI ribbon">
                <StatCard
                  label="ATM Vol (front)"
                  value={fmtPct(atmFront)}
                  caption={`${term[0]?.tenor ?? "—"} · ${payload.pair ?? pair}`}
                  tone="neutral"
                  trend={atmVals}
                />
                <StatCard
                  label="25Δ Risk Reversal"
                  value={fmtPctSigned(rr)}
                  caption="Call − put skew (25Δ)"
                  tone={(rr ?? 0) >= 0 ? "positive" : "negative"}
                />
                <StatCard
                  label="25Δ Butterfly"
                  value={fmtPct(bf)}
                  caption="Smile convexity (25Δ)"
                  tone="neutral"
                />
                <StatCard
                  label="Term slope"
                  value={
                    termSlope == null
                      ? "—"
                      : `${termSlope >= 0 ? "+" : ""}${termSlope.toFixed(2)} pp`
                  }
                  caption={
                    term.length
                      ? `${term[0]?.tenor} → ${term[term.length - 1]?.tenor}`
                      : "—"
                  }
                  tone={slopeTone}
                  trend={atmVals}
                />
              </section>

              <section style={surfaceWrap} aria-label="Vol surface grid">
                <div style={surfaceHead}>
                  <span style={metaLabel}>
                    Surface · tenor × delta (implied vol %)
                  </span>
                  <span style={metaLabel}>
                    {fmtPct(volStats.min)} – {fmtPct(volStats.max)}
                  </span>
                </div>
                <DataGrid
                  columns={cols}
                  rows={gridRows}
                  rowKey={(r) => r.tenor}
                  density="compact"
                />
                <VolLegend min={volStats.min} max={volStats.max} />
              </section>

              <section style={termPanel} aria-label="ATM term structure">
                <div style={surfaceHead}>
                  <span style={metaLabel}>ATM term structure</span>
                  <span className="u-inline-flex">
                    <Sparkline
                      values={atmVals.length ? atmVals : [0, 0]}
                      width={140}
                      height={28}
                      tone={slopeTone}
                    />
                  </span>
                </div>
                <TermStructure points={term} />
              </section>

              {payload.methodology ? (
                <section style={methodPanel}>
                  <div style={metaLabel}>Methodology</div>
                  <p style={methodText}>{payload.methodology}</p>
                </section>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={sources} />
          <StatusDivider />
          <StatusSection
            label="mode"
            value={dataMode}
            tone={isLive ? "positive" : "warn"}
          />
          <StatusDivider />
          <StatusSection label="vol src" value={volSource} />
          <StatusDivider />
          <StatusSection label="cells" value={surface.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="pair"
            value={payload.pair ?? pair}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/** A single heatmap cell: background intensity scales with vol across the surface. */
function HeatCell({
  vol,
  min,
  max,
  emphasis,
}: {
  vol: number;
  min: number;
  max: number;
  emphasis?: boolean;
}) {
  const span = max - min;
  const t = span > 1e-9 ? (vol - min) / span : 0.5;
  // Cool (low vol) -> warm (high vol): blend accent -> negative.
  const lowTone = "var(--accent)";
  const highTone = "var(--negative)";
  const intensity = 0.12 + Math.max(0, Math.min(1, t)) * 0.5;
  const cellTone = t >= 0.5 ? highTone : lowTone;
  return (
    <span
      style={{
        ...heatCell,
        background: `color-mix(in srgb, ${cellTone} ${(intensity * 100).toFixed(0)}%, transparent)`,
        borderColor: emphasis
          ? "color-mix(in srgb, var(--accent) 55%, transparent)"
          : "transparent",
        fontWeight: emphasis ? 700 : 600,
      }}
    >
      {vol.toFixed(2)}
    </span>
  );
}

function VolLegend({ min, max }: { min: number; max: number }) {
  const mid = (min + max) / 2;
  return (
    <div style={legendRow} aria-hidden>
      <span style={legendLabel}>{fmtPct(min)}</span>
      <span style={legendBar} />
      <span style={legendLabel}>{fmtPct(mid)}</span>
      <span style={{ ...legendBar, ...legendBarHigh }} />
      <span style={legendLabel}>{fmtPct(max)}</span>
    </div>
  );
}

/** ATM term-structure as horizontal bars per tenor — bar length = relative vol. */
function TermStructure({ points }: { points: { tenor: string; vol: number }[] }) {
  if (!points.length) {
    return <div style={legendLabel}>No ATM term points.</div>;
  }
  const max = Math.max(...points.map((p) => p.vol), 1e-6);
  return (
    <div style={termList}>
      {points.map((p) => {
        const width = Math.max(4, Math.min(100, (p.vol / max) * 100));
        return (
          <div key={p.tenor} style={termRow}>
            <span style={termTenor}>{p.tenor}</span>
            <span style={termTrack}>
              <span style={{ ...termFill, width: `${width}%` }} />
            </span>
            <span style={termVol}>{p.vol.toFixed(2)}%</span>
          </div>
        );
      })}
    </div>
  );
}

function toNum(v: unknown): number | undefined {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

function fmtPct(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(2)}%`;
}

function fmtPctSigned(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(3)}%`;
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const surfaceWrap: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: 12,
  display: "grid",
  gap: 10,
};

const surfaceHead: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const tenorCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-display)",
  fontWeight: 600,
  letterSpacing: "0.02em",
};

const heatCell: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  minWidth: 64,
  padding: "2px 6px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid transparent",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-display)",
};

const emptyCell: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const legendRow: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
};

const legendBar: CSSProperties = {
  flex: "1 1 auto",
  height: 6,
  borderRadius: 999,
  background:
    "linear-gradient(90deg, color-mix(in srgb, var(--accent) 18%, transparent), color-mix(in srgb, var(--accent) 55%, transparent))",
};

const legendBarHigh: CSSProperties = {
  background:
    "linear-gradient(90deg, color-mix(in srgb, var(--negative) 22%, transparent), color-mix(in srgb, var(--negative) 60%, transparent))",
};

const legendLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 10,
  letterSpacing: "0.04em",
  flex: "0 0 auto",
};

const termPanel: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: 12,
  display: "grid",
  gap: 10,
};

const termList: CSSProperties = {
  display: "grid",
  gap: 7,
};

const termRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "64px minmax(0, 1fr) 72px",
  alignItems: "center",
  gap: 10,
  fontSize: 12,
};

const termTenor: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-display)",
  fontWeight: 600,
  fontSize: 11,
};

const termTrack: CSSProperties = {
  height: 8,
  background: "var(--surface-3)",
  borderRadius: 999,
  overflow: "hidden",
};

const termFill: CSSProperties = {
  height: "100%",
  borderRadius: 999,
  background:
    "linear-gradient(90deg, color-mix(in srgb, var(--accent) 45%, transparent), var(--accent))",
  transition: "width var(--motion-base)",
};

const termVol: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
  textAlign: "right",
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
};

const methodText: CSSProperties = {
  margin: "6px 0 0",
  color: "var(--text-secondary)",
  lineHeight: 1.5,
  fontSize: 12,
};
