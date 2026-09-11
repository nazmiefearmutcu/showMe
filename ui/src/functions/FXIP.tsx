/**
 * FXIP — FX Information Portal.
 *
 * Portal read for one currency pair: spot (with 90d-close trend), covered-
 * interest-parity forwards, reference policy rates, an explicit ATM vol
 * ASSUMPTION and annualized carry. The pair comes from the bound symbol or
 * a persisted major-pair picker (`showme.fxip.pair`); the history window is
 * `showme.fxip.days`. Data honesty: when the backend falls back to
 * `reference_model` the pane says the spot is a labelled reference level,
 * NOT a live quote, and surfaces provider warnings verbatim.
 */
import { useEffect, useMemo, type CSSProperties } from "react";
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
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface FXIPMetricRow {
  metric?: string;
  value?: number | string;
  unit?: string;
  source?: string;
}

interface FXIPHistoryRow {
  date?: string;
  close?: number;
}

interface FXIPData {
  status?: string;
  pair?: string;
  base?: string;
  quote?: string;
  spot?: number;
  daily_change_pct?: number;
  one_month_forward?: number;
  three_month_forward?: number;
  implied_vol_atm_1m?: number;
  carry_annualized?: number;
  source_mode?: string;
  rows?: FXIPMetricRow[];
  history?: FXIPHistoryRow[];
  methodology?: string;
}

const PAIR_OPTIONS = [
  { value: "EURUSD", label: "EURUSD" },
  { value: "USDJPY", label: "USDJPY" },
  { value: "GBPUSD", label: "GBPUSD" },
  { value: "USDCHF", label: "USDCHF" },
  { value: "AUDUSD", label: "AUDUSD" },
  { value: "USDCAD", label: "USDCAD" },
  { value: "NZDUSD", label: "NZDUSD" },
  { value: "EURGBP", label: "EURGBP" },
  { value: "EURJPY", label: "EURJPY" },
  { value: "EURCHF", label: "EURCHF" },
  { value: "GBPJPY", label: "GBPJPY" },
] as const;
const PAIR_IDS = PAIR_OPTIONS.map((o) => o.value);

const DAYS_OPTIONS = [
  { value: 30, label: "30d" },
  { value: 90, label: "90d" },
  { value: 180, label: "180d" },
] as const;
const DAYS_IDS = DAYS_OPTIONS.map((o) => o.value);

const REFRESH_MS = 30_000;

