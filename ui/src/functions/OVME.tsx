/**
 * OVME — Option Valuation desk (Black-Scholes + Greeks).
 *
 * Pure model pane: spot / strike / tenor / vol / rate / dividend inputs
 * (all persisted under `showme.ovme.*`) drive the backend Black-Scholes-
 * Merton pricer, which returns the premium, all five greeks, a 51-point
 * value curve and per-spot sensitivities.
 *
 * Layout: CALL/PUT toggle + status pill in the header, an inputs strip,
 * a price + greeks card grid, an inline-SVG value curve (value vs
 * intrinsic, current spot + strike markers) and a sampled sensitivity
 * grid table. The request omits the symbol (the backend rejects
 * EQUITY-class instruments for this derivative function) and every price
 * comes from the model — the header pill states "model", never "live".
 */
import { useMemo, type CSSProperties } from "react";
import {
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
import { usePersistentNumber, usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

/* ── payload types ─────────────────────────────────────────────────── */

interface SensitivityPoint {
  spot?: number;
  price?: number;
  intrinsic?: number;
  time_value?: number;
  delta?: number;
}

interface OvmeData {
  status?: string;
  spot?: number;
  strike?: number;
  T?: number;
  years_to_expiry?: number;
  vol?: number;
  rate?: number;
  div_yield?: number;
  type?: string;
  price?: number;
  delta?: number;
  gamma?: number;
  theta?: number;
  vega?: number;
  rho?: number;
  d1?: number;
  d2?: number;
  curve?: SensitivityPoint[];
  sensitivity?: SensitivityPoint[];
  summary?: Record<string, unknown>;
  methodology?: string;
}

/* ── persisted input helpers ───────────────────────────────────────── */

const TYPE_OPTIONS = [
  { value: "CALL", label: "CALL" },
  { value: "PUT", label: "PUT" },
] as const;
type OptType = (typeof TYPE_OPTIONS)[number]["value"];

/* ── pane ──────────────────────────────────────────────────────────── */

export function OVMEPane({ code }: FunctionPaneProps) {
  const [type, setType] = usePersistentOption<OptType>(
    "showme.ovme.type",
    TYPE_OPTIONS.map((o) => o.value),
    "CALL",
  );
  const [spot, setSpot] = usePersistentNumber("showme.ovme.spot", 100);
  const [strike, setStrike] = usePersistentNumber("showme.ovme.strike", 100);
  const [years, setYears] = usePersistentNumber("showme.ovme.years", 0.25);
  const [volPct, setVolPct] = usePersistentNumber("showme.ovme.vol", 30);
  const [ratePct, setRatePct] = usePersistentNumber("showme.ovme.rate", 4.5);
  const [divPct, setDivPct] = usePersistentNumber("showme.ovme.div", 0);

  const { state, data, error, refetch } = useFunction<OvmeData>({
    code,
    params: {
      asset_class: "DERIVATIVE",
      spot,
      strike,
      years_to_expiry: years,
      vol: volPct / 100,
      rate: ratePct / 100,
      div_yield: divPct / 100,
      type,
    },
  });

  const payload = data?.data;
  const curve: SensitivityPoint[] = useMemo(
    () => (payload?.curve && payload.curve.length ? payload.curve : payload?.sensitivity ?? []),
    [payload],
  );
  const isCall = type === "CALL";
  const moneyness =
    spot > 0 && strike > 0
      ? isCall
        ? strike < spot
          ? "ITM"
          : strike > spot
            ? "OTM"
            : "ATM"
        : strike > spot
          ? "ITM"
          : strike < spot
            ? "OTM"
            : "ATM"
      : "—";
  // Sample the 51-point curve down to an 11-row grid (every 0.05 of spot).
  const gridRows = useMemo(
    () => curve.filter((_, i) => i % 5 === 0),
    [curve],
  );

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8" aria-busy="true">
      <Skeleton height={56} />
      <Skeleton height={56} />
      <Skeleton height={120} />
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
  ) : payload?.status !== "ok" ? (
    <Empty
      title="Model needs valid inputs"
      body={
        firstString(payload?.summary, "error") ??
        "Spot and strike must be positive numbers for the Black-Scholes pricer."
      }
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {/* inputs strip */}
      <section style={inputRowStyle} aria-label="Valuation inputs">
        <label style={inputLabelStyle}>
          <span className="u-text-mute">SPOT</span>
          <NumInput value={spot} step={1} min={0.01} ariaLabel="Underlying spot price" onChange={setSpot} />
        </label>
        <label style={inputLabelStyle}>
          <span className="u-text-mute">STRIKE</span>
          <NumInput value={strike} step={1} min={0.01} ariaLabel="Option strike price" onChange={setStrike} />
        </label>
        <label style={inputLabelStyle}>
          <span className="u-text-mute">YEARS</span>
          <NumInput value={years} step={0.05} min={0.01} ariaLabel="Years to expiry" onChange={setYears} />
        </label>
        <label style={inputLabelStyle}>
          <span className="u-text-mute">VOL %</span>
          <NumInput value={volPct} step={1} min={0.01} ariaLabel="Implied volatility percent" onChange={setVolPct} />
        </label>
        <label style={inputLabelStyle}>
          <span className="u-text-mute">RATE %</span>
          <NumInput value={ratePct} step={0.25} ariaLabel="Risk-free rate percent" onChange={setRatePct} />
        </label>
        <label style={inputLabelStyle}>
          <span className="u-text-mute">DIV %</span>
          <NumInput value={divPct} step={0.25} min={0} ariaLabel="Dividend yield percent" onChange={setDivPct} />
        </label>
      </section>

      {/* price + greeks cards */}
      <section style={kpiGridStyle} aria-label="Price and greeks">
        <StatCard
          label="Price"
          value={fmtNum(payload?.price, 3)}
          caption={`${type} · ${moneyness} · T ${fmtNum(years, 2)}Y`}
          tone="neutral"
        />
        <StatCard
          label="Delta"
          value={fmtNum(payload?.delta, 4)}
          caption="Δ PER 1 UNDERLYING"
          tone={deltaTone(payload?.delta)}
        />
        <StatCard
          label="Gamma"
          value={fmtNum(payload?.gamma, 4)}
          caption="Δ CHANGE PER 1 UNIT"
          tone="neutral"
        />
        <StatCard
          label="Theta / day"
          value={fmtNum(payload?.theta, 4)}
          caption="DECAY PER DAY"
          tone={thetaTone(payload?.theta)}
        />
        <StatCard
          label="Vega / vol pt"
          value={fmtNum(payload?.vega, 4)}
          caption="PER 1 VOL POINT"
          tone="neutral"
        />
        <StatCard
          label="Rho / rate pt"
          value={fmtNum(payload?.rho, 4)}
          caption="PER 1 RATE POINT"
          tone="neutral"
        />
      </section>

      {/* value curve */}
      <ValueChart
        curve={curve}
        spot={spot}
        strike={strike}
        optionType={type}
        price={payload?.price}
      />

      {/* sensitivity grid */}
      <section style={tableWrapStyle} aria-label="Sensitivity grid">
        <table style={tableStyle} aria-label="Value sensitivity to spot">
          <thead>
            <tr>
              {["Spot", "Value", "Intrinsic", "Time value", "Delta"].map((h, i) => (
                <th key={h} style={{ ...thStyle, textAlign: i === 0 ? "left" : "right" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {gridRows.map((r) => {
              const rowSpot = num(r.spot);
              const nearSpot = rowSpot != null && Math.abs(rowSpot - spot) < 1e-9;
              return (
                <tr
                  key={rowSpot ?? gridRows.indexOf(r)}
                  style={nearSpot ? { background: "var(--accent-soft)" } : undefined}
                  aria-label={`At spot ${fmtNum(rowSpot)}: value ${fmtNum(r.price, 3)}, delta ${fmtNum(r.delta, 3)}`}
                >
                  <td style={{ ...tdStyle, ...(nearSpot ? monoAccentStyle : {}) }}>
                    {fmtNum(rowSpot)}
                    {nearSpot ? " ◂" : ""}
                  </td>
                  <td style={tdNumStyle}>{fmtNum(r.price, 3)}</td>
                  <td style={tdNumStyle}>{fmtNum(r.intrinsic, 3)}</td>
                  <td style={tdNumStyle}>{fmtNum(r.time_value, 3)}</td>
                  <td style={tdNumStyle}>{fmtNum(r.delta, 4)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="u-text-mute" style={noteTextStyle}>
          sampled every 5th point of the {curve.length}-point sensitivity run ·
          model d1 {fmtNum(payload?.d1, 3)} / d2 {fmtNum(payload?.d2, 3)}
        </div>
      </section>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Option Valuation — ${type} ${fmtNum(strike)}`}
          subtitle={`S ${fmtNum(spot)} · T ${fmtNum(years, 2)}Y · vol ${fmtNum(volPct)}% · r ${fmtNum(ratePct)}% · q ${fmtNum(divPct)}%`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                model
              </Pill>
              <SegmentedControl
                label="TYPE"
                value={type}
                options={TYPE_OPTIONS}
                onChange={setType}
                title="Option type"
              />
              <LoadStatePill state={state} status={payload?.status} />
              <RefreshButton loading={state === "loading"} onClick={refetch} title="Reprice option" />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={payload?.status ?? state} />
          <StatusDivider />
          <StatusSection label="model" value={payload?.type ?? type} tone="accent" />
          <StatusDivider />
          <StatusSection label="grid" value={`${curve.length} pt`} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── value curve (inline SVG, tokens only) ─────────────────────────── */

const CHART_W = 560;
const CHART_H = 150;
const CHART_PAD_X = 10;
const CHART_PAD_TOP = 10;
const CHART_PAD_BOTTOM = 16;

function ValueChart({
  curve,
  spot,
  strike,
  optionType,
  price,
}: {
  curve: SensitivityPoint[];
  spot: number;
  strike: number;
  optionType: string;
  price?: number;
}) {
  const geom = useMemo(() => {
    const xs: number[] = [];
    const values: number[] = [];
    const intr: number[] = [];
    for (const p of curve) {
      const x = num(p.spot);
      const v = num(p.price);
      const i = num(p.intrinsic);
      if (x == null || v == null || i == null) continue;
      xs.push(x);
      values.push(v);
      intr.push(i);
    }
    if (xs.length < 2) return null;
    let lo = 0;
    let hi = 0;
    for (const v of values) {
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    const span = hi - lo || 1;
    const xMin = xs[0];
    const xMax = xs[xs.length - 1];
    const xSpan = xMax - xMin || 1;
    const plotH = CHART_H - CHART_PAD_TOP - CHART_PAD_BOTTOM;
    const px = (x: number) =>
      CHART_PAD_X + ((x - xMin) / xSpan) * (CHART_W - 2 * CHART_PAD_X);
    const py = (v: number) => CHART_PAD_TOP + (1 - (v - lo) / span) * plotH;
    const path = (vals: number[]) =>
      vals
        .map((v, i) => `${i === 0 ? "M" : "L"}${px(xs[i]).toFixed(1)},${py(v).toFixed(1)}`)
        .join(" ");
    return {
      px,
      valuePath: path(values),
      intrinsicPath: path(intr),
      xMin,
      xMax,
    };
  }, [curve]);

  if (!geom) {
    return (
      <div className="u-text-mute" style={noteTextStyle}>
        Curve data unavailable for chart.
      </div>
    );
  }

  const spotX = spot >= geom.xMin && spot <= geom.xMax ? geom.px(spot) : null;
  const strikeX = strike >= geom.xMin && strike <= geom.xMax ? geom.px(strike) : null;

  return (
    <section style={chartCardStyle} aria-label="Option value curve">
      <div style={chartHeadStyle}>
        <span className="u-text-mute" style={noteTextStyle}>
          VALUE VS SPOT · {curve.length} PTS · {optionType}
        </span>
        <span style={monoStrongStyle}>{fmtNum(price, 3)}</span>
      </div>
      <svg
        width="100%"
        height={CHART_H}
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        role="img"
        aria-label={`${optionType} value from spot ${fmtNum(geom.xMin)} to ${fmtNum(geom.xMax)}, currently ${fmtNum(price, 3)}`}
        preserveAspectRatio="none"
      >
        {/* intrinsic (muted, dashed) */}
        <path
          d={geom.intrinsicPath}
          fill="none"
          stroke="var(--text-mute)"
          strokeWidth={1}
          strokeDasharray="4 3"
        />
        {/* model value (accent) */}
        <path d={geom.valuePath} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
        {/* strike marker */}
        {strikeX != null && (
          <line
            x1={strikeX}
            x2={strikeX}
            y1={CHART_PAD_TOP}
            y2={CHART_H - CHART_PAD_BOTTOM}
            stroke="var(--text-mute)"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
        )}
        {/* current spot marker */}
        {spotX != null && (
          <line
            x1={spotX}
            x2={spotX}
            y1={CHART_PAD_TOP}
            y2={CHART_H - CHART_PAD_BOTTOM}
            stroke="var(--positive)"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        )}
        <text x={CHART_PAD_X} y={CHART_H - 4} fontSize={9} fill="var(--text-mute)" fontFamily="JetBrains Mono, monospace">
          {fmtNum(geom.xMin, 0)}
        </text>
        <text
          x={CHART_W - CHART_PAD_X}
          y={CHART_H - 4}
          fontSize={9}
          fill="var(--text-mute)"
          textAnchor="end"
          fontFamily="JetBrains Mono, monospace"
        >
          {fmtNum(geom.xMax, 0)}
        </text>
      </svg>
      <div style={legendRowStyle}>
        <span style={legendItemStyle}>
          <svg width={18} height={6} aria-hidden>
            <line x1={0} x2={18} y1={3} y2={3} stroke="var(--accent)" strokeWidth={1.5} />
          </svg>
          Model value
        </span>
        <span style={legendItemStyle}>
          <svg width={18} height={6} aria-hidden>
            <line x1={0} x2={18} y1={3} y2={3} stroke="var(--text-mute)" strokeWidth={1} strokeDasharray="4 3" />
          </svg>
          Intrinsic
        </span>
        <span style={legendItemStyle}>
          <svg width={10} height={8} aria-hidden>
            <line x1={5} x2={5} y1={0} y2={8} stroke="var(--positive)" strokeWidth={1} strokeDasharray="3 3" />
          </svg>
          Spot
        </span>
        <span style={legendItemStyle}>
          <svg width={10} height={8} aria-hidden>
            <line x1={5} x2={5} y1={0} y2={8} stroke="var(--text-mute)" strokeWidth={1} strokeDasharray="2 3" />
          </svg>
          Strike
        </span>
      </div>
    </section>
  );
}

/* ── small input ───────────────────────────────────────────────────── */

function NumInput({
  value,
  onChange,
  step = 1,
  min,
  ariaLabel,
}: {
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  ariaLabel: string;
}) {
  return (
    <input
      type="number"
      className="fn-num-input"
      style={numInputStyle}
      value={String(value)}
      step={step}
      min={min}
      aria-label={ariaLabel}
      onChange={(e) => {
        const n = Number(e.target.value);
        if (e.target.value.trim() !== "" && Number.isFinite(n) && (min == null || n >= min)) {
          onChange(n);
        }
      }}
    />
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function firstString(rec: Record<string, unknown> | undefined, key: string): string | null {
  const v = rec?.[key];
  return typeof v === "string" && v.trim() ? v : null;
}

function deltaTone(v: unknown): "positive" | "negative" | "neutral" {
  const n = num(v);
  if (n == null) return "neutral";
  return n > 0 ? "positive" : n < 0 ? "negative" : "neutral";
}

function thetaTone(v: unknown): "negative" | "neutral" {
  const n = num(v);
  return n != null && n < 0 ? "negative" : "neutral";
}

function fmtNum(v: unknown, digits = 2): string {
  const n = num(v);
  if (n == null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/* ── styles (design tokens only) ───────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: 10,
};

const inputRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "end",
  gap: 12,
};

const inputLabelStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 3,
  fontSize: 9,
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.06em",
};

const numInputStyle: CSSProperties = {
  width: 84,
  padding: "3px 6px",
  background: "var(--bg-raised, transparent)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-md, 4px)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 11,
};

const chartCardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  padding: "10px 12px",
  border: "1px solid var(--border)",
  borderRadius: 8,
  background: "var(--bg-raised, transparent)",
};

const chartHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 12,
};

const legendRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 14,
  alignItems: "center",
};

const legendItemStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  fontSize: 10,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const tableWrapStyle: CSSProperties = { minWidth: 0 };

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  tableLayout: "fixed",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 11,
};

const thStyle: CSSProperties = {
  padding: "4px 8px",
  color: "var(--text-mute)",
  fontWeight: 500,
  letterSpacing: "0.06em",
  fontSize: 9,
  textTransform: "uppercase",
  borderBottom: "1px solid var(--border-subtle)",
};

const tdStyle: CSSProperties = {
  padding: "3px 8px",
  color: "var(--text-primary)",
  borderBottom: "1px solid var(--border-subtle)",
};

const tdNumStyle: CSSProperties = {
  ...tdStyle,
  textAlign: "right",
};

const monoAccentStyle: CSSProperties = {
  color: "var(--accent)",
  fontWeight: 700,
};

const noteTextStyle: CSSProperties = {
  fontSize: 10,
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.05em",
  marginTop: 6,
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};
