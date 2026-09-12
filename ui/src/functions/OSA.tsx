/**
 * OSA — Option Strategy Analyzer (multi-leg payoff desk).
 *
 * Recreated 2026-09-11 (options-family redesign, lane L4). One screen, one
 * job: a compact leg editor drives the backend Black-Scholes strategy
 * analyzer, the payoff SVG is the primary visual, and a payoff-at-key-prices
 * DataGrid carries sort / keyboard / CSV.
 *
 * Data honesty: the strategy is a MODEL (sources=black_scholes_formula),
 * never a market feed — the header carries the single "model" pill. Leg
 * premiums are priced at the entered per-leg IV (never "solved"); max
 * gain/loss are read over the visible expiry grid; a missing summary value
 * renders as an em-dash, never a fabricated number.
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
import { usePersistentNumber } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

/* ── model types ───────────────────────────────────────────────────── */

interface OsaLeg {
  qty: number; // signed: positive = long, negative = short
  strike: number;
  type: "CALL" | "PUT";
  expiry: number; // years
  vol: number; // decimal IV
}

interface OsaLegRow {
  leg?: number;
  qty?: number;
  type?: string;
  strike?: number;
  expiry_years?: number;
  vol?: number;
  iv_source?: string;
  premium?: number;
  initial_value?: number;
}

interface OsaCurvePoint {
  spot?: number;
  pnl?: number;
  payoff?: number;
  net_debit?: number;
  pv_debit?: number;
}

interface OsaSummary {
  net_debit?: number;
  max_gain_visible?: number;
  max_loss_visible?: number;
  breakeven_count_visible?: number;
}

interface OsaData {
  status?: string;
  reason?: string;
  spot?: number;
  rate?: number;
  div_yield?: number;
  strategy?: string;
  rows?: OsaLegRow[];
  legs?: OsaLegRow[];
  curve?: OsaCurvePoint[];
  pnl_curve?: OsaCurvePoint[];
  summary?: OsaSummary;
}

interface PayoffRow {
  spot: number;
  payoff: number | null;
  pnl: number | null;
}

/* ── strategy presets + persistence ────────────────────────────────── */

const LEGS_KEY = "showme.osa.legs";
const PRESET_KEY = "showme.osa.preset";
const MAX_LEGS = 4;

const PRESETS: ReadonlyArray<{ id: string; label: string; legs: OsaLeg[] }> = [
  {
    id: "bullCall",
    label: "BULL CALL",
    legs: [
      { qty: 1, strike: 100, type: "CALL", expiry: 0.25, vol: 0.25 },
      { qty: -1, strike: 110, type: "CALL", expiry: 0.25, vol: 0.25 },
    ],
  },
  {
    id: "bearPut",
    label: "BEAR PUT",
    legs: [
      { qty: 1, strike: 110, type: "PUT", expiry: 0.25, vol: 0.25 },
      { qty: -1, strike: 100, type: "PUT", expiry: 0.25, vol: 0.25 },
    ],
  },
  {
    id: "straddle",
    label: "STRADDLE",
    legs: [
      { qty: 1, strike: 100, type: "CALL", expiry: 0.25, vol: 0.25 },
      { qty: 1, strike: 100, type: "PUT", expiry: 0.25, vol: 0.25 },
    ],
  },
  {
    id: "strangle",
    label: "STRANGLE",
    legs: [
      { qty: 1, strike: 90, type: "PUT", expiry: 0.25, vol: 0.25 },
      { qty: 1, strike: 110, type: "CALL", expiry: 0.25, vol: 0.25 },
    ],
  },
  {
    id: "condor",
    label: "IRON CONDOR",
    legs: [
      { qty: 1, strike: 80, type: "PUT", expiry: 0.25, vol: 0.25 },
      { qty: -1, strike: 90, type: "PUT", expiry: 0.25, vol: 0.25 },
      { qty: -1, strike: 110, type: "CALL", expiry: 0.25, vol: 0.25 },
      { qty: 1, strike: 120, type: "CALL", expiry: 0.25, vol: 0.25 },
    ],
  },
];
const PRESET_IDS: readonly string[] = PRESETS.map((p) => p.id);