export function FXIPPane({ code, symbol }: FunctionPaneProps) {
  const [pair, setPair] = usePersistentOption<string>(
    "showme.fxip.pair",
    PAIR_IDS,
    "EURUSD",
  );
  const [days, setDays] = usePersistentOption<number>(
    "showme.fxip.days",
    DAYS_IDS,
    90,
  );
  const effectivePair = symbol || pair;
  // FX spot is quote-live: poll the portal on the visibility tick without
  // touching the fetch params (a changing key would re-key useFunction and
  // flash the skeleton on every poll — canonical TECH/GLCO pattern).
  const tick = useVisibilityTick(REFRESH_MS);
  const { state, data, error, refetch } = useFunction<FXIPData>({
    code,
    symbol: effectivePair,
    params: { days },
  });
  useEffect(() => {
    if (tick === 0) return;
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  const payload = data?.data;
  const status = payload?.status ?? "—";
  const sourceMode = payload?.source_mode ?? "—";
  const isLive = sourceMode.startsWith("live");
  const isReference = sourceMode === "reference_model";

  const trend = useMemo(() => {
    const closes = (payload?.history ?? [])
      .map((r) => (typeof r.close === "number" ? r.close : null))
      .filter((v): v is number => v != null && Number.isFinite(v));
    return closes.reverse();
  }, [payload]);

  const COLS: DataGridColumn<FXIPMetricRow>[] = useMemo(
    () => [
      {
        key: "metric",
        header: "Metric",
        width: 160,
        render: (r) => (
          <span style={monoStrongStyle}>{r.metric ?? "—"}</span>
        ),
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 140,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtRowValue(r)}</span>
        ),
      },
      {
        key: "unit",
        header: "Unit",
        width: 160,
        render: (r) => <span style={bodyStyle}>{r.unit ?? "—"}</span>,
      },
      {
        key: "source",
        header: "Source",
        width: 220,
        render: (r) =>
          r.source ? (
            <Pill
              tone={r.source.includes("reference") || r.source.includes("assumption") ? "muted" : "accent"}
              variant="soft"
              withDot={false}
            >
              {r.source}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const body = state === "loading" || state === "idle" ? (
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
  ) : !payload || (payload.rows ?? []).length === 0 ? (
    <Empty
      title="No portal payload"
      body="FXIP returned no metric rows for this pair — try another pair or retry."
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {isReference ? (
        <div role="note" style={warnStyle} aria-label="FXIP reference notice">
          <strong>Reference spot.</strong> Live spot is unavailable for{" "}
          {payload.pair ?? effectivePair} — the level shown is a labelled
          reference value, NOT a live quote. Forwards and carry computed from
          it are illustrative.
        </div>
      ) : null}
      <section style={kpiGridStyle} aria-label="FXIP portal summary">
        <StatCard
          label={`Spot ${payload.base ?? ""}/${payload.quote ?? ""}`}
          value={fmtRate(payload.spot)}
          caption={
            payload.daily_change_pct != null
              ? `${payload.daily_change_pct >= 0 ? "+" : ""}${payload.daily_change_pct.toFixed(3)}% DAILY`
              : "—"
          }
          tone={
            payload.daily_change_pct != null
              ? payload.daily_change_pct >= 0
                ? "positive"
                : "negative"
              : "neutral"
          }
          trend={trend.length > 1 ? trend : undefined}
        />
        <StatCard
          label="1M forward"
          value={fmtRate(payload.one_month_forward)}
          caption="COVERED INTEREST PARITY"
          tone="neutral"
        />
        <StatCard
          label="3M forward"
          value={fmtRate(payload.three_month_forward)}
          caption="COVERED INTEREST PARITY"
          tone="neutral"
        />
        <StatCard
          label="ATM vol 1M"
          value={fmtPct(payload.implied_vol_atm_1m)}
          caption="ASSUMPTION — NOT A QUOTE"
          tone="neutral"
        />
        <StatCard
          label="Carry (annualized)"
          value={fmtSignedPct((payload.carry_annualized ?? 0) * 100)}
          caption="QUOTE RATE − BASE RATE"
          tone={
            (payload.carry_annualized ?? 0) >= 0 ? "positive" : "negative"
          }
        />
      </section>
      <div>
        <div style={gridTitleStyle}>
          portal metrics · {payload.pair ?? effectivePair}
        </div>
        <DataGrid
          columns={COLS}
          rows={payload.rows ?? []}
          rowKey={(r, i) => `${r.metric ?? "m"}-${i}`}
          density="compact"
          ariaLabel="FXIP portal metrics"
        />
      </div>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`FX Info Portal — ${effectivePair}`}
          subtitle={`${payload?.pair ?? effectivePair} · ${isLive ? "live spot" : "reference spot"}`}
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={isLive ? "positive" : "warn"}
                variant="soft"
                withDot={false}
              >
                {sourceMode}
              </Pill>
              {!symbol ? (
                <SegmentedControl
                  label="PAIR"
                  value={pair}
                  options={PAIR_OPTIONS}
                  onChange={setPair}
                  title="Currency pair"
                />
              ) : null}
              <SegmentedControl
                label="DAYS"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
                title="History window"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh FX portal"
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
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="mode" value={sourceMode} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="days" value={days} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function fmtRate(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.abs(v) >= 20 ? v.toFixed(3) : v.toFixed(4);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(3)}%`;
}

function fmtSignedPct(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(3)}%`;
}

/**
 * Rate-unit rows ship decimals (0.045 base rate, 0.01 carry) while the KPI
 * ribbon shows the same inputs as percents. Render decimal-annual rows in
 * percent units so the table and the cards agree; the carry is signed like
 * the KPI (quote rate − base rate).
 */
function fmtRowValue(r: FXIPMetricRow): string {
  const v = r.value;
  if (typeof v === "string") return v;
  if (v == null || !Number.isFinite(v)) return "—";
  if (r.unit === "decimal annual") {
    const pct = v * 100;
    if (r.metric === "carry_annualized") {
      return `${pct >= 0 ? "+" : ""}${pct.toFixed(3)}%`;
    }
    return `${pct.toFixed(3)}%`;
  }
  return String(v);
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const gridTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.05em",
  marginBottom: 6,
};

const warnStyle: CSSProperties = {
  border: "1px solid var(--negative, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
};

const bodyStyle: CSSProperties = {
  color: "var(--text-primary)",
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
