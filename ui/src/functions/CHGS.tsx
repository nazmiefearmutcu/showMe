/**
 * CHGS — Chart Studies (preset TECH bundle).
 *
 * Backend (engine/functions/misc/_bonus.py CHGSFunction) keeps a SYNTHETIC
 * `_chart_template` branch that fires unless `live_chart` is passed — this
 * pane ALWAYS requests the live path (`live_chart: true`) and renders the
 * TECH payload honestly:
 *
 *  - study chips (from the payload's `indicators` map) + close/study overlay
 *    chart + per-study latest-values table + scalar summary cards;
 *  - a payload without `indicators` IS the synthetic template — it gets a
 *    prominent "synthetic template" pill + inline warning, never silently
 *    presented as live chart data.
 */
import { useMemo, useState, type CSSProperties } from "react";
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
  /* synthetic template shape (no live_chart on the backend) */
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

const CHART_W = 620;
const CHART_H = 200;
const PAD = { top: 12, right: 14, bottom: 24, left: 52 };

export function CHGSPane({ code, symbol }: FunctionPaneProps) {
  const [days, setDays] = usePersistentOption<number>(
    "showme.chgs.days",
    DAYS_IDS,
    180,
  );
  const [study, setStudy] = useState<string>("sma_20");
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  // DEFECT GUARD: the backend CHGS serves a synthetic `_chart_template`
  // unless live_chart is truthy — always request the live path here.
  const { state, data, error, refetch } = useFunction<CHGSData>({
    code,
    symbol: effectiveSymbol,
    params: { live_chart: true, days },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const isSynthetic = !payload?.indicators;

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
  const activeStudy = studyKeys.includes(study) ? study : studyKeys[0] ?? "";
  const studySeries = useMemo(
    () =>
      (payload?.indicators?.[activeStudy] ?? []).filter(
        (p) => typeof p.value === "number",
      ),
    [payload, activeStudy],
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
      <SegmentedControl
        label="STUDY"
        value={activeStudy}
        options={studyKeys}
        onChange={(next) => setStudy(String(next))}
        title="Overlay study"
      />
      <figure style={figureStyle} aria-label="CHGS study chart">
        <StudyChart closes={closes} studySeries={studySeries} studyLabel={studyLabel(activeStudy)} />
        <figcaption style={captionStyle}>
          <span style={legendItemStyle}>
            <span aria-hidden="true" style={swatchCloseStyle} /> close
            <span aria-hidden="true" style={swatchStudyStyle} />{" "}
            {studyLabel(activeStudy)}
          </span>
          <span>
            {closes.length} bars · {studySeries.length} {studyLabel(activeStudy)} pts
          </span>
        </figcaption>
      </figure>
      {studyTableRows.length > 0 ? (
        <DataGrid
          columns={STUDY_COLS}
          rows={studyTableRows}
          rowKey={(r) => r.key}
          density="compact"
          ariaLabel="CHGS per-study latest values"
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
          subtitle={`${aliasOf} · ${isSynthetic ? "synthetic template" : `${closes.length} bars · ${studyKeys.length} studies`}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {isSynthetic ? "template" : `${closes.length} bars`}
              </Pill>
              <Pill
                tone={isSynthetic ? "warn" : "positive"}
                variant="soft"
                withDot={!isSynthetic}
              >
                {isSynthetic ? "synthetic template" : "live studies"}
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

/* ── chart ─────────────────────────────────────────────────────────── */

function StudyChart({
  closes,
  studySeries,
  studyLabel: sLabel,
}: {
  closes: Array<{ date: string; close: number }>;
  studySeries: StudyPoint[];
  studyLabel: string;
}) {
  const geom = useMemo(() => {
    const closeVals = closes.map((c) => c.close);
    const studyVals = studySeries.map((p) => p.value as number);
    const all = [...closeVals, ...studyVals];
    const minY = Math.min(...all);
    const maxY = Math.max(...all);
    const spanY = maxY - minY || 1;
    const innerW = CHART_W - PAD.left - PAD.right;
    const innerH = CHART_H - PAD.top - PAD.bottom;
    const x = (i: number, len: number) =>
      PAD.left + (len <= 1 ? 0 : (i / (len - 1)) * innerW);
    const y = (v: number) => PAD.top + (1 - (v - minY) / spanY) * innerH;
    return {
      closeLine: closes
        .map((c, i) => `${x(i, closes.length).toFixed(1)},${y(c.close).toFixed(1)}`)
        .join(" "),
      studyLine: studySeries
        .map((p, i) => `${x(i, studySeries.length).toFixed(1)},${y(p.value as number).toFixed(1)}`)
        .join(" "),
      last: {
        x: x(closes.length - 1, closes.length),
        y: y(closeVals[closeVals.length - 1]),
        v: closeVals[closeVals.length - 1],
        date: closes[closes.length - 1].date,
      },
      grid: [0, 0.5, 1].map((f) => ({
        y: PAD.top + f * innerH,
        v: maxY - f * spanY,
      })),
    };
  }, [closes, studySeries]);

  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      role="img"
      aria-label={`Close with ${sLabel} overlay, ${closes.length} bars and ${studySeries.length} study points`}
      style={svgStyle}
    >
      {geom.grid.map((g, i) => (
        <g key={i}>
          <line
            x1={PAD.left}
            x2={CHART_W - PAD.right}
            y1={g.y}
            y2={g.y}
            stroke="var(--grid-color, var(--text-mute))"
            strokeWidth={1}
          />
          <text x={4} y={g.y + 3} style={axisTextStyle}>
            {fmtNum(g.v)}
          </text>
        </g>
      ))}
      <polyline
        points={geom.studyLine}
        fill="none"
        stroke="var(--accent-2, var(--accent))"
        strokeWidth={1.3}
        strokeDasharray="4 3"
      />
      <polyline
        points={geom.closeLine}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={1.6}
      />
      <circle cx={geom.last.x} cy={geom.last.y} r={3} fill="var(--accent)">
        <title>{`${geom.last.date.slice(0, 10)}: close ${fmtNum(geom.last.v)}`}</title>
      </circle>
    </svg>
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

const figureStyle: CSSProperties = {
  margin: 0,
};

const captionStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  marginTop: 4,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const legendItemStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const swatchCloseStyle: CSSProperties = {
  width: 12,
  height: 2,
  background: "var(--accent)",
};

const swatchStudyStyle: CSSProperties = {
  width: 12,
  height: 2,
  marginLeft: 8,
  background: "repeating-linear-gradient(90deg, var(--accent-2, var(--accent)) 0 4px, transparent 4px 7px)",
};

const svgStyle: CSSProperties = {
  width: "100%",
  height: "auto",
  display: "block",
};

const axisTextStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  fill: "var(--text-mute)",
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