function sanitizeLeg(raw: unknown): OsaLeg | null {
  if (typeof raw !== "object" || raw === null) return null;
  const rec = raw as Record<string, unknown>;
  const num = (v: unknown, fallback: number): number => {
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? n : fallback;
  };
  const type = String(rec.type ?? "CALL").toUpperCase() === "PUT" ? "PUT" : "CALL";
  return {
    qty: num(rec.qty, 1),
    strike: num(rec.strike, 100),
    type,
    expiry: Math.max(0.01, num(rec.expiry, 0.25)),
    vol: Math.max(0.01, num(rec.vol, 0.25)),
  };
}

function readStoredLegs(key: string): OsaLeg[] {
  const fallback = PRESETS[0].legs;
  if (typeof localStorage === "undefined") return fallback;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return fallback;
    const legs = parsed
      .slice(0, MAX_LEGS)
      .map(sanitizeLeg)
      .filter((l): l is OsaLeg => l !== null);
    return legs.length ? legs : fallback;
  } catch {
    return fallback;
  }
}

/** Persisted legs array. Stored as JSON so the whole strategy survives reloads. */
function usePersistentLegs(key: string): [OsaLeg[], (next: OsaLeg[]) => void] {
  const [legs, setLegs] = useState<OsaLeg[]>(() => readStoredLegs(key));
  const update = (next: OsaLeg[]) => {
    const clamped = next.slice(0, MAX_LEGS);
    setLegs(clamped);
    try {
      localStorage.setItem(key, JSON.stringify(clamped));
    } catch {
      /* storage unavailable — session-only strategy */
    }
  };
  return [legs, update];
}

function readStoredPreset(key: string): string {
  if (typeof localStorage === "undefined") return PRESETS[0].id;
  const raw = localStorage.getItem(key);
  return raw && PRESET_IDS.includes(raw) ? raw : PRESETS[0].id;
}

/* ── pane ──────────────────────────────────────────────────────────── */

