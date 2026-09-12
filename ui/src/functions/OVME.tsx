/**
 * OVME — Option Valuation desk (Black-Scholes-Merton + greeks).
 *
 * Recreated 2026-09-11 (options-family redesign, lane L4). One screen, one
 * job: a single compact input strip drives the backend BSM pricer, the
 * value-vs-spot curve is the primary visual (with vega/rho read inline), and
 * the sampled sensitivity curve is a DataGrid with sort / keyboard / CSV.
 *
 * Data honesty: every price is model output (sources=black_scholes_formula),
 * never a market feed — the header carries the single "model" pill. Invalid
 * inputs render the backend's structured reason, missing values render as an
 * em-dash, and no fabricated numbers are shown anywhere.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  Field,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  PaneState,
  Pill,
  StatCard,
  StatusDivider,
  StatusSection,
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type DataGridColumn,
  type GridCsvColumn,
} from "@/design-system";
import { formatNumber, formatNumberFixed } from "@/lib/format";
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
  reason?: string;
  spot?: number;
  strike?: number;
  T?: number;
  years_to_expiry?: number;
  vol?: number;
  rate?: number;
  div_yield?: number;
  type?: string;
  model?: string;
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
}

/* ── persisted controls ────────────────────────────────────────────── */

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
  const gridRows = useMemo(() => curve.filter((_, i) => i % 5 === 0), [curve]);

  const gridColumns = useMemo<DataGridColumn<SensitivityPoint>[]>(
    () => [
      {
        key: "spot",
        header: "Spot",
        width: 92,
        numeric: true,
        sortable: true,
        render: (r) => {
          const rowSpot = num(r.spot);
          const nearSpot = rowSpot != null && Math.abs(rowSpot - spot) < 1e-9;
          return (
            <span
              style={{
                ...monoStrongStyle,
                ...(nearSpot
                  ? {
                      background: "var(--accent-soft)",
                      padding: "1px 4px",
                      borderRadius: "var(--radius-xs)",
                    }
                  : {}),
              }}
            >
              {fmtNum(rowSpot)}
            </span>
          );
        },
      },
      {
        key: "price",
        header: "Value",
        width: 104,
        numeric: true,
        sortable: true,
        render: (r) => <span style={monoStrongStyle}>{fmtNum(r.price, 3)}</span>,
      },
      {
        key: "intrinsic",
        header: "Intrinsic",
        width: 100,
        numeric: true,
        sortable: true,
        render: (r) => <span style={monoStyle}>{fmtNum(r.intrinsic, 3)}</span>,
      },
      {
        key: "time_value",
        header: "Time value",
        width: 110,
        numeric: true,
        sortable: true,
        render: (r) => <span style={monoStyle}>{fmtNum(r.time_value, 3)}</span>,
      },
      {
        key: "delta",
        header: "Delta",
        width: 92,
        numeric: true,
        sortable: true,
        render: (r) => <span style={monoStyle}>{fmtNum(r.delta, 4)}</span>,
      },
    ],
    [spot],
  );

  const csvColumns = useMemo<GridCsvColumn<SensitivityPoint>[]>(
    () => [
      { key: "spot", header: "Spot", value: (r) => r.spot ?? "" },
      { key: "price", header: "Value", value: (r) => r.price ?? "" },
      { key: "intrinsic", header: "Intrinsic", value: (r) => r.intrinsic ?? "" },
      { key: "time_value", header: "Time value", value: (r) => r.time_value ?? "" },
      { key: "delta", header: "Delta", value: (r) => r.delta ?? "" },
    ],
    [],
  );

  const exportCsv = () => {
    downloadGridCsv(
      gridCsvFilename(`ovme-${type.toLowerCase()}`),
      buildGridCsv(csvColumns, gridRows),
    );
  };

  const body = (
    <PaneState
      state={state}
      error={error}
      empty={payload?.status !== "ok"}
      emptyTitle="Model needs valid inputs"
      emptyBody={
        firstString(payload?.summary, "error") ??
        payload?.reason ??
        "Spot and strike must be positive numbers for the Black-Scholes pricer."
      }
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        {/* input strip — one compact row, unit folded into the label */}
        <section style={inputRowStyle} aria-label="Valuation inputs">
          <NumField
            label="Spot"
            value={spot}
            min={0.01}
            step={1}
            width={96}
            ariaLabel="Underlying spot price"
            onChange={setSpot}
          />
          <NumField
            label="Strike"
            value={strike}
            min={0.01}
            step={1}
            width={96}
            ariaLabel="Option strike price"
            onChange={setStrike}
          />
          <NumField
            label="T (y)"
            value={years}
            min={0.01}
            step={0.05}
            width={84}
            ariaLabel="Years to expiry"
            onChange={setYears}
          />
          <NumField
            label="Vol %"
            value={volPct}
            min={0.01}
            step={1}
            width={84}
            ariaLabel="Implied volatility percent"
            onChange={setVolPct}
          />
          <NumField
            label="Rate %"
            value={ratePct}
            step={0.25}
            width={84}
            ariaLabel="Risk-free rate percent"
            onChange={setRatePct}
          />
          <NumField
            label="Div %"
            value={divPct}
            min={0}
            step={0.25}
            width={84}
            ariaLabel="Dividend yield percent"
            onChange={setDivPct}
          />
        </section>

        {/* KPI strip — the four decision-relevant numbers */}
        <section style={kpiGridStyle} aria-label="Price and greeks">
          <StatCard
            label="Price"
            value={fmtNum(payload?.price, 3)}
            caption="per share"
            tone="neutral"
          />
          <StatCard
            label="Delta"
            value={fmtNum(payload?.delta, 4)}
            caption="per +1 spot"
            tone={deltaTone(payload?.delta)}
          />
          <StatCard
            label="Gamma"
            value={fmtNum(payload?.gamma, 4)}
            caption="per +1 delta"
            tone="neutral"
          />
          <StatCard
            label="Theta"
            value={fmtNum(payload?.theta, 4)}
            caption="per day"
            tone={thetaTone(payload?.theta)}
          />
        </section>

        {/* primary visual — value curve, vega/rho read inline */}
        <ValueChart
          curve={curve}
          spot={spot}
          strike={strike}
          optionType={type}
          vega={payload?.vega}
          rho={payload?.rho}
        />

        {/* secondary table — sensitivity curve with sort / keyboard / CSV */}
        <section aria-label="Sensitivity grid" style={tableWrapStyle}>
          <div style={tableHeadStyle}>
            <span className="u-text-mute" style={noteTextStyle}>
              sensitivity · every 5th point
            </span>
          </div>
          <DataGrid
            columns={gridColumns}
            rows={gridRows}
            rowKey={(r, i) => `${r.spot ?? i}-${i}`}
            density="compact"
            ariaLabel="Value sensitivity to spot"
            defaultSortKey="spot"
            defaultSortDir="ascending"
            keyboardNavigable
          />
        </section>
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Option Valuation"
          subtitle={`${type} ${fmtStrike(strike)} · ${moneyness}`}
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
              {/* R2-#10 (F4): CSV lives in the header slot like the rest of
                  the family, not inside the grid section. */}
              <button
                type="button"
                className="btn btn--ghost"
                onClick={exportCsv}
                disabled={gridRows.length === 0}
                title="Download CSV"
                aria-label={`Download ${gridRows.length} sensitivity rows as CSV`}
              >
                CSV
              </button>
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
          <StatusSection label="points" value={curve.length} tone="accent" />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── value curve (inline SVG, tokens only) ─────────────────────────── */

const CHART_W = 560;
// FIX R2-#9: vertical budget trim (was 150) so the sensitivity grid gains a
// row above the 900px fold.
const CHART_H = 120;
const CHART_PAD_X = 10;
const CHART_PAD_TOP = 10;
const CHART_PAD_BOTTOM = 16;

function ValueChart({
  curve,
  spot,
  strike,
  optionType,
  vega,
  rho,
}: {
  curve: SensitivityPoint[];
  spot: number;
  strike: number;
  optionType: string;
  vega?: number;
  rho?: number;
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
          Value vs spot
        </span>
        <span className="u-text-mute" style={noteTextStyle}>
          vega {fmtNum(vega, 4)} / vol pt · rho {fmtNum(rho, 4)} / rate pt
        </span>
      </div>
      <svg
        width="100%"
        height={CHART_H}
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        role="img"
        aria-label={`${optionType} value from spot ${fmtNum(geom.xMin)} to ${fmtNum(geom.xMax)}`}
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
        {/* model value — the only primary data series */}
        <path d={geom.valuePath} fill="none" stroke="var(--accent-2, var(--accent))" strokeWidth={1.5} />
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
            stroke="var(--text-primary)"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        )}
        <text
          x={CHART_PAD_X}
          y={CHART_H - 4}
          fontSize={9}
          fill="var(--text-mute)"
          fontFamily="JetBrains Mono, monospace"
        >
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
      {/* minimal two-entry key — the only two multi-series lines */}
      <div style={legendRowStyle}>
        <span style={legendItemStyle}>
          <svg width={18} height={6} aria-hidden>
            <line x1={0} x2={18} y1={3} y2={3} stroke="var(--accent-2, var(--accent))" strokeWidth={1.5} />
          </svg>
          Model value
        </span>
        <span style={legendItemStyle}>
          <svg width={18} height={6} aria-hidden>
            <line x1={0} x2={18} y1={3} y2={3} stroke="var(--text-mute)" strokeWidth={1} strokeDasharray="4 3" />
          </svg>
          Intrinsic
        </span>
      </div>
    </section>
  );
}

