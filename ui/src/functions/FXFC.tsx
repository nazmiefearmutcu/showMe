/**
 * FXFC — FX Forecasts (covered-interest-parity forward carry).
 *
 * Header: pair segmented control (persisted) + source honesty pill +
 * status + refresh. Body: warning banner when the backend fell back to
 * the labelled reference spot + KPI ribbon (spot, 3M forecast, rate
 * differential, vol assumption) + forecast-vs-spot curve (dashed spot
 * overlay) + the horizon table: forecast level, forecast-vs-spot delta
 * (F − S), model bands (spot·vol·√T), confidence, and the per-row
 * source_mode pill.
 *
 * Model note (honesty): forecasts are the CIP forward path and the bands
 * are MODEL bands (spot·vol·√T) — not vendor analyst forecasts. When the
 * live spot cannot be fetched the backend labels rows `reference_model`;
 * the pane mirrors that as a "reference spot" pill + banner instead of
 * pretending the curve is live.
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
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { formatNumberPlain } from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface FXFCRow {
  pair?: string;
  horizon?: string;
  tenor_years?: number;
  spot?: number;
  forecast?: number;
  lower_band?: number;
  upper_band?: number;
  forward_points?: number;
  confidence?: number;
  source_mode?: string;
}

interface FXFCData {
  pair?: string;
  base?: string;
  quote?: string;
  spot?: number;
  base_rate?: number;
  quote_rate?: number;
  vol_annualized?: number;
  source_mode?: string;
  forecast?: FXFCRow[];
  curve?: FXFCRow[];
  methodology?: string;
}

const PAIR_OPTIONS = [
  { value: "EURUSD", label: "EURUSD", title: "PAIR EURUSD" },
  { value: "USDJPY", label: "USDJPY", title: "PAIR USDJPY" },
  { value: "GBPUSD", label: "GBPUSD", title: "PAIR GBPUSD" },
  { value: "AUDUSD", label: "AUDUSD", title: "PAIR AUDUSD" },
  { value: "USDCAD", label: "USDCAD", title: "PAIR USDCAD" },
  { value: "EURGBP", label: "EURGBP", title: "PAIR EURGBP" },
] as const;

type PairId = (typeof PAIR_OPTIONS)[number]["value"];
const PAIR_IDS = PAIR_OPTIONS.map((o) => o.value);

/** Mirror of the backend pair normalizer — 6 alpha letters or bust. */
function normalizePair(raw: string | undefined): PairId | null {
  if (!raw) return null;
  const value = raw.toUpperCase().replace(/[/\s=X-]/g, "");
  if (value.length >= 6 && /^[A-Z]{6}$/.test(value.slice(0, 6))) {
    return value.slice(0, 6) as PairId;
  }
  return null;
}

const CURVE_W = 320;
const CURVE_H = 88;

