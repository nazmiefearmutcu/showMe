/**
 * CPF — Commodity Price Forecast.
 *
 * Live actual series (keyless Yahoo futures proxy for the selected FRED
 * series id) plus a trend-extrapolated forward leg computed by the backend
 * (engine/functions/commodity/_funcs.py CPFFunction). Header: series +
 * horizon segmented controls, data-mode + model pills, refresh. Body:
 * headline cards (latest actual, endpoint forecast, implied move) + an
 * actual/forecast SVG curve + the forecast-point table.
 *
 * Honesty: the forecast leg is a clamped log-linear trend extrapolation of
 * the live actual series — NOT analyst consensus. The pane says so on a
 * dedicated pill + inline notice, and surfaces data_mode verbatim.
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
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface CPFPoint {
  date?: string;
  value?: number | null;
}

interface CPFData {
  status?: string;
  reason?: string;
  series_id?: string;
  commodity?: string;
  unit?: string;
  horizon?: string;
  actual?: CPFPoint[];
  forecast?: CPFPoint[];
  forecast_vintage?: string | null;
  as_of?: string;
  data_mode?: string;
  next_actions?: string[];
}

const SERIES_OPTIONS = [
  { value: "WTISPLC", label: "WTI" },
  { value: "PGOLD", label: "GOLD" },
  { value: "PCOPPUSDM", label: "COPPER" },
  { value: "DHHNGSP", label: "NATGAS" },
] as const;
const HORIZON_OPTIONS = [
  { value: "6M", label: "6M" },
  { value: "1Y", label: "1Y" },
  { value: "2Y", label: "2Y" },
  { value: "5Y", label: "5Y" },
] as const;

const CHART_W = 620;
const CHART_H = 190;
const PAD = { top: 12, right: 14, bottom: 24, left: 46 };

export function CPFPane({ code, symbol }: FunctionPaneProps) {
  const [seriesId, setSeriesId] = usePersistentOption<string>(
    "showme.cpf.series",
    SERIES_OPTIONS.map((o) => o.value),
    "WTISPLC",
  );
  const [horizon, setHorizon] = usePersistentOption<string>(
    "showme.cpf.horizon",
    HORIZON_OPTIONS.map((o) => o.value),
    "1Y",
  );
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["COMMODITY"]);
  const { state, data, error, refetch } = useFunction<CPFData>({
    code,
    symbol: effectiveSymbol,
    params: { series_id: seriesId, horizon, show_actual_history: true },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const actual = useMemo(
    () => (payload?.actual ?? []).filter((p) => typeof p.value === "number"),
    [payload],
  );
  const forecast = useMemo(
    () => (payload?.forecast ?? []).filter((p) => typeof p.value === "number"),
    [payload],
  );

  const status = payload?.status ?? "—";
  const dataMode = payload?.data_mode ?? "—";
  const isLive = dataMode === "live_official";
  const latestActual = actual.length ? (actual[actual.length - 1].value as number) : null;
  const endpointForecast = forecast.length
    ? (forecast[forecast.length - 1].value as number)
    : null;
  const impliedMovePct =
    latestActual != null && endpointForecast != null && latestActual !== 0
      ? (endpointForecast / latestActual - 1) * 100
      : null;

  const FORECAST_COLS: DataGridColumn<CPFPoint>[] = useMemo(
    () => [
      {
        key: "date",
        header: "Period",
        width: 140,
        render: (r) => (
          <span style={monoPrimaryStyle}>{String(r.date ?? "—").slice(0, 10)}</span>
        ),
      },
      {
        key: "value",
        header: "Forecast",
        numeric: true,
        width: 130,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtValue(r.value)}</span>
        ),
      },
      {
        key: "delta",
        header: "Δ vs actual",
        numeric: true,
        width: 130,
        render: (r) => {
          const pct =
            typeof r.value === "number" &&
            latestActual != null &&
            latestActual !== 0
              ? (r.value / latestActual - 1) * 100
              : null;
          return (
            <span
              style={{
                ...monoStrongStyle,
                color:
                  pct == null
                    ? "var(--text-mute)"
                    : pct >= 0
                      ? "var(--positive)"
                      : "var(--negative)",
              }}
            >
              {fmtSignedPct(pct)}
            </span>
          );
        },
      },
    ],
    [latestActual],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a commodity" body="CPF needs a commodity context." icon="⌖" />
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
  ) : actual.length === 0 && forecast.length === 0 ? (
    <Empty
      title={status === "provider_unavailable" ? "Forecast feed unavailable" : "No forecast data"}
      body={
        payload?.reason ??
        "The live actual-price feed returned no points, so no forecast was computed."
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
      <div role="note" style={noticeStyle}>
        <strong>Trend model.</strong> The forecast leg is a clamped trend
        extrapolation of the live actual series (vintage{" "}
        {payload?.forecast_vintage ?? "—"}) — NOT analyst consensus.
      </div>
      <section style={kpiGridStyle} aria-label="CPF forecast cards">
        <StatCard
          label="Latest actual"
          value={fmtValue(latestActual)}
          caption={`${payload?.unit ?? ""} · ${String(payload?.as_of ?? "—").slice(0, 10)}`}
          tone="neutral"
        />
        <StatCard
          label={`Forecast @ ${payload?.horizon ?? horizon}`}
          value={fmtValue(endpointForecast)}
          caption={`VINTAGE ${payload?.forecast_vintage ?? "—"}`}
          tone={impliedMovePct != null && impliedMovePct < 0 ? "negative" : "positive"}
        />
        <StatCard
          label="Implied move"
          value={fmtSignedPct(impliedMovePct)}
          caption="ENDPOINT VS ACTUAL"
          tone={impliedMovePct != null && impliedMovePct < 0 ? "negative" : "neutral"}
        />
        <StatCard
          label="Series"
          value={payload?.commodity ?? seriesId}
          caption={`${actual.length} ACTUAL · ${forecast.length} FORECAST PTS`}
          tone="neutral"
        />
      </section>
      <figure style={figureStyle} aria-label="CPF actual vs forecast curve">
        <ForecastChart actual={actual} forecast={forecast} />
        <figcaption style={captionStyle}>
          <span style={legendItemStyle}>
            <span aria-hidden="true" style={swatchActualStyle} /> actual
            <span aria-hidden="true" style={swatchForecastStyle} /> forecast
          </span>
          <span>
            {actual.length} actual + {forecast.length} forecast points
          </span>
        </figcaption>
      </figure>
      {forecast.length > 0 ? (
        <DataGrid
          columns={FORECAST_COLS}
          rows={forecast}
          rowKey={(r, i) => `${r.date ?? "f"}-${i}`}
          density="compact"
          ariaLabel="CPF forecast points"
        />
      ) : null}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Commodity Forecast — ${payload?.commodity ?? seriesId}`}
          subtitle={`${seriesId} · ${actual.length}+${forecast.length} pts`}
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={isLive ? "positive" : "warn"}
                variant="soft"
                withDot={isLive}
              >
                {isLive ? "live actual" : dataMode}
              </Pill>
              <Pill tone="muted" variant="soft" withDot={false}>
                trend model
              </Pill>
              <SegmentedControl
                label="SERIES"
                value={seriesId}
                options={SERIES_OPTIONS}
                onChange={setSeriesId}
              />
              <SegmentedControl
                label="HORIZON"
                value={horizon}
                options={HORIZON_OPTIONS}
                onChange={setHorizon}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh forecast"
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
          <StatusSection label="data_mode" value={dataMode} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="horizon" value={horizon} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── chart ─────────────────────────────────────────────────────────── */

