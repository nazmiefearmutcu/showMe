/**
 * FXH — FX Hedge (forward overlay calculator).
 *
 * Hedge book from live-spot forward overlays: per-currency exposures with
 * hedged/unhedged notional, locked-in carry P&L and residual P&L under
 * home-currency shocks, plus the backend's 5-point ±10% scenario curve.
 * Header: pair + HEDGE ratio / HORIZON / SHOCK knobs (all persisted).
 * The scenario ladder itself is the backend's fixed ±10% set — the SHOCK
 * knob sizes the headline strengthen/weaken cards (noted inline).
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
import { formatNumberFixed } from "@/lib/format";
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

interface FXHRow {
  currency?: string;
  home_currency?: string;
  notional_foreign?: number;
  spot_rate?: number;
  forward_rate?: number;
  home_value_now?: number;
  hedge_ratio?: number;
  hedged_notional_foreign?: number;
  unhedged_notional_foreign?: number;
  days_to_maturity?: number;
  carry_pnl_home?: number;
  scenario_usd_strengthens_pct?: number;
  pnl_if_home_strengthens?: number;
  pnl_if_home_weakens?: number;
}

interface FXHCurvePoint {
  shock_pct?: number;
  total_pnl?: number;
  unhedged_pnl?: number;
}

interface FXHData {
  status?: string;
  reason?: string;
  rows?: FXHRow[];
  exposures?: FXHRow[];
  curve?: FXHCurvePoint[];
  total_carry_pnl?: number;
  total_home_value?: number;
  total_pnl_if_home_strengthens?: number;
  total_pnl_if_home_weakens?: number;
  hedge_ratio?: number;
  days_to_maturity?: number;
  source_mode?: string;
  methodology?: string;
}

const PAIR_OPTIONS = [
  { value: "EURUSD", label: "EURUSD", title: "PAIR EURUSD" },
  { value: "USDJPY", label: "USDJPY", title: "PAIR USDJPY" },
  { value: "GBPUSD", label: "GBPUSD", title: "PAIR GBPUSD" },
  { value: "AUDUSD", label: "AUDUSD", title: "PAIR AUDUSD" },
] as const;

type PairId = (typeof PAIR_OPTIONS)[number]["value"];
const PAIR_IDS = PAIR_OPTIONS.map((o) => o.value);

const RATIO_OPTIONS = [
  { value: 0.25, label: "25%", title: "HEDGE 25%" },
  { value: 0.5, label: "50%", title: "HEDGE 50%" },
  { value: 0.75, label: "75%", title: "HEDGE 75%" },
  { value: 1, label: "100%", title: "HEDGE 100%" },
] as const;

const DAYS_OPTIONS = [
  { value: 30, label: "30d", title: "HORIZON 30d" },
  { value: 60, label: "60d", title: "HORIZON 60d" },
  { value: 90, label: "90d", title: "HORIZON 90d" },
  { value: 180, label: "180d", title: "HORIZON 180d" },
] as const;

const SHOCK_OPTIONS = [
  { value: 0.02, label: "±2%", title: "SHOCK ±2%" },
  { value: 0.05, label: "±5%", title: "SHOCK ±5%" },
  { value: 0.1, label: "±10%", title: "SHOCK ±10%" },
] as const;

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

export function FXHPane({ code, symbol }: FunctionPaneProps) {
  const [pair, setPair] = usePersistentOption<PairId>(
    "showme.fxh.pair",
    PAIR_IDS,
    "EURUSD",
  );
  const [ratio, setRatio] = usePersistentNumber("showme.fxh.ratio", 0.75);
  const [days, setDays] = usePersistentNumber("showme.fxh.days", 90);
  const [shock, setShock] = usePersistentNumber("showme.fxh.shock", 0.05);

  // An explicit FX pair symbol (navigation intent) beats the stored pick.
  const effectivePair = normalizePair(symbol) ?? pair;
  const { state, data, error, refetch } = useFunction<FXHData>({
    code,
    symbol: effectivePair,
    params: {
      pair: effectivePair,
      hedge_ratio: ratio,
      days,
      usd_shock_pct: shock,
    },
  });

  const payload = data?.data;
  const warnings = data?.warnings ?? [];
  const rows = useMemo(
    () => payload?.rows ?? payload?.exposures ?? [],
    [payload],
  );
  const curve = useMemo(() => payload?.curve ?? [], [payload]);
  const isLive = payload?.source_mode === "live_yfinance_quote";
  const noData =
    state === "ok" &&
    (payload?.status === "data_unavailable" || rows.length === 0);

  const COLS: DataGridColumn<FXHRow>[] = useMemo(
    () => [
      {
        key: "currency",
        header: "Ccy",
        width: 72,
        render: (r) => (
          <span style={monoStrongStyle}>{r.currency ?? "—"}</span>
        ),
      },
      {
        key: "notional_foreign",
        header: "Notional",
        numeric: true,
        width: 116,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtNum(r.notional_foreign)}</span>
        ),
      },
      {
        key: "spot_rate",
        header: "Spot",
        numeric: true,
        width: 104,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtRate(r.spot_rate)}</span>
        ),
      },
      {
        key: "forward_rate",
        header: "Forward",
        numeric: true,
        width: 108,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtRate(r.forward_rate)}</span>
        ),
      },
      {
        key: "hedged",
        header: "Hedged",
        numeric: true,
        width: 116,
        render: (r) => (
          <span style={monoMutedStyle}>
            {fmtNum(r.hedged_notional_foreign)}
          </span>
        ),
      },
      {
        key: "unhedged",
        header: "Unhedged",
        numeric: true,
        width: 116,
        render: (r) => (
          <span style={monoMutedStyle}>
            {fmtNum(r.unhedged_notional_foreign)}
          </span>
        ),
      },
      {
        key: "carry_pnl_home",
        header: "Carry P&L",
        numeric: true,
        width: 122,
        render: (r) => (
          <span
            style={{
              ...monoStrongStyle,
              color: pnlColor(r.carry_pnl_home),
            }}
          >
            {fmtMoney(r.carry_pnl_home, true)}
          </span>
        ),
      },
      {
        key: "pnl_weak",
        header: `P&L home +${fmtShock(shock)}`,
        numeric: true,
        width: 132,
        render: (r) => (
          <span
            style={{
              ...monoPrimaryStyle,
              color: pnlColor(r.pnl_if_home_weakens),
            }}
          >
            {fmtMoney(r.pnl_if_home_weakens, true)}
          </span>
        ),
      },
      {
        key: "pnl_strong",
        header: `P&L home −${fmtShock(shock)}`,
        numeric: true,
        width: 132,
        render: (r) => (
          <span
            style={{
              ...monoPrimaryStyle,
              color: pnlColor(r.pnl_if_home_strengthens),
            }}
          >
            {fmtMoney(r.pnl_if_home_strengthens, true)}
          </span>
        ),
      },
    ],
    [shock],
  );

  const geom = useMemo(() => buildCurve(curve), [curve]);

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
    ) : noData ? (
      <div className="u-grid-gap-14">
        {warningBanner}
        <Empty
          title="Hedge book unavailable"
          body={
            payload?.reason ??
            "No exposure has a usable spot rate — FXH refuses to invent notionals."
          }
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
        <section style={kpiGridStyle} aria-label="FXH KPI ribbon">
          <StatCard
            label="Home value"
            value={fmtMoney(payload?.total_home_value, false)}
            caption={`${rows.length} CCY · ${fmtNum(payload?.hedge_ratio != null ? payload.hedge_ratio * 100 : null, 0)}% HEDGED`}
            tone="neutral"
          />
          <StatCard
            label="Carry P&L"
            value={fmtMoney(payload?.total_carry_pnl, true)}
            caption={`${days}D FORWARD OVERLAY`}
            tone={pnlTone(payload?.total_carry_pnl)}
          />
          <StatCard
            label={`If home −${fmtShock(shock)}%`}
            value={fmtMoney(payload?.total_pnl_if_home_strengthens, true)}
            caption="RESIDUAL + CARRY"
            tone={pnlTone(payload?.total_pnl_if_home_strengthens)}
          />
          <StatCard
            label={`If home +${fmtShock(shock)}%`}
            value={fmtMoney(payload?.total_pnl_if_home_weakens, true)}
            caption="RESIDUAL + CARRY"
            tone={pnlTone(payload?.total_pnl_if_home_weakens)}
          />
        </section>
        <figure
          style={curveStyle}
          role="img"
          aria-label={`FXH scenario curve: total hedged P&L versus unhedged P&L across a ±10% home-currency shock ladder`}
        >
          <svg
            viewBox={`0 0 ${CURVE_W} ${CURVE_H}`}
            preserveAspectRatio="none"
            style={svgStyle}
            aria-hidden="true"
          >
            {geom.zeroY != null ? (
              <line
                x1={0}
                x2={CURVE_W}
                y1={geom.zeroY}
                y2={geom.zeroY}
                stroke="var(--text-mute)"
                strokeWidth={1}
              />
            ) : null}
            {geom.unhedgedPoints.length > 1 ? (
              <polyline
                points={geom.unhedgedPoints
                  .map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`)
                  .join(" ")}
                fill="none"
                stroke="var(--text-mute)"
                strokeDasharray="4 3"
                strokeWidth={1.2}
              />
            ) : null}
            {geom.totalPoints.length > 1 ? (
              <polyline
                points={geom.totalPoints
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
              <span aria-hidden="true" style={swatchAccentStyle} /> hedged total
            </span>
            <span style={legendRowStyle}>
              <span aria-hidden="true" style={swatchSpotStyle} /> unhedged
            </span>
            <span style={legendRowStyle}>
              shock ladder −10% → +10% (backend fixed set; SHOCK knob sizes the
              cards)
            </span>
          </figcaption>
        </figure>
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.currency ?? "ccy"}-${i}`}
          density="compact"
          ariaLabel="FXH hedge book"
        />
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`FX Hedge — ${effectivePair}`}
          subtitle={`${rows.length} exposure${rows.length === 1 ? "" : "s"} · ${days}d forward overlay`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live spot" : payload?.source_mode ?? "—"}
              </Pill>
              <SegmentedControl
                label="PAIR"
                value={effectivePair}
                options={PAIR_OPTIONS}
                onChange={setPair}
              />
              <SegmentedControl
                label="HEDGE"
                value={ratio}
                options={RATIO_OPTIONS}
                onChange={setRatio}
              />
              <SegmentedControl
                label="HORIZON"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
              />
              <SegmentedControl
                label="SHOCK"
                value={shock}
                options={SHOCK_OPTIONS}
                onChange={setShock}
              />
              <LoadStatePill state={state} status={payload?.status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh hedge book"
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
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="hedge"
            value={`${Math.round(ratio * 100)}% · ${days}d`}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

interface CurveGeom {
  totalPoints: Array<[number, number]>;
  unhedgedPoints: Array<[number, number]>;
  zeroY: number | null;
}

function buildCurve(points: FXHCurvePoint[]): CurveGeom {
  const totals = points
    .map((p) => p.total_pnl)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const unhedged = points
    .map((p) => p.unhedged_pnl)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (totals.length < 2) {
    return { totalPoints: [], unhedgedPoints: [], zeroY: null };
  }
  const all = [...totals, ...unhedged, 0];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const yOf = (v: number) =>
    CURVE_H - 8 - ((v - (min - span * 0.12)) / (span * 1.24)) * (CURVE_H - 16);
  const step = CURVE_W / (points.length - 1);
  const totalPoints = points.map((p, i) => [
    i * step,
    yOf(typeof p.total_pnl === "number" ? p.total_pnl : 0),
  ] as [number, number]);
  const unhedgedPoints = points.map((p, i) => [
    i * step,
    yOf(typeof p.unhedged_pnl === "number" ? p.unhedged_pnl : 0),
  ] as [number, number]);
  return { totalPoints, unhedgedPoints, zeroY: yOf(0) };
}

function pnlColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-mute)";
  return v >= 0 ? "var(--positive)" : "var(--negative)";
}

function pnlTone(v: number | null | undefined): "positive" | "negative" {
  return (v ?? 0) >= 0 ? "positive" : "negative";
}

function fmtMoney(v: number | null | undefined, signed: boolean): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : signed ? "+" : "";
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(2)}K`;
  return `${sign}$${a.toFixed(2)}`;
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return formatNumberFixed(v, digits);
}

function fmtRate(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.abs(v) >= 100 ? v.toFixed(3) : v.toFixed(5);
}

function fmtShock(shock: number): string {
  const pct = shock * 100;
  return Number.isInteger(pct) ? String(pct) : pct.toFixed(1);
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