export function OSAPane({ code }: FunctionPaneProps) {
  const [legs, setLegs] = usePersistentLegs(LEGS_KEY);
  const [spot, setSpot] = usePersistentNumber("showme.osa.spot", 100);
  const [rate, setRate] = usePersistentNumber("showme.osa.rate", 4.5); // percent
  const [divPct, setDivPct] = usePersistentNumber("showme.osa.div", 0); // percent
  const [preset, setPreset] = useState<string>(() => readStoredPreset(PRESET_KEY));

  const applyPreset = (id: string) => {
    const found = PRESETS.find((p) => p.id === id);
    if (!found) return;
    setLegs(found.legs.map((l) => ({ ...l })));
    setPreset(id);
    try {
      localStorage.setItem(PRESET_KEY, id);
    } catch {
      /* session-only */
    }
  };

  const patchLeg = (idx: number, patch: Partial<OsaLeg>) => {
    setLegs(legs.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
    setPreset("custom");
  };

  const addLeg = () => {
    if (legs.length >= MAX_LEGS) return;
    setLegs([...legs, { qty: 1, strike: spot, type: "CALL", expiry: 0.25, vol: 0.25 }]);
    setPreset("custom");
  };

  const removeLeg = (idx: number) => {
    if (legs.length <= 1) return;
    setLegs(legs.filter((_, i) => i !== idx));
    setPreset("custom");
  };

  // The backend echoes the `strategy` label; sending it keeps the header
  // honest (otherwise the runner's CALL_SPREAD default is echoed even for a
  // straddle / condor).
  const presetLabel = PRESETS.find((p) => p.id === preset)?.label ?? "CUSTOM";
  const { state, data, error, refetch } = useFunction<OsaData>({
    code,
    params: {
      asset_class: "DERIVATIVE",
      spot,
      rate: rate / 100,
      div_yield: divPct / 100,
      strategy: presetLabel,
      legs: legs.map((l) => ({ ...l })),
    },
  });

  const payload = data?.data;
  const isOk = state !== "loading" && state !== "idle" && payload?.status === "ok";
  const curve: OsaCurvePoint[] = useMemo(
    () => (payload?.curve && payload.curve.length ? payload.curve : payload?.pnl_curve ?? []),
    [payload],
  );
  const legRows: OsaLegRow[] = useMemo(() => payload?.rows ?? payload?.legs ?? [], [payload]);
  const summary = payload?.status === "ok" ? payload.summary : undefined;
  const breakevens = useMemo(() => computeBreakevens(curve), [curve]);
  const netDebit = num(summary?.net_debit);
  const maxGain = num(summary?.max_gain_visible);
  const maxLoss = num(summary?.max_loss_visible);

  const profileRows = useMemo(
    () =>
      keyPriceRows(
        curve,
        breakevens,
        legs.map((l) => l.strike),
        spot,
      ),
    [curve, breakevens, legs, spot],
  );

  const gridColumns = useMemo<DataGridColumn<PayoffRow>[]>(
    () => [
      {
        key: "spot",
        header: "Spot",
        width: 96,
        numeric: true,
        sortable: true,
        render: (r) => <span style={monoStrongStyle}>{formatNumberFixed(r.spot, 2)}</span>,
      },
      {
        key: "payoff",
        header: "Payoff at expiry",
        width: 128,
        numeric: true,
        sortable: true,
        render: (r) => <span style={monoStyle}>{fmtSigned(r.payoff)}</span>,
      },
      {
        key: "pnl",
        header: "P&L",
        width: 110,
        numeric: true,
        sortable: true,
        render: (r) => (
          <span
            style={{
              ...monoStrongStyle,
              color:
                r.pnl == null
                  ? "var(--text-mute)"
                  : r.pnl >= 0
                    ? "var(--positive)"
                    : "var(--negative)",
            }}
          >
            {fmtSigned(r.pnl)}
          </span>
        ),
      },
    ],
    [],
  );

  const csvColumns = useMemo<GridCsvColumn<PayoffRow>[]>(
    () => [
      { key: "spot", header: "Spot", value: (r) => r.spot },
      { key: "payoff", header: "Payoff at expiry", value: (r) => r.payoff ?? "" },
      { key: "pnl", header: "P&L", value: (r) => r.pnl ?? "" },
    ],
    [],
  );

  const exportCsv = () => {
    downloadGridCsv(
      gridCsvFilename("osa-payoff"),
      buildGridCsv(csvColumns, profileRows),
    );
  };

  const strategyEcho =
    payload?.status === "ok" && payload.strategy ? String(payload.strategy) : null;
  const strategyLabel = (strategyEcho ?? presetLabel).replace(/_/g, " ").toUpperCase();

  const body = (
    <PaneState
      state={state}
      error={error}
      empty={!isOk}
      emptyTitle="Strategy could not be priced"
      emptyBody={
        payload?.reason ??
        "Check the legs — every strike, expiry and IV must be positive, and the backend must return at least two curve points."
      }
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        {/* KPI strip — net debit / bounds / breakevens */}
        <section style={kpiGridStyle} aria-label="Strategy statistics">
          <StatCard
            label="Net debit"
            value={fmtSigned(netDebit)}
            caption={netDebit == null ? undefined : netDebit < 0 ? "credit received" : "paid up front"}
            tone={netDebit != null && netDebit < 0 ? "positive" : "neutral"}
          />
          <StatCard
            label="Max gain"
            value={fmtSigned(maxGain)}
            caption={maxGain == null ? undefined : "at range high"}
            tone={maxGain != null && maxGain > 0 ? "positive" : "neutral"}
          />
          <StatCard
            label="Max loss"
            value={fmtSigned(maxLoss)}
            caption={maxLoss == null ? undefined : "at range low"}
            tone={maxLoss != null && maxLoss < 0 ? "negative" : "neutral"}
          />
          <StatCard
            label="Breakevens"
            value={String(summary?.breakeven_count_visible ?? breakevens.length)}
            caption={breakevens.length ? breakevens.map((b) => fmtNum(b, 2)).join(" / ") : "none in range"}
            tone="neutral"
          />
        </section>

        {/* primary visual — expiration P&L profile */}
        <PayoffChart curve={curve} breakevens={breakevens} spot={spot} />

        {/* compact leg editor — one row set, kit input density */}
        <section aria-label="Strategy legs editor" style={editorWrapStyle}>
          <div style={{ ...editorGridStyle, ...editorHeadStyle }} aria-hidden="true">
            <span>SIDE</span>
            <span>TYPE</span>
            <span>STRIKE</span>
            <span>EXP Y</span>
            <span>IV</span>
            <span>QTY</span>
            <span style={editorNumHeadStyle}>PREMIUM</span>
            <span />
          </div>
          {legs.map((leg, idx) => {
            const long = leg.qty >= 0;
            return (
              <div
                key={idx}
                role="group"
                aria-label={`Leg ${idx + 1}: ${long ? "buy" : "sell"} ${leg.type} ${fmtNum(leg.strike)}`}
                style={{ ...editorGridStyle, ...editorRowStyle }}
              >
                <MiniToggle
                  ariaLabel={`Leg ${idx + 1} side`}
                  options={[
                    { value: "B", label: "BUY" },
                    { value: "S", label: "SELL" },
                  ]}
                  value={long ? "B" : "S"}
                  onChange={(v) => {
                    const mag = Math.abs(leg.qty) || 1;
                    patchLeg(idx, { qty: v === "B" ? mag : -mag });
                  }}
                />
                <MiniToggle
                  ariaLabel={`Leg ${idx + 1} type`}
                  options={[
                    { value: "CALL", label: "C" },
                    { value: "PUT", label: "P" },
                  ]}
                  value={leg.type}
                  onChange={(v) => patchLeg(idx, { type: v as OsaLeg["type"] })}
                />
                <NumInput
                  value={leg.strike}
                  step={1}
                  min={0.01}
                  ariaLabel={`Leg ${idx + 1} strike`}
                  onChange={(v) => patchLeg(idx, { strike: v })}
                />
                <NumInput
                  value={leg.expiry}
                  step={0.05}
                  min={0.01}
                  ariaLabel={`Leg ${idx + 1} expiry years`}
                  onChange={(v) => patchLeg(idx, { expiry: v })}
                />
                <NumInput
                  value={leg.vol}
                  step={0.05}
                  min={0.01}
                  ariaLabel={`Leg ${idx + 1} implied volatility decimal`}
                  onChange={(v) => patchLeg(idx, { vol: v })}
                />
                <NumInput
                  value={Math.abs(leg.qty) || 1}
                  step={1}
                  min={1}
                  ariaLabel={`Leg ${idx + 1} quantity`}
                  onChange={(v) => patchLeg(idx, { qty: Math.round(v) * (long ? 1 : -1) })}
                />
                <span style={premiumStyle}>{fmtNum(legRows[idx]?.premium)}</span>
                <button
                  type="button"
                  className="btn btn--ghost"
                  title={`Remove leg ${idx + 1}`}
                  aria-label={`Remove leg ${idx + 1}`}
                  disabled={legs.length <= 1}
                  onClick={() => removeLeg(idx)}
                  style={removeBtnStyle}
                >
                  ✕
                </button>
              </div>
            );
          })}
          <div style={editorFootStyle}>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={addLeg}
              disabled={legs.length >= MAX_LEGS}
              title="Add a leg (max 4)"
            >
              + Add leg
            </button>
            <span className="u-text-mute" style={noteTextStyle}>
              premium = Black-Scholes at current spot · IV per leg is the entered value (default
              0.25)
            </span>
          </div>
        </section>

        {/* model assumptions — single compact row, kit Field inputs */}
        <section style={assumptionRowStyle} aria-label="Model assumptions">
          <NumField
            label="Spot"
            value={spot}
            min={0.01}
            step={1}
            width={104}
            ariaLabel="Underlying spot price"
            onChange={setSpot}
          />
          <NumField
            label="Rate %"
            value={rate}
            step={0.25}
            width={92}
            ariaLabel="Risk-free rate percent"
            onChange={setRate}
          />
          <NumField
            label="Div %"
            value={divPct}
            min={0}
            step={0.25}
            width={92}
            ariaLabel="Dividend yield percent"
            onChange={setDivPct}
          />
        </section>

        {/* secondary table — expiry P&L at the decision-relevant prices */}
        <section aria-label="Expiry P&L at key prices" style={tableWrapStyle}>
          <div style={tableHeadStyle}>
            <span className="u-text-mute" style={noteTextStyle}>
              key prices · {profileRows.length} rows
            </span>
          </div>
          <DataGrid
            columns={gridColumns}
            rows={profileRows}
            rowKey={(r) => r.spot}
            density="compact"
            ariaLabel="Expiry P&L at key prices"
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
          title={`Option Strategy Analyzer — ${strategyLabel}`}
          subtitle={`${legs.length} leg${legs.length === 1 ? "" : "s"} · spot ${fmtNum(spot)}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                model
              </Pill>
              <SegmentedControl
                label="STRATEGY"
                value={preset}
                options={PRESETS.map((p) => ({ value: p.id, label: p.label }))}
                onChange={applyPreset}
                title="Strategy preset"
              />
              {/* R2-#10 (F4): CSV lives in the header slot like the rest of
                  the family, not inside the grid section. */}
              <button
                type="button"
                className="btn btn--ghost"
                onClick={exportCsv}
                disabled={profileRows.length === 0}
                title="Download CSV"
                aria-label={`Download ${profileRows.length} payoff rows as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={payload?.status} />
              <RefreshButton loading={state === "loading"} onClick={refetch} title="Reprice strategy" />
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

/* ── payoff chart (inline SVG, tokens only) ─────────────────────────── */

const CHART_W = 560;
// FIX R2-#9: vertical budget trim (was 150) so the primary grid gains a row
// above the 900px fold; 120px still reads as the payoff curve.
const CHART_H = 120;
const CHART_PAD_X = 10;
const CHART_PAD_TOP = 10;
const CHART_PAD_BOTTOM = 16;

function PayoffChart({
  curve,
  breakevens,
  spot,
}: {
  curve: OsaCurvePoint[];
  breakevens: number[];
  spot: number;
}) {
  const geom = useMemo(() => {
    const xs: number[] = [];
    const pnl: number[] = [];
    for (const p of curve) {
      const x = num(p.spot);
      const y = num(p.pnl);
      if (x == null || y == null) continue;
      xs.push(x);
      pnl.push(y);
    }
    if (xs.length < 2) return null;
    let lo = 0;
    let hi = 0;
    for (const v of pnl) {
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
    const path = pnl
      .map((v, i) => `${i === 0 ? "M" : "L"}${px(xs[i]).toFixed(1)},${py(v).toFixed(1)}`)
      .join(" ");
    return { px, py, path, xMin, xMax, zeroY: py(0) };
  }, [curve]);

  if (!geom) {
    return (
      <div className="u-text-mute" style={noteTextStyle}>
        Curve data unavailable for chart.
      </div>
    );
  }

  const spotX = spot >= geom.xMin && spot <= geom.xMax ? geom.px(spot) : null;

  return (
    <section style={chartCardStyle} aria-label="Expiration payoff chart">
      <span className="u-text-mute" style={noteTextStyle}>
        Expiration P&amp;L · visible grid
      </span>
      <svg
        width="100%"
        height={CHART_H}
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        role="img"
        aria-label={`Expiration P&L from spot ${fmtNum(geom.xMin)} to ${fmtNum(geom.xMax)} with ${breakevens.length} breakeven marker${breakevens.length === 1 ? "" : "s"}`}
        preserveAspectRatio="none"
      >
        {/* zero P&L line — structural reference */}
        <line
          x1={CHART_PAD_X}
          x2={CHART_W - CHART_PAD_X}
          y1={geom.zeroY}
          y2={geom.zeroY}
          stroke="var(--border-strong)"
          strokeWidth={1}
        />
        {/* P&L at expiry — the only data series */}
        <path d={geom.path} fill="none" stroke="var(--accent-2, var(--accent))" strokeWidth={1.5} />
        {/* breakeven markers, in-line on the zero line */}
        {breakevens.map((b) => (
          <circle
            key={b}
            cx={geom.px(b)}
            cy={geom.zeroY}
            r={3}
            fill="var(--bg)"
            stroke="var(--accent-2, var(--accent))"
            strokeWidth={1.5}
          />
        ))}
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
        {/* axis hints */}
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
    </section>
  );
}

/* ── small inputs (kit Field for the strip, dense inputs for the matrix) ── */

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
      // FIX R2-#3: `type="number"` renders the value with the OS locale
      // decimal separator (tr-TR "0,25"); a text input with a dot-decimal
      // value + `inputMode="decimal"` pins en-US formatting.
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
  const [text, setText] = useState<string>(() => String(value));
  useEffect(() => {
    setText(String(value));
  }, [value]);
  return (
    <input
      // FIX R2-#3: en-US dot decimals (see NumField note).
      type="text"
      inputMode="decimal"
      className="fn-num-input"
      style={numInputStyle}
      value={text}
      step={step}
      min={min}
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

function MiniToggle({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  onChange: (v: string) => void;
  ariaLabel: string;
}) {
  return (
    <span role="group" aria-label={ariaLabel} style={miniToggleStyle}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          disabled={value === o.value}
          onClick={() => onChange(o.value)}
          title={o.label}
          className={`fn-segmented__opt${value === o.value ? " fn-segmented__opt--active" : ""}`}
          style={miniToggleBtnStyle}
        >
          {o.label}
        </button>
      ))}
    </span>
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

/** Zero crossings of the P&L curve, linearly interpolated. */
function computeBreakevens(curve: OsaCurvePoint[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < curve.length; i += 1) {
    const y1 = num(curve[i - 1]?.pnl);
    const y2 = num(curve[i]?.pnl);
    const x1 = num(curve[i - 1]?.spot);
    const x2 = num(curve[i]?.spot);
    if (y1 == null || y2 == null || x1 == null || x2 == null) continue;
    if ((y1 <= 0 && y2 >= 0) || (y1 >= 0 && y2 <= 0)) {
      const denom = Math.abs(y1) + Math.abs(y2);
      const t = denom === 0 ? 0 : Math.abs(y1) / denom;
      out.push(x1 + (x2 - x1) * t);
    }
  }
  return out;
}

/**
 * The decision-relevant slice of the 101-point wire curve: the endpoints,
 * the current spot, every strike and every breakeven — each snapped to its
 * nearest wire curve point (no interpolation beyond what the backend sent).
 */
function keyPriceRows(
  curve: OsaCurvePoint[],
  breakevens: number[],
  strikes: number[],
  spot: number,
): PayoffRow[] {
  const points: PayoffRow[] = [];
  for (const p of curve) {
    const s = num(p.spot);
    if (s == null) continue;
    points.push({ spot: s, payoff: num(p.payoff), pnl: num(p.pnl) });
  }
  if (points.length < 2) return [];
  const targets = [points[0].spot, points[points.length - 1].spot, spot, ...strikes, ...breakevens];
  const picked = new Set<number>();
  for (const t of targets) {
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < points.length; i += 1) {
      const d = Math.abs(points[i].spot - t);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    }
    picked.add(best);
  }
  return [...picked].sort((a, b) => a - b).map((i) => points[i]);
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  const n = num(v);
  if (n == null) return "—";
  return formatNumber(n, digits);
}

function fmtSigned(v: number | null | undefined, digits = 2): string {
  const n = num(v);
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${formatNumberFixed(n, digits)}`;
}

/* ── styles (design tokens only) ───────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
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

const editorWrapStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  overflowX: "auto",
  minWidth: 0,
};

const EDITOR_COLS = "64px 52px minmax(64px,1fr) minmax(58px,1fr) minmax(54px,1fr) 48px 76px 22px";

const editorGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: EDITOR_COLS,
  gap: 6,
  alignItems: "center",
  minWidth: 470,
};

// Labels are written already-uppercase on purpose: no new
// `text-transform` site (the lang=tr uppercase defect is a central fix).
const editorHeadStyle: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "var(--tracking-label)",
  color: "var(--text-mute)",
  padding: "0 2px",
};

const editorNumHeadStyle: CSSProperties = { textAlign: "right" };

const editorRowStyle: CSSProperties = {
  padding: "2px 0",
  borderBottom: "1px solid var(--border-subtle)",
};

const editorFootStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  flexWrap: "wrap",
  marginTop: 4,
};

const tableWrapStyle: CSSProperties = { minWidth: 0 };

const tableHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 12,
  marginBottom: 6,
};

const assumptionRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-end",
  gap: 10,
};

const numInputStyle: CSSProperties = {
  width: "100%",
  minWidth: 0,
  padding: "3px 6px",
  background: "var(--bg-elev-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-sm)",
  outline: "none",
};

const premiumStyle: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
  fontWeight: 600,
  fontSize: "var(--font-size-sm)",
  textAlign: "right",
};

const removeBtnStyle: CSSProperties = {
  height: 20,
  minWidth: 0,
  padding: "0 6px",
  lineHeight: "20px",
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

const miniToggleStyle: CSSProperties = {
  display: "inline-flex",
  gap: 2,
};

const miniToggleBtnStyle: CSSProperties = {
  padding: "1px 5px",
  fontSize: "var(--font-size-2xs)",
  height: 20,
  minWidth: 0,
};
