/**
 * OSA — Option Strategy Analysis (multi-leg builder).
 *
 * Fully client-parameterised model pane: the legs editor (buy/sell,
 * call/put, strike, expiry, IV, quantity) drives the backend Black-Scholes
 * strategy analyzer, which returns per-leg solved premiums and a 101-point
 * expiration payoff/PnL curve. Legs persist under `showme.osa.legs`, spot /
 * rate under `showme.osa.*`.
 *
 * Data honesty: the strategy is a MODEL (sources=black_scholes_formula),
 * never a market feed — the header pill states "model", not "live".
 * Max gain / loss are computed over the VISIBLE price grid, and the stats
 * strip says so. The request omits the symbol entirely (the backend
 * rejects EQUITY-class instruments for this derivative function).
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
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
import { formatNumber } from "@/lib/format";
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
  spot?: number;
  rate?: number;
  strategy?: string;
  rows?: OsaLegRow[];
  legs?: OsaLegRow[];
  curve?: OsaCurvePoint[];
  pnl_curve?: OsaCurvePoint[];
  summary?: OsaSummary;
  methodology?: string;
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

  const { state, data, error, refetch } = useFunction<OsaData>({
    code,
    params: {
      asset_class: "DERIVATIVE",
      spot,
      rate: rate / 100,
      legs: legs.map((l) => ({ ...l })),
    },
  });

  const payload = data?.data;
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

  const premiumFor = (idx: number): number | null => num(legRows[idx]?.premium);

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8" aria-busy="true">
      <Skeleton height={56} />
      <Skeleton height={120} />
      <Skeleton height={20} width="70%" />
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
  ) : payload?.status !== "ok" || curve.length < 2 ? (
    <Empty
      title="Strategy could not be priced"
      body="Check the legs — every strike, expiry and IV must be positive."
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {/* stats strip */}
      <section style={kpiGridStyle} aria-label="Strategy statistics">
        <StatCard
          label="Net debit"
          value={fmtSigned(netDebit)}
          caption={netDebit != null && netDebit < 0 ? "CREDIT RECEIVED" : "PAID UP FRONT"}
          tone={netDebit != null && netDebit < 0 ? "positive" : "neutral"}
        />
        <StatCard
          label="Max gain (grid)"
          value={fmtSigned(maxGain)}
          caption="VISIBLE PRICE RANGE"
          tone={maxGain != null && maxGain > 0 ? "positive" : "neutral"}
        />
        <StatCard
          label="Max loss (grid)"
          value={fmtSigned(maxLoss)}
          caption="VISIBLE PRICE RANGE"
          tone={maxLoss != null && maxLoss < 0 ? "negative" : "neutral"}
        />
        <StatCard
          label="Breakevens"
          value={String(summary?.breakeven_count_visible ?? breakevens.length)}
          caption={breakevens.length ? breakevens.map((b) => fmtNum(b, 1)).join(" / ") : "NONE IN RANGE"}
          tone="neutral"
        />
      </section>

      {/* payoff / P&L chart */}
      <PayoffChart
        curve={curve}
        breakevens={breakevens}
        spot={spot}
        netDebit={netDebit}
      />

      {/* legs editor */}
      <section aria-label="Strategy legs editor" style={tableWrapStyle}>
        <table style={tableStyle} aria-label="Legs">
          <thead>
            <tr>
              {["Side", "Type", "Strike", "Expiry (y)", "IV", "Premium", ""].map((h, i) => (
                <th key={h + i} style={{ ...thStyle, textAlign: i >= 2 && i <= 5 ? "right" : "left" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {legs.map((leg, idx) => {
              const long = leg.qty >= 0;
              return (
                <tr key={idx} aria-label={`Leg ${idx + 1}: ${long ? "buy" : "sell"} ${leg.type} ${fmtNum(leg.strike)}`}>
                  <td style={tdStyle}>
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
                  </td>
                  <td style={tdStyle}>
                    <MiniToggle
                      ariaLabel={`Leg ${idx + 1} type`}
                      options={[
                        { value: "CALL", label: "C" },
                        { value: "PUT", label: "P" },
                      ]}
                      value={leg.type}
                      onChange={(v) => patchLeg(idx, { type: v as OsaLeg["type"] })}
                    />
                  </td>
                  <td style={tdNumStyle}>
                    <NumInput
                      value={leg.strike}
                      step={1}
                      min={0.01}
                      ariaLabel={`Leg ${idx + 1} strike`}
                      onChange={(v) => patchLeg(idx, { strike: v })}
                    />
                  </td>
                  <td style={tdNumStyle}>
                    <NumInput
                      value={leg.expiry}
                      step={0.05}
                      min={0.01}
                      ariaLabel={`Leg ${idx + 1} expiry years`}
                      onChange={(v) => patchLeg(idx, { expiry: v })}
                    />
                  </td>
                  <td style={tdNumStyle}>
                    <NumInput
                      value={leg.vol}
                      step={0.05}
                      min={0.01}
                      ariaLabel={`Leg ${idx + 1} implied volatility decimal`}
                      onChange={(v) => patchLeg(idx, { vol: v })}
                    />
                  </td>
                  <td style={tdNumStyle}>
                    <span style={monoStrongStyle}>{fmtNum(premiumFor(idx))}</span>
                  </td>
                  <td style={tdStyle}>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      title={`Remove leg ${idx + 1}`}
                      aria-label={`Remove leg ${idx + 1}`}
                      disabled={legs.length <= 1}
                      onClick={() => removeLeg(idx)}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div style={editorNoteStyle}>
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
            quantity per leg = ±1 step · premium priced at spot {fmtNum(spot)} · IV solved
            per leg by the model
          </span>
        </div>
      </section>

      {/* spot / rate inputs */}
      <section
        style={inputRowStyle}
        aria-label="Underlying assumptions"
      >
        <label style={inputLabelStyle}>
          <span className="u-text-mute">SPOT</span>
          <NumInput value={spot} step={1} min={0.01} ariaLabel="Underlying spot price" onChange={setSpot} />
        </label>
        <label style={inputLabelStyle}>
          <span className="u-text-mute">RATE %</span>
          <NumInput value={rate} step={0.25} ariaLabel="Risk-free rate percent" onChange={setRate} />
        </label>
        <span className="u-text-mute" style={noteTextStyle}>
          premiums reprice on every change
        </span>
      </section>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Option Strategy Analyzer${payload?.strategy ? ` — ${String(payload.strategy).replace(/_/g, " ").toUpperCase()}` : ""}`}
          subtitle={`${legs.length} leg${legs.length === 1 ? "" : "s"} · spot ${fmtNum(spot)} · net debit ${fmtSigned(netDebit)}`}
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
          <StatusSection label="legs" value={legs.length} tone="accent" />
          <StatusDivider />
          <StatusSection label="grid" value={`${curve.length} pt`} />
          <StatusDivider />
          <StatusSection label="rate" value={`${fmtNum(rate)}%`} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── payoff / P&L chart (inline SVG, tokens only) ──────────────────── */

const CHART_W = 560;
const CHART_H = 150;
const CHART_PAD_X = 10;
const CHART_PAD_TOP = 10;
const CHART_PAD_BOTTOM = 16;

function PayoffChart({
  curve,
  breakevens,
  spot,
  netDebit,
}: {
  curve: OsaCurvePoint[];
  breakevens: number[];
  spot: number;
  netDebit: number | null;
}) {
  const geom = useMemo(() => {
    const xs: number[] = [];
    const pnl: number[] = [];
    const payoff: number[] = [];
    for (const p of curve) {
      const x = num(p.spot);
      const a = num(p.pnl);
      const b = num(p.payoff);
      if (x == null || a == null || b == null) continue;
      xs.push(x);
      pnl.push(a);
      payoff.push(b);
    }
    if (xs.length < 2) return null;
    let lo = 0;
    let hi = 0;
    for (const v of [...pnl, ...payoff]) {
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
      xs,
      pnl,
      payoff,
      px,
      py,
      zeroY: py(0),
      pnlPath: path(pnl),
      payoffPath: path(payoff),
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

  return (
    <section style={chartCardStyle} aria-label="Expiration payoff and P&L chart">
      <div style={chartHeadStyle}>
        <span className="u-text-mute" style={noteTextStyle}>
          EXPIRY PAYOFF / P&L · {geom.xs.length} PTS
        </span>
        <span className="u-text-mute" style={noteTextStyle}>
          {netDebit != null && netDebit < 0 ? "credit strategy" : "debit strategy"}
        </span>
      </div>
      <svg
        width="100%"
        height={CHART_H}
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        role="img"
        aria-label={`Expiration payoff and P&L from ${fmtNum(geom.xMin)} to ${fmtNum(geom.xMax)}, ${breakevens.length} breakeven point${breakevens.length === 1 ? "" : "s"}`}
        preserveAspectRatio="none"
      >
        {/* zero P&L baseline */}
        <line
          x1={CHART_PAD_X}
          x2={CHART_W - CHART_PAD_X}
          y1={geom.zeroY}
          y2={geom.zeroY}
          stroke="var(--border-subtle)"
          strokeWidth={1}
        />
        {/* payoff at expiry (muted, dashed) */}
        <path
          d={geom.payoffPath}
          fill="none"
          stroke="var(--text-mute)"
          strokeWidth={1}
          strokeDasharray="4 3"
        />
        {/* P&L (accent) */}
        <path d={geom.pnlPath} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
        {/* breakeven markers */}
        {breakevens.map((b) => (
          <circle
            key={b}
            cx={geom.px(b)}
            cy={geom.zeroY}
            r={3.5}
            fill="var(--bg)"
            stroke="var(--accent)"
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
            stroke="var(--positive)"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        )}
        {/* axis hints */}
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
          P&L at expiry
        </span>
        <span style={legendItemStyle}>
          <svg width={18} height={6} aria-hidden>
            <line x1={0} x2={18} y1={3} y2={3} stroke="var(--text-mute)" strokeWidth={1} strokeDasharray="4 3" />
          </svg>
          Payoff
        </span>
        <span style={legendItemStyle}>
          <svg width={10} height={8} aria-hidden>
            <circle cx={5} cy={4} r={3} fill="var(--bg)" stroke="var(--accent)" strokeWidth={1.5} />
          </svg>
          Breakeven
        </span>
        <span style={legendItemStyle}>
          <svg width={10} height={8} aria-hidden>
            <line x1={5} x2={5} y1={0} y2={8} stroke="var(--positive)" strokeWidth={1} strokeDasharray="3 3" />
          </svg>
          Spot
        </span>
      </div>
    </section>
  );
}

/* ── small inputs ──────────────────────────────────────────────────── */

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
      type="number"
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

function fmtNum(v: number | null | undefined, digits = 2): string {
  const n = num(v);
  if (n == null) return "—";
  return formatNumber(n, digits);
}

function fmtSigned(v: number | null | undefined): string {
  const n = num(v);
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
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
  fontSize: "var(--font-size-2xs)",
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
  fontSize: "var(--font-size-sm)",
};

const thStyle: CSSProperties = {
  padding: "4px 8px",
  color: "var(--text-mute)",
  fontWeight: 500,
  letterSpacing: "0.06em",
  fontSize: "var(--font-size-xs)",
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

const editorNoteStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  marginTop: 6,
};

const noteTextStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.05em",
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
  fontSize: "var(--font-size-xs)",
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
  fontSize: "var(--font-size-sm)",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const miniToggleStyle: CSSProperties = {
  display: "inline-flex",
  gap: 2,
};

const miniToggleBtnStyle: CSSProperties = {
  padding: "1px 6px",
  fontSize: "var(--font-size-2xs)",
};
