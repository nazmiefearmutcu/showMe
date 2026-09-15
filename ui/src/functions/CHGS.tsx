/**
 * CHGS — Chart Studies (preset TECH bundle).
 *
 * The chart itself is rendered by the in-house showMe chart engine
 * (`@/chart/Chart`), which owns the timeframe/type pickers, the searchable
 * indicator picker (RSI/ATR/ADX included), zoom/pan and theming. CHGS keeps
 * the function payload (`days`) that feeds the summary cards, the per-study
 * latest-values table and the footer — the backend request keeps its full
 * default study set (no UI chip row), so the table stays populated.
 *
 * Backend (engine/functions/misc/_bonus.py CHGSFunction) defers to the live
 * TECH studies by default; the labelled synthetic `_chart_template` branch is
 * now opt-in (`reference=true`) and stamps `status:"reference"` +
 * `data_mode:"modeled"`. The pane renders the TECH payload honestly:
 *
 *  - a genuine failure envelope (`provider_unavailable` / `no_price_history`)
 *    renders an honest outage Empty with the backend `reason` + Retry — it is
 *    NEVER labelled "synthetic template";
 *  - the synthetic template label fires only for the real template shape
 *    (`data_mode === "modeled"` / `status === "reference"`).
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
import { defaultSymbolForFunction } from "@/lib/symbols";
import { SymbolBar } from "@/shell/SymbolBar";
import { Chart } from "@/chart/Chart";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface StudyPoint {
  time?: string;
  value?: number | null;
}

interface CHGSBar {
  date?: string;
  close?: number | null;
}

interface CHGSIndicatorRow {
  indicator?: string;
  value?: number;
  period?: string | number;
  formula?: string;
}

interface CHGSData {
  status?: string;
  data_mode?: string;
  reason?: string;
  next_actions?: string[];
  bar_count?: number;
  bars?: CHGSBar[];
  indicators?: Record<string, StudyPoint[]>;
  indicator_rows?: CHGSIndicatorRow[];
  summary?: {
    last_price?: number;
    rsi?: number;
    atr?: number;
    adx?: number;
    macd?: number;
    stoch_k?: number;
  };
  /* synthetic template shape (only behind reference=true) */
  symbol?: string;
  last?: number;
  rsi_14?: number;
  sma_20?: number;
  sma_50?: number;
}

const DAYS_OPTIONS = [
  { value: 90, label: "3m" },
  { value: 180, label: "6m" },
  { value: 365, label: "1y" },
] as const;
const DAYS_IDS = DAYS_OPTIONS.map((o) => o.value);

const STUDY_LABELS: Record<string, string> = {
  sma_20: "SMA 20",
  sma_50: "SMA 50",
  ema_20: "EMA 20",
  bb_upper: "BB upper",
  bb_mid: "BB mid",
  bb_lower: "BB lower",
  stoch_k: "Stoch %K",
  stoch_d: "Stoch %D",
  tenkan: "Tenkan",
  kijun: "Kijun",
  senkou_a: "Senkou A",
  senkou_b: "Senkou B",
  obv: "OBV",
};

function studyLabel(key: string): string {
  return STUDY_LABELS[key] ?? key;
}

const CHART_H = 380;

