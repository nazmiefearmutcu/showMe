/**
 * FRD — FX Forward Rates (covered interest parity).
 *
 * Live spot + CIP forward-points grid across the OTC tenor ladder
 * (1W..1Y). Header: pair segmented control (persisted) + status pill +
 * refresh. Body: KPI ribbon (spot, 3M forward, rate differential, 1Y
 * points) + forward-curve SVG with a dashed spot overlay + per-tenor
 * table (forward, points, pips, annualized carry). When the live spot
 * cannot be fetched the backend labels rows `reference_model`; the pane
 * surfaces that as a degraded banner instead of pretending the curve is
 * live.
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
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface FRDRow {
  pair?: string;
  tenor?: string;
  tenor_years?: number;
  spot?: number;
  forward?: number;
  forward_points?: number;
  base_rate?: number;
  quote_rate?: number;
  source_mode?: string;
}

interface FRDData {
  pair?: string;
  base?: string;
  quote?: string;
  S?: number;
  F?: number;
  r_base?: number;
  r_quote?: number;
  rows?: FRDRow[];
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

export function FRDPane({ code, symbol }: FunctionPaneProps) {
  const [pair, setPair] = usePersistentOption<PairId>(
    "showme.frd.pair",
    PAIR_IDS,
    "EURUSD",
  );
  // An explicit FX pair symbol (navigation intent) beats the stored pick.
  const effectivePair = normalizePair(symbol) ?? pair;
  const { state, data, error, refetch } = useFunction<FRDData>({
    code,
    symbol: effectivePair,
    params: { pair: effectivePair },
  });

  const payload = data?.data;
  const warnings = data?.warnings ?? [];
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  const spot = payload?.S;
  const isLive = rows[0]?.source_mode === "live_yfinance_quote";

  const stats = useMemo(() => deriveStats(rows, payload), [rows, payload]);

  const curve = useMemo(() => buildCurve(rows, spot), [rows, spot]);

  const COLS: DataGridColumn<FRDRow>[] = useMemo(
    () => [
      {
        key: "tenor",
        header: "Tenor",
        width: 84,
        render: (r) => (
          <span style={monoStrongStyle}>{r.tenor ?? "—"}</span>
        ),
      },
      {
        key: "tenor_years",
        header: "Years",
        numeric: true,
        width: 88,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtYears(r.tenor_years)}</span>
        ),
      },
      {
        key: "spot",
        header: "Spot",
        numeric: true,
        width: 108,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtFx(r.spot)}</span>
        ),
      },
      {
        key: "forward",
        header: "Forward",
        numeric: true,
        width: 116,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtFx(r.forward)}</span>
        ),
      },
      {
        key: "forward_points",
        header: "F − S",
        numeric: true,
        width: 116,
        render: (r) => (
          <span
            style={{
              ...monoPrimaryStyle,
              color: pointColor(r.forward_points),
            }}
          >
            {fmtDiff(r.forward_points)}
          </span>
        ),
      },
      {
        key: "carry",
        header: "Ann. carry %",
        numeric: true,
        width: 122,
        render: (r) => (
          <span
            style={{
              ...monoPrimaryStyle,
              color: pointColor(annualizedCarry(r)),
            }}
          >
            {fmtCarry(annualizedCarry(r))}
          </span>
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
          title="No forward tenors returned"
          body="The CIP grid came back empty for this pair."
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
        <section style={kpiGridStyle} aria-label="FRD KPI ribbon">
          <StatCard
            label={`Spot ${payload?.pair ?? ""}`}
            value={fmtFx(spot)}
            caption={isLive ? "LIVE YFINANCE" : "REFERENCE MODEL"}
            tone={isLive ? "positive" : "neutral"}
          />
          <StatCard
            label="3M forward"
            value={fmtFx(stats.fwd3m)}
            caption={`${fmtDiff(stats.points3m)} F−S`}
            tone="neutral"
          />
          <StatCard
            label="Rate diff"
            value={`${fmtSigned((payload?.r_quote ?? 0) - (payload?.r_base ?? 0), 3)}%`}
            caption={`${payload?.quote ?? "—"} vs ${payload?.base ?? "—"} RATES`}
            tone={
              (payload?.r_quote ?? 0) >= (payload?.r_base ?? 0)
                ? "positive"
                : "negative"
            }
          />
          <StatCard
            label="1Y F − S"
            value={fmtDiff(stats.points1y)}
            caption={`${fmtCarry(stats.carry1y)} ann.`}
            tone={stats.points1y >= 0 ? "positive" : "negative"}
          />
        </section>
        <figure
          className="frd-curve"
          style={curveStyle}
          role="img"
          aria-label={`FRD forward curve for ${payload?.pair ?? effectivePair}: forward levels by tenor with a dashed spot overlay`}
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
            {curve.forwardPoints.length > 1 ? (
              <polyline
                points={curve.forwardPoints
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
              <span aria-hidden="true" style={swatchAccentStyle} /> forward
            </span>
            <span style={legendRowStyle}>
              <span aria-hidden="true" style={swatchSpotStyle} /> spot overlay
            </span>
            <span style={legendRowStyle}>
              {rows[0]?.tenor ?? "—"} → {rows[rows.length - 1]?.tenor ?? "—"}
            </span>
          </figcaption>
        </figure>
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.tenor ?? "tenor"}-${i}`}
          density="compact"
          ariaLabel="FRD forward-points grid"
        />
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`FX Forwards — ${payload?.pair ?? effectivePair}`}
          subtitle={`${rows.length} tenors · CIP F = S·(1+r_q·T)/(1+r_b·T)`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live spot" : "reference spot"}
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
                title="Refresh forwards"
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
          <StatusSection label="tenors" value={rows.length} />
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

function deriveStats(rows: FRDRow[], payload?: FRDData) {
  const byTenor = (t: string) => rows.find((r) => r.tenor === t);
  const r3m = byTenor("3M");
  const r1y = byTenor("1Y") ?? rows[rows.length - 1];
  return {
    fwd3m: r3m?.forward ?? payload?.F ?? null,
    points3m: r3m?.forward_points ?? 0,
    points1y: r1y?.forward_points ?? 0,
    carry1y: r1y ? annualizedCarry(r1y) : null,
  };
}

/** (F/S − 1)/T in annualized percent — the carry implied by the forward. */
function annualizedCarry(row: FRDRow): number | null {
  const { forward, spot, tenor_years: t } = row;
  if (!forward || !spot || !t) return null;
  return ((forward / spot - 1) / t) * 100;
}