function ForecastChart({
  actual,
  forecast,
}: {
  actual: CPFPoint[];
  forecast: CPFPoint[];
}) {
  const geom = useMemo(() => {
    const all = [...actual, ...forecast]
      .map((p) => p.value as number)
      .filter((v) => Number.isFinite(v));
    const minY = Math.min(...all);
    const maxY = Math.max(...all);
    const spanY = maxY - minY || 1;
    const total = actual.length + forecast.length;
    const innerW = CHART_W - PAD.left - PAD.right;
    const innerH = CHART_H - PAD.top - PAD.bottom;
    const x = (i: number) => PAD.left + (i / Math.max(total - 1, 1)) * innerW;
    const y = (v: number) => PAD.top + (1 - (v - minY) / spanY) * innerH;
    const toLine = (pts: CPFPoint[], offset: number) =>
      pts
        .map((p, i) => `${x(offset + i).toFixed(1)},${y(p.value as number).toFixed(1)}`)
        .join(" ");
    return {
      actualLine: toLine(actual, 0),
      forecastLine: toLine(forecast, actual.length),
      lastActual:
        actual.length > 0
          ? {
              x: x(actual.length - 1),
              y: y(actual[actual.length - 1].value as number),
              v: actual[actual.length - 1].value as number,
              date: actual[actual.length - 1].date ?? "",
            }
          : null,
      dots: forecast.map((p, i) => ({
        x: x(actual.length + i),
        y: y(p.value as number),
        v: p.value as number,
        date: p.date ?? "",
      })),
      grid: [0, 0.5, 1].map((f) => ({
        y: PAD.top + f * innerH,
        v: maxY - f * spanY,
      })),
    };
  }, [actual, forecast]);

  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      role="img"
      aria-label={`Actual vs forecast curve with ${actual.length} actual and ${forecast.length} forecast points`}
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
            {fmtValue(g.v)}
          </text>
        </g>
      ))}
      <polyline
        points={geom.actualLine}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={1.6}
      />
      <polyline
        points={geom.forecastLine}
        fill="none"
        stroke="var(--accent-2, var(--accent))"
        strokeWidth={1.6}
        strokeDasharray="5 4"
      />
      {geom.lastActual ? (
        <circle cx={geom.lastActual.x} cy={geom.lastActual.y} r={3} fill="var(--accent)">
          <title>{`actual ${geom.lastActual.date.slice(0, 10)}: ${fmtValue(geom.lastActual.v)}`}</title>
        </circle>
      ) : null}
      {geom.dots.map((d) => (
        <circle
          key={`${d.date}-${d.x}`}
          cx={d.x}
          cy={d.y}
          r={2.6}
          fill="var(--accent-2, var(--accent))"
        >
          <title>{`forecast ${d.date.slice(0, 10)}: ${fmtValue(d.v)}`}</title>
        </circle>
      ))}
    </svg>
  );
}

/* ── formatting ────────────────────────────────────────────────────── */

function fmtValue(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  const digits = a >= 1000 ? 0 : a >= 100 ? 1 : 3;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtSignedPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: 12,
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
  fontSize: 10,
  color: "var(--text-mute)",
};

const legendItemStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const swatchActualStyle: CSSProperties = {
  width: 12,
  height: 2,
  background: "var(--accent)",
};

const swatchForecastStyle: CSSProperties = {
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
  fontSize: 9,
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
