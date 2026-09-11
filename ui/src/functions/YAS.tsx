/**
 * YAS — Yield & Spread Analytics.
 *
 * Instant closed-form bond analytics: the backend solves YTM (Newton +
 * bisection fallback) and derives Macaulay/modified duration, convexity
 * and spread vs benchmark, plus a ±100bp shock-price ladder. The pane is
 * fully interactive: bond identity, price, coupon %, maturity, benchmark
 * % (persisted under `showme.yas.*`) and coupon frequency drive the
 * model; headline cards + shock ladder re-compute on every change. All
 * numbers are model outputs from user inputs — the footer says so.
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
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import {
  usePersistentNumber,
  usePersistentOption,
} from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface YASMetricRow {
  metric?: string;
  value?: number;
  display_pct?: number;
  spread_bps?: number;
  unit?: string;
}

interface YASShockPoint {
  ytm_pct?: number;
  price?: number;
  shock_bps?: number;
}

interface YASSummary {
  bond?: string;
  price?: number;
  face?: number;
  coupon_rate?: number;
  coupon_pct?: number;
  maturity_years?: number;
  frequency?: number;
  benchmark_rate?: number;
  benchmark_pct?: number;
  ytm?: number;
  ytm_pct?: number;
  spread_vs_benchmark?: number;
  spread_bps?: number;
}

interface YASData {
  status?: string;
  rows?: YASMetricRow[];
  curve?: YASShockPoint[];
  summary?: YASSummary;
  methodology?: string;
}

const FREQ_OPTIONS = [
  { value: 1, label: "1x", title: "FREQ 1x" },
  { value: 2, label: "2x", title: "FREQ 2x" },
  { value: 4, label: "4x", title: "FREQ 4x" },
] as const;
const FREQ_IDS = FREQ_OPTIONS.map((o) => o.value);

const DEFAULT_PRICE = 99.5;
const DEFAULT_COUPON_PCT = 4.25;
const DEFAULT_MATURITY = 10;
const DEFAULT_BENCHMARK_PCT = 4.45;
const DEFAULT_BOND = "US10Y";

export function YASPane({ code, symbol }: FunctionPaneProps) {
  const [price, setPrice] = usePersistentNumber("showme.yas.price", DEFAULT_PRICE);
  const [couponPct, setCouponPct] = usePersistentNumber(
    "showme.yas.coupon",
    DEFAULT_COUPON_PCT,
  );
  const [maturity, setMaturity] = usePersistentNumber(
    "showme.yas.maturity",
    DEFAULT_MATURITY,
  );
  const [benchmarkPct, setBenchmarkPct] = usePersistentNumber(
    "showme.yas.benchmark",
    DEFAULT_BENCHMARK_PCT,
  );
  const [freq, setFreq] = usePersistentOption<number>(
    "showme.yas.freq",
    FREQ_IDS,
    2,
  );
  const [bond, setBond] = useState(() => cleanBond(symbol) ?? DEFAULT_BOND);

  const { state, data, error, refetch } = useFunction<YASData>({
    code,
    symbol: bond,
    params: {
      price,
      coupon: pctToDecimal(couponPct),
      maturity_years: maturity,
      freq,
      benchmark_rate: pctToDecimal(benchmarkPct),
    },
  });

  const payload = data?.data;
  const summary = payload?.summary;
  const curve = useMemo(() => payload?.curve ?? [], [payload]);

  const stats = useMemo(() => {
    const macaulay = payload?.rows?.find(
      (r) => r.metric === "macaulay_duration",
    )?.value;
    const modified = payload?.rows?.find(
      (r) => r.metric === "modified_duration",
    )?.value;
    const convexity = payload?.rows?.find(
      (r) => r.metric === "convexity",
    )?.value;
    return { macaulay, modified, convexity };
  }, [payload]);

  const COLS: DataGridColumn<YASShockPoint>[] = useMemo(
    () => [
      {
        key: "shock_bps",
        header: "Shock bp",
        numeric: true,
        width: 104,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtSignedInt(r.shock_bps)}</span>
        ),
      },
      {
        key: "ytm_pct",
        header: "YTM %",
        numeric: true,
        width: 112,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtFixed(r.ytm_pct, 3)}%</span>
        ),
      },
      {
        key: "price",
        header: "Price",
        numeric: true,
        width: 112,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtFixed(r.price, 3)}</span>
        ),
      },
      {
        key: "delta",
        header: "Δ vs now",
        numeric: true,
        width: 112,
        render: (r) => {
          const delta =
            typeof r.price === "number" && summary?.price != null
              ? r.price - summary.price
              : null;
          return (
            <span
              style={{
                ...monoStrongStyle,
                color: deltaColor(delta),
              }}
            >
              {fmtSignedFixed(delta, 3)}
            </span>
          );
        },
      },
    ],
    [summary],
  );

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={56} />
        <Skeleton height={20} />
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
    ) : curve.length === 0 ? (
      <Empty
        title="No analytics returned"
        body="The yield model came back empty — check the bond inputs."
        icon="∅"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <section
          style={inputsRowStyle}
          aria-label="YAS bond inputs"
        >
          <BondField value={bond} onCommit={setBond} />
          <NumField
            label="PRICE"
            ariaLabel="Price (per 100 face)"
            value={price}
            onCommit={setPrice}
            step={0.5}
            min={0.01}
          />
          <NumField
            label="COUPON %"
            ariaLabel="Coupon percent"
            value={couponPct}
            onCommit={setCouponPct}
            step={0.25}
            min={0}
          />
          <NumField
            label="MATURITY Y"
            ariaLabel="Maturity years"
            value={maturity}
            onCommit={setMaturity}
            step={1}
            min={0.1}
          />
          <NumField
            label="BENCHMARK %"
            ariaLabel="Benchmark percent"
            value={benchmarkPct}
            onCommit={setBenchmarkPct}
            step={0.25}
            min={0}
          />
        </section>
        <section style={kpiGridStyle} aria-label="YAS KPI ribbon">
          <StatCard
            label="YTM"
            value={`${fmtFixed(summary?.ytm_pct, 3)}%`}
            caption={`BOND ${summary?.bond ?? bond} @ ${fmtFixed(summary?.price, 2)}`}
            tone="neutral"
          />
          <StatCard
            label="Spread vs bench"
            value={`${fmtSignedFixed(summary?.spread_bps, 1)} bps`}
            caption={`BENCH ${fmtFixed(summary?.benchmark_pct, 2)}%`}
            tone={spreadTone(summary?.spread_bps)}
          />
          <StatCard
            label="Mod duration"
            value={`${fmtFixed(stats.modified, 2)}y`}
            caption={`MACAULAY ${fmtFixed(stats.macaulay, 2)}y`}
            tone="neutral"
          />
          <StatCard
            label="Convexity"
            value={fmtFixed(stats.convexity, 1)}
            caption="2ND-ORDER PRICE SENS."
            tone="neutral"
          />
        </section>
        <div>
          <div style={ladderTitleStyle}>±100bp shock ladder (duration + convexity)</div>
          <DataGrid
            columns={COLS}
            rows={curve}
            rowKey={(r, i) => `${r.shock_bps ?? "bp"}-${i}`}
            density="compact"
            ariaLabel="YAS shock price ladder"
          />
        </div>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Yield & Spread — ${summary?.bond ?? bond}`}
          subtitle={`${summary?.maturity_years ?? maturity}y · coupon ${fmtFixed(summary?.coupon_pct ?? couponPct, 2)}% · ${freq}x/yr`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                model
              </Pill>
              <SegmentedControl
                label="FREQ"
                value={freq}
                options={FREQ_OPTIONS}
                onChange={setFreq}
              />
              <LoadStatePill state={state} status={payload?.status ?? null} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Recompute analytics"
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
          <StatusSection label="status" value={payload?.status ?? state} />
          <StatusDivider />
          <StatusSection label="ladder" value={`${curve.length} pts`} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="bond" value={bond} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── input fields ──────────────────────────────────────────────────── */