export function CHGSPane({ code, symbol }: FunctionPaneProps) {
  const [days, setDays] = usePersistentOption<number>(
    "showme.chgs.days",
    DAYS_IDS,
    180,
  );
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  // Default-polarity (2026-09-08): CHGS defers to the live TECH path with no
  // flag — the old `live_chart:true` param is inert and has been dropped.
  const { state, data, error, refetch } = useFunction<CHGSData>({
    code,
    symbol: effectiveSymbol,
    params: { days },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const warnings = Array.isArray(data?.warnings) ? data.warnings : [];
  const hasStudies = !!payload?.indicators;
  // The synthetic label is reserved for the genuine template mode — the
  // backend stamps `data_mode:"modeled"` + `status:"reference"` (legacy
  // template payloads carry the bespoke last/rsi_14 fields).
  const isSynthetic =
    !hasStudies &&
    (payload?.data_mode === "modeled" ||
      payload?.status === "reference" ||
      typeof payload?.last === "number" ||
      typeof payload?.rsi_14 === "number");
  // Anything else without studies is an honest outage / no-data state
  // (`provider_unavailable`, `no_price_history`, or a keyless empty body) —
  // it must NEVER claim the synthetic template.
  const isOutage = !hasStudies && !isSynthetic;
  const outageReason =
    (typeof payload?.reason === "string" && payload.reason) ||
    warnings[0] ||
    "The chart provider returned no study data for this symbol.";

  const closes = useMemo(
    () =>
      (payload?.bars ?? [])
        .filter((b) => typeof b.close === "number")
        .map((b) => ({ date: String(b.date ?? ""), close: b.close as number })),
    [payload],
  );

  const studyKeys = useMemo(
    () => Object.keys(payload?.indicators ?? {}).sort(),
    [payload],
  );

  const studyTableRows = useMemo(
    () =>
      studyKeys.map((key) => {
        const series = (payload?.indicators?.[key] ?? []).filter(
          (p) => typeof p.value === "number",
        );
        const last = series[series.length - 1];
        return {
          key,
          label: studyLabel(key),
          value: last ? (last.value as number) : null,
          asOf: last ? String(last.time ?? "").slice(0, 10) : "—",
        };
      }),
    [payload, studyKeys],
  );

  const STUDY_COLS: DataGridColumn<(typeof studyTableRows)[number]>[] =
    useMemo(
      () => [
        {
          key: "label",
          header: "Study",
          width: 150,
          render: (r) => <span style={monoPrimaryStyle}>{r.label}</span>,
        },
        {
          key: "value",
          header: "Latest",
          numeric: true,
          width: 140,
          render: (r) => (
            <span style={monoStrongStyle}>{fmtNum(r.value)}</span>
          ),
        },
        {
          key: "asOf",
          header: "As of",
          width: 130,
          render: (r) => (
            <span style={monoMutedStyle}>{r.asOf}</span>
          ),
        },
      ],
      [],
    );

  const summary = payload?.summary;
  const status = payload?.status ?? "—";
  const aliasOf = String(data?.metadata?.alias_of ?? "TECH");

  const body = !effectiveSymbol ? (
    <Empty
      title="Pick a symbol"
      body="CHGS needs an instrument symbol to compute chart studies."
      icon="⌖"
    />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={CHART_H} />
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
  ) : isOutage ? (
    <Empty
      title="Chart studies unavailable"
      body={outageReason}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : isSynthetic ? (
    <div className="u-grid-gap-14">
      <div role="alert" style={noticeStyle}>
        <strong>Synthetic template.</strong> The backend served its synthetic
        chart template, NOT live OHLCV data. No studies can be computed from
        it — retry the live path.
      </div>
      <section style={kpiGridStyle} aria-label="CHGS synthetic cards">
        <StatCard
          label="Template close"
          value={fmtNum(payload?.last)}
          caption="SYNTHETIC VALUE — NOT A LIVE PRINT"
          tone="neutral"
        />
        <StatCard
          label="Template RSI 14"
          value={fmtNum(payload?.rsi_14)}
          caption="SYNTHETIC VALUE — NOT A LIVE PRINT"
          tone="neutral"
        />
      </section>
    </div>
  ) : closes.length === 0 ? (
    <Empty
      title="No chart bars returned"
      body="The live chart feed returned no OHLCV bars — retry once the provider recovers."
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="CHGS summary cards">
        <StatCard
          label="Last price"
          value={fmtNum(summary?.last_price)}
          caption={`${closes.length} BARS · ${closes[closes.length - 1]?.date.slice(0, 10) ?? ""}`}
          tone="neutral"
        />
        <StatCard
          label="RSI"
          value={fmtNum(summary?.rsi)}
          caption={
            (summary?.rsi ?? 50) >= 70
              ? "OVERBOUGHT"
              : (summary?.rsi ?? 50) <= 30
                ? "OVERSOLD"
                : "NEUTRAL"
          }
          tone="neutral"
        />
        <StatCard
          label="ATR"
          value={fmtNum(summary?.atr)}
          caption="TRUE-RANGE VOLATILITY"
          tone="neutral"
        />
        <StatCard
          label="ADX"
          value={fmtNum(summary?.adx)}
          caption={(summary?.adx ?? 0) >= 25 ? "TRENDING" : "RANGE-BOUND"}
          tone="neutral"
        />
      </section>
      <Chart symbol={effectiveSymbol} height={CHART_H} initialInterval="1D" />
      {studyTableRows.length > 0 ? (
        <DataGrid
          columns={STUDY_COLS}
          rows={studyTableRows}
          rowKey={(r) => r.key}
          density="compact"
          ariaLabel="CHGS per-study latest values"
          // Lane B4: studies are a heterogeneous reference list (price-scale
          // SMA/BB vs oscillators), so numeric value sorting would be
          // misleading — alphabetical study labels are the only honest
          // default and they pin the previous studyKeys.sort() order.
          defaultSortKey="label"
          defaultSortDir="ascending"
          keyboardNavigable
        />
      ) : null}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Chart Studies — ${effectiveSymbol || ""}`}
          subtitle={`${aliasOf} · ${
            isSynthetic
              ? "synthetic template"
              : isOutage
                ? "provider unavailable"
                : `${closes.length} bars · ${studyKeys.length} studies`
          }`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {isSynthetic
                  ? "template"
                  : isOutage
                    ? "no studies"
                    : `${closes.length} bars`}
              </Pill>
              <Pill
                tone={isSynthetic || isOutage ? "warn" : "positive"}
                variant="soft"
                withDot={!isSynthetic && !isOutage}
              >
                {isSynthetic
                  ? "synthetic template"
                  : isOutage
                    ? "provider unavailable"
                    : "live studies"}
              </Pill>
              <SegmentedControl
                label="RANGE"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh chart studies"
              />
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={effectiveSymbol} />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="mode" value={aliasOf} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="range" value={days} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── formatting ────────────────────────────────────────────────────── */

function fmtNum(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
  return v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
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

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