interface CurveGeom {
  forwardPoints: Array<[number, number]>;
  spotY: number | null;
}

function buildCurve(rows: FRDRow[], spot: number | undefined): CurveGeom {
  const fwds = rows
    .map((r) => r.forward)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (fwds.length < 2 || spot == null || !Number.isFinite(spot)) {
    return { forwardPoints: [], spotY: null };
  }
  const levels = [spot, ...fwds];
  const min = Math.min(...levels);
  const max = Math.max(...levels);
  const span = max - min || Math.abs(max) * 0.001 || 1;
  // Pad 12% top and bottom so the spot line never sits on the frame edge.
  const yOf = (v: number) =>
    CURVE_H - 8 - ((v - (min - span * 0.12)) / (span * 1.24)) * (CURVE_H - 16);
  const step = CURVE_W / (rows.length - 1);
  const forwardPoints = rows.map((r, i) => [
    i * step,
    yOf(typeof r.forward === "number" ? r.forward : spot),
  ] as [number, number]);
  return { forwardPoints, spotY: yOf(spot) };
}

function pointColor(v: number | null | undefined): string {
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

function fmtCarry(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function fmtSigned(v: number, digits: number): string {
  if (!Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}`;
}

function fmtYears(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Number(v.toFixed(3)).toString();
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
  fontSize: 10,
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
  fontSize: 11,
  padding: "6px 8px",
  fontFamily: "JetBrains Mono, monospace",
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