/* ── small input (kit Field wrapper with local text state) ─────────── */

function NumField({
  label,
  value,
  onChange,
  step = 1,
  min,
  width,
  ariaLabel,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  width?: number;
  ariaLabel: string;
}) {
  const [text, setText] = useState<string>(() => String(value));
  useEffect(() => {
    setText(String(value));
  }, [value]);
  return (
    <Field
      label={label}
      // FIX R2-#3: `type="number"` renders with the OS locale separator
      // (tr-TR "0,25"); text + dot value + inputMode pins en-US formatting.
      type="text"
      inputMode="decimal"
      value={text}
      step={step}
      min={min}
      width={width}
      aria-label={ariaLabel}
      onChange={(e) => {
        setText(e.target.value);
        const n = Number(e.target.value);
        if (e.target.value.trim() !== "" && Number.isFinite(n) && (min == null || n >= min)) {
          onChange(n);
        }
      }}
      onBlur={() => setText(String(value))}
    />
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function num(v: unknown): number | null {
  // GUARD: Number(null) === 0 — an absent value must stay missing (em-dash),
  // never collapse into a fabricated zero.
  if (v == null || v === "") return null;
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
  return formatNumberFixed(n, digits);
}

/** Header strike: grouping with at most 2 decimals ("100", not "100.00"). */
function fmtStrike(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  return formatNumber(n, 2);
}

/* ── styles (design tokens only) ───────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 10,
};

const inputRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-end",
  gap: 10,
  overflowX: "auto",
  paddingBottom: 2,
};

const chartCardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  // FIX R2-#9: trimmed from 10/12 to lift the primary grid above the fold.
  padding: "8px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  background: "var(--scrim-low)",
};

const chartHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 12,
  flexWrap: "wrap",
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
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  fontFamily: "var(--font-mono)",
};

const tableWrapStyle: CSSProperties = { minWidth: 0 };

const tableHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 12,
  marginBottom: 6,
};

const noteTextStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  fontFamily: "var(--font-mono)",
  letterSpacing: "0.05em",
};

const monoStyle: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};