export function FXFCPane({ code, symbol }: FunctionPaneProps) {
  const [pair, setPair] = usePersistentOption<PairId>(
    "showme.fxfc.pair",
    PAIR_IDS,
    "EURUSD",
  );
  // An explicit FX pair symbol (navigation intent) beats the stored pick.
  const effectivePair = normalizePair(symbol) ?? pair;
  const { state, data, error, refetch } = useFunction<FXFCData>({
    code,
    symbol: effectivePair,
    params: { pair: effectivePair },
  });

  const payload = data?.data;
  const warnings = data?.warnings ?? [];
  const rows: FXFCRow[] = useMemo(
    () => payload?.forecast ?? payload?.curve ?? [],
    [payload],
  );
  // The backend spot chain has several live tiers (live_yfinance_quote,
  // live_ecb_reference, live_official/Frankfurter) plus manual_input. Only
  // `reference_model` is the labelled static fallback — treating every
  // non-yfinance tier as "reference" mislabelled live ECB spot. The
  // envelope-level source_mode is preferred; per-row carries the fallback.
  const sourceMode = payload?.source_mode ?? rows[0]?.source_mode;
  const isLive = typeof sourceMode === "string" && sourceMode.startsWith("live_");
  const isManual = sourceMode === "manual_input";
  const spot = payload?.spot;

  const stats = useMemo(() => deriveStats(rows), [rows]);
  const curve = useMemo(() => buildCurve(rows, spot), [rows, spot]);

  const COLS: DataGridColumn<FXFCRow>[] = useMemo(
    () => [
      {
        key: "horizon",
        header: "Horizon",
        width: 96,
        render: (r) => (
          <span style={monoStrongStyle}>{r.horizon ?? "—"}</span>
        ),
      },
      {
        key: "forecast",
        header: "Forecast",
        numeric: true,
        width: 116,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtFx(r.forecast)}</span>
        ),
      },
      {
        key: "forward_points",
        header: "F − S",
        numeric: true,
        width: 112,
        render: (r) => (
          <span
            style={{
              ...monoPrimaryStyle,
              color: deltaColor(r.forward_points),
            }}
          >
            {fmtDiff(r.forward_points)}
          </span>
        ),
      },
      {
        key: "lower_band",
        header: "Lower band",
        numeric: true,
        width: 116,
        render: (r) => <span style={monoMutedStyle}>{fmtFx(r.lower_band)}</span>,
      },
      {
        key: "upper_band",
        header: "Upper band",
        numeric: true,
        width: 116,
        render: (r) => <span style={monoMutedStyle}>{fmtFx(r.upper_band)}</span>,
      },
      {
        key: "confidence",
        header: "Conf.",
        numeric: true,
        width: 88,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.confidence, 1)}%</span>
        ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 188,
        render: (r) =>
          r.source_mode ? (
            <Pill
              tone={r.source_mode.includes("reference") ? "muted" : "accent"}
              variant="soft"
              withDot={false}
            >
              {r.source_mode}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const warningBanner =
    warnings.length > 0 ? (
      <div role="status" style={warningStyle} aria-label="Data quality warning">
        {warnings.join(" · ")}
      </div>
    ) : null;

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={56} />
        <Skeleton height={96} />
        <Skeleton height={20} />
        <Skeleton height={20} width="80%" />
      </div>
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
    ) : rows.length === 0 ? (
      <div className="u-grid-gap-14">
        {warningBanner}
        <Empty
          title="No forecast horizons returned"
          body="The CIP forecast ladder came back empty for this pair."
          icon="∅"
          action={
            <button onClick={refetch} className="btn">
              Retry
            </button>
          }
        />
      </div>
    ) : (
      <div className="u-grid-gap-14">
        {warningBanner}
        <section style={kpiGridStyle} aria-label="FXFC KPI ribbon">
          <StatCard
            label={`Spot ${payload?.pair ?? effectivePair}`}
            value={fmtFx(spot)}
            caption={
              isLive
                ? `LIVE SPOT · ${sourceMode}`
                : isManual
                  ? "MANUAL SPOT INPUT"
                  : "REFERENCE MODEL SPOT"
            }
            tone={isLive ? "positive" : "neutral"}
          />
          <StatCard
            label={`${stats.horizon} forecast`}
            value={fmtFx(stats.fwd3m)}
            caption={`${fmtDiff(stats.points3m)} F−S`}
            tone="neutral"
          />
          <StatCard
            label="Rate diff"
            value={`${fmtRate((payload?.quote_rate ?? 0) - (payload?.base_rate ?? 0))}%`}
            caption={`${payload?.quote ?? "—"} vs ${payload?.base ?? "—"} RATES`}
            tone={
              (payload?.quote_rate ?? 0) >= (payload?.base_rate ?? 0)
                ? "positive"
                : "negative"
            }
          />
          <StatCard
            label="Vol assumption"
            value={`${fmtRate(payload?.vol_annualized)}%`}
            caption="MODEL BAND INPUT (spot·vol·√T)"
            tone="neutral"
          />
        </section>
        <figure
          className="fxfc-curve"
          style={curveStyle}
          role="img"
          aria-label={`FXFC forecast path for ${payload?.pair ?? effectivePair}: CIP forward forecast by horizon with a dashed spot overlay`}
        >
          <svg
            viewBox={`0 0 ${CURVE_W} ${CURVE_H}`}
            preserveAspectRatio="none"
            style={svgStyle}
            aria-hidden="true"
          >
            {curve.spotY != null ? (
              <line
                x1={0}
                x2={CURVE_W}
                y1={curve.spotY}
                y2={curve.spotY}
                stroke="var(--text-mute)"
                strokeDasharray="4 3"
                strokeWidth={1}
              />
            ) : null}
            {curve.forecastPoints.length > 1 ? (
              <polyline
                points={curve.forecastPoints
                  .map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`)
                  .join(" ")}
                fill="none"
                stroke="var(--accent)"
                strokeWidth={1.6}
              />
            ) : null}
          </svg>
          <figcaption style={curveCaptionStyle}>
            <span style={legendRowStyle}>
              <span aria-hidden="true" style={swatchAccentStyle} /> CIP forecast
            </span>
            <span style={legendRowStyle}>
              <span aria-hidden="true" style={swatchSpotStyle} /> spot overlay
            </span>
            <span style={legendRowStyle}>
              {rows[0]?.horizon ?? "—"} →{" "}
              {rows[rows.length - 1]?.horizon ?? "—"}
            </span>
          </figcaption>
        </figure>
        <p role="note" style={modelNoteStyle} aria-label="Model note">
          Model note: forecast = spot·(1+r_q·T)/(1+r_b·T) (covered interest
          parity); bands = spot·vol·√T are model bands, not vendor analyst
          forecasts.
        </p>
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.horizon ?? "h"}-${i}`}
          density="compact"
          ariaLabel="FXFC forecast table"
        />
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`FX Forecasts — ${payload?.pair ?? effectivePair}`}
          subtitle={`${rows.length} horizons · CIP carry path`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live spot" : isManual ? "manual spot" : "reference spot"}
              </Pill>
              <SegmentedControl
                label="PAIR"
                value={effectivePair}
                options={PAIR_OPTIONS}
                onChange={setPair}
              />
              <LoadStatePill state={state} status={payload ? "ok" : null} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh forecasts"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={state} />
          <StatusDivider />
          <StatusSection label="horizons" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="pair" value={effectivePair} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function deriveStats(rows: FXFCRow[]) {
  const byHorizon = (h: string) => rows.find((r) => r.horizon === h);
  const r3m = byHorizon("3M") ?? rows[Math.min(1, rows.length - 1)];
  return {
    // Label the ladder slot actually used — a custom tenor set without a 3M
    // row must not be presented as a "3M forecast".
    horizon: r3m?.horizon ?? "3M",
    fwd3m: r3m?.forecast ?? null,
    points3m: r3m?.forward_points ?? 0,
  };
}

interface CurveGeom {
  forecastPoints: Array<[number, number]>;
  spotY: number | null;
}

function buildCurve(rows: FXFCRow[], spot: number | undefined): CurveGeom {
  const fwds = rows
    .map((r) => r.forecast)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (fwds.length < 2 || spot == null || !Number.isFinite(spot)) {
    return { forecastPoints: [], spotY: null };
  }
  const levels = [spot, ...fwds];
  const min = Math.min(...levels);
  const max = Math.max(...levels);
  const span = max - min || Math.abs(max) * 0.001 || 1;
  // Pad 12% top and bottom so the spot line never sits on the frame edge.
  const yOf = (v: number) =>
    CURVE_H - 8 - ((v - (min - span * 0.12)) / (span * 1.24)) * (CURVE_H - 16);
  const step = CURVE_W / (rows.length - 1);
  const forecastPoints = rows.map((r, i) => [
    i * step,
    yOf(typeof r.forecast === "number" ? r.forecast : spot),
  ] as [number, number]);
  return { forecastPoints, spotY: yOf(spot) };
}

function deltaColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-mute)";
  if (v > 0) return "var(--positive)";
  if (v < 0) return "var(--negative)";
  return "var(--text-primary)";
}

function fmtFx(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.abs(v) >= 100 ? v.toFixed(3) : v.toFixed(5);
}

function fmtDiff(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const digits = Math.abs(v) < 1 ? 6 : 3;
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

function fmtNum(v: number | null | undefined, digits: number): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return formatNumberPlain(v, digits);
}

function fmtRate(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return (v * 100).toFixed(2);
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const curveStyle: CSSProperties = {
  margin: 0,
  border: "1px solid var(--border, var(--text-mute))",
  padding: 8,
};

const svgStyle: CSSProperties = {
  display: "block",
  width: "100%",
  height: CURVE_H,
};

const curveCaptionStyle: CSSProperties = {
  display: "flex",
  gap: 14,
  alignItems: "center",
  marginTop: 6,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const legendRowStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
};

const swatchAccentStyle: CSSProperties = {
  width: 14,
  height: 2,
  background: "var(--accent)",
  display: "inline-block",
};

const swatchSpotStyle: CSSProperties = {
  width: 14,
  height: 0,
  borderTop: "2px dashed var(--text-mute)",
  display: "inline-block",
};

const warningStyle: CSSProperties = {
  border: "1px solid var(--warning, var(--text-mute))",
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  padding: "6px 8px",
  fontFamily: "JetBrains Mono, monospace",
};

const modelNoteStyle: CSSProperties = {
  margin: 0,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