function cleanBond(raw: string | undefined): string | null {
  const value = (raw ?? "").trim().toUpperCase();
  return /^[A-Z0-9.-]{1,20}$/.test(value) ? value : null;
}

function BondField({
  value,
  onCommit,
}: {
  value: string;
  onCommit: (next: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => {
    setDraft(value);
  }, [value]);
  return (
    <label style={fieldRowStyle}>
      <span style={fieldLabelStyle}>BOND</span>
      <input
        type="text"
        aria-label="Bond symbol"
        value={draft}
        spellCheck={false}
        onChange={(e) => {
          setDraft(e.target.value);
          const cleaned = cleanBond(e.target.value);
          if (cleaned) onCommit(cleaned);
        }}
        onBlur={() => setDraft(value)}
        style={{ ...numInputStyle, width: 96 }}
      />
    </label>
  );
}

function NumField({
  label,
  ariaLabel,
  value,
  onCommit,
  step,
  min,
}: {
  label: string;
  ariaLabel: string;
  value: number;
  onCommit: (next: number) => void;
  step: number;
  min: number;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => {
    setDraft(String(value));
  }, [value]);
  return (
    <label style={fieldRowStyle}>
      <span style={fieldLabelStyle}>{label}</span>
      <input
        type="number"
        aria-label={ariaLabel}
        value={draft}
        step={step}
        min={min}
        onChange={(e) => {
          setDraft(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value.trim() !== "" && Number.isFinite(n) && n >= min) {
            onCommit(n);
          }
        }}
        onBlur={() => setDraft(String(value))}
        style={numInputStyle}
      />
    </label>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

/** Percent input → annual decimal, rounded to 1e-6 (4.45 → 0.0445). */
function pctToDecimal(pct: number): number {
  return Math.round((pct / 100) * 1e6) / 1e6;
}

function deltaColor(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-mute)";
  return v >= 0 ? "var(--positive)" : "var(--negative)";
}

function spreadTone(v: number | null | undefined): "positive" | "negative" | "neutral" {
  if (v == null || !Number.isFinite(v) || v === 0) return "neutral";
  return v > 0 ? "negative" : "positive";
}

function fmtFixed(v: number | null | undefined, digits: number): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function fmtSignedFixed(v: number | null | undefined, digits: number): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

function fmtSignedInt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return String(v > 0 ? `+${v}` : v);
}

/* ── styles ────────────────────────────────────────────────────────── */

const inputsRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 12,
  alignItems: "flex-end",
};

const fieldRowStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 3,
};

const fieldLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
};

const numInputStyle: CSSProperties = {
  width: 76,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-sm)",
  padding: "2px 4px",
  border: "1px solid var(--border-row)",
  borderRadius: 3,
  background: "var(--surface-1)",
  color: "var(--text-primary)",
};

const ladderTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.05em",
  marginBottom: 6,
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
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
