/**
 * YAS — Yield & Spread Analytics.
 *
 * Bond analytics: the backend solves YTM (Newton + bisection fallback) and
 * derives Macaulay/modified duration, convexity and spread vs benchmark,
 * plus a ±100bp shock-price ladder.
 *
 * 2026-11-07 (strict truth audit): the pane used to send a fixed demo bond
 * (price 99.5, coupon 4.25%, 10y, benchmark 4.45%) on every request, so a
 * US2Y and a US10Y showed identical numbers. Price / coupon / maturity /
 * benchmark are now optional overrides (empty = not sent): generic US
 * Treasury tenors (US1M…US30Y) are analysed from the live FRED
 * constant-maturity yield, other bonds need their own price, coupon and
 * maturity, and the inputs stay visible when the backend asks for them.
 * Overrides reset when the bond changes; only the coupon frequency persists.
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
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
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
  as_of?: string;
}

interface YASData {
  status?: string;
  reason?: string;
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

const DEFAULT_BOND = "US10Y";

/** Generic US Treasury tenor the backend prices from the live CMT yield. */
export function isGenericTreasury(bond: string): boolean {
  return /^US(1M|3M|6M|1Y|2Y|3Y|5Y|7Y|10Y|20Y|30Y)$/.test(bond);
}

export function YASPane({ code, symbol }: FunctionPaneProps) {
  const [price, setPrice] = useState<number | null>(null);
  const [couponPct, setCouponPct] = useState<number | null>(null);
  const [maturity, setMaturity] = useState<number | null>(null);
  const [benchmarkPct, setBenchmarkPct] = useState<number | null>(null);
  const [freq, setFreq] = usePersistentOption<number>(
    "showme.yas.freq",
    FREQ_IDS,
    2,
  );
  const [bond, setBondRaw] = useState(() => cleanBond(symbol) ?? DEFAULT_BOND);
  const setBond = (next: string) => {
    if (next === bond) return;
    // Overrides describe one specific bond; never carry them to another.
    setPrice(null);
    setCouponPct(null);
    setMaturity(null);
    setBenchmarkPct(null);
    setBondRaw(next);
  };

  const params = useMemo(() => {
    // YAS only ever prices bonds. The pane owns the asset class: without it the
    // sidecar infers one from the symbol, and a CUSIP-style id falls through to
    // EQUITY and is refused as unsupported_asset.
    const out: Record<string, string | number> = { asset_class: "BOND", freq };
    if (price != null) out.price = price;
    if (couponPct != null) out.coupon = pctToDecimal(couponPct);
    if (maturity != null) out.maturity_years = maturity;
    if (benchmarkPct != null) out.benchmark_rate = pctToDecimal(benchmarkPct);
    return out;
  }, [price, couponPct, maturity, benchmarkPct, freq]);

  const { state, data, error, refetch } = useFunction<YASData>({
    code,
    symbol: bond,
    params,
  });

  const payload = data?.data;
  const summary = payload?.summary;
  const curve = useMemo(() => payload?.curve ?? [], [payload]);
  const overridden = price != null || couponPct != null || maturity != null;
  const liveCmt =
    !overridden && (data?.sources ?? []).includes("fred") && isGenericTreasury(bond);
  const blocked =
    payload?.status === "input_error" ||
    payload?.status === "provider_unavailable" ||
    payload?.status === "unsupported_asset";

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

  // CSV export of the ±100bp shock ladder — RAW payload numbers plus the
  // Δ-vs-now column computed against the summary price.
  const csvColumns = useMemo<GridCsvColumn<YASShockPoint>[]>(
    () => [
      { key: "shock_bps", header: "Shock bp", value: (r) => r.shock_bps ?? "" },
      { key: "ytm_pct", header: "YTM %", value: (r) => r.ytm_pct ?? "" },
      { key: "price", header: "Price", value: (r) => r.price ?? "" },
      {
        key: "delta_vs_now",
        header: "Δ vs now",
        value: (r) =>
          typeof r.price === "number" && summary?.price != null
            ? r.price - summary.price
            : "",
      },
    ],
    [summary],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, curve);
    downloadGridCsv(gridCsvFilename(`yas-${bond}`), csv);
  };

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
    ) : blocked ? (
      <Empty
        title={blockedTitle(payload?.status)}
        body={payload?.reason ?? "—"}
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
            caption="2ND-ORDER · YEARS²"
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
          subtitle={`${summary?.maturity_years ?? maturity ?? "—"}y · coupon ${fmtFixed(summary?.coupon_pct ?? couponPct, 2)}% · ${freq}x/yr${summary?.as_of ? ` · CMT ${summary.as_of}` : ""}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={liveCmt ? "positive" : "muted"} variant="soft" withDot={false}>
                {liveCmt ? "live CMT" : "model"}
              </Pill>
              <SegmentedControl
                label="FREQ"
                value={freq}
                options={FREQ_OPTIONS}
                onChange={setFreq}
              />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={curve.length === 0}
                title="Download CSV"
                aria-label={`Download ${curve.length} shock ladder rows as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={payload?.status ?? null} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Recompute analytics"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-grid-gap-14">
            <section style={inputsRowStyle} aria-label="YAS bond inputs">
              <BondField value={bond} onCommit={setBond} />
              <NumField
                label="PRICE"
                ariaLabel="Price (per 100 face)"
                value={price}
                placeholder={summary?.price}
                onCommit={setPrice}
                step={0.5}
                min={0.01}
              />
              <NumField
                label="COUPON %"
                ariaLabel="Coupon percent"
                value={couponPct}
                placeholder={summary?.coupon_pct}
                onCommit={setCouponPct}
                step={0.25}
                min={0}
              />
              <NumField
                label="MATURITY Y"
                ariaLabel="Maturity years"
                value={maturity}
                placeholder={summary?.maturity_years}
                onCommit={setMaturity}
                step={1}
                min={0.1}
              />
              <NumField
                label="BENCHMARK %"
                ariaLabel="Benchmark percent"
                value={benchmarkPct}
                placeholder={summary?.benchmark_pct}
                onCommit={setBenchmarkPct}
                step={0.25}
                min={0}
              />
            </section>
            {body}
          </div>
        </PaneBody>
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

function blockedTitle(status: string | undefined): string {
  if (status === "input_error") return "Bond inputs needed";
  if (status === "unsupported_asset") return "Asset not supported";
  return "Live yield unavailable";
}

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

/** Optional override: empty means "not sent" (the backend's live value is
 * shown as the placeholder). */
function NumField({
  label,
  ariaLabel,
  value,
  placeholder,
  onCommit,
  step,
  min,
}: {
  label: string;
  ariaLabel: string;
  value: number | null;
  placeholder?: number;
  onCommit: (next: number | null) => void;
  step: number;
  min: number;
}) {
  const text = value == null ? "" : String(value);
  const [draft, setDraft] = useState(text);
  useEffect(() => {
    setDraft(text);
  }, [text]);
  return (
    <label style={fieldRowStyle}>
      <span style={fieldLabelStyle}>{label}</span>
      <input
        type="number"
        aria-label={ariaLabel}
        value={draft}
        placeholder={
          placeholder != null && Number.isFinite(placeholder)
            ? String(Number(placeholder.toFixed(4)))
            : "—"
        }
        step={step}
        min={min}
        onChange={(e) => {
          setDraft(e.target.value);
          if (e.target.value.trim() === "") {
            onCommit(null);
            return;
          }
          const n = Number(e.target.value);
          if (Number.isFinite(n) && n >= min) {
            onCommit(n);
          }
        }}
        onBlur={() => setDraft(text)}
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
