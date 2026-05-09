/**
 * GP / TECH — Price chart + technical indicators (lightweight-charts).
 *
 * The ShowMe GP / TECH functions return OHLCV records keyed by ISO date. We
 * render a candlestick series + volume histogram and overlay any returned
 * indicators (sma, ema, rsi, macd, bollinger).
 */
import { useEffect, useMemo, useRef, type CSSProperties } from "react";
import {
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
  createChart,
} from "lightweight-charts";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  Tabs,
} from "@/design-system";
import {
  chartResizeHandleStyle,
  measureChartElement,
  resizeChartToElement,
  terminalChartHostStyle,
  terminalChartViewportStyle,
  usePersistentChartSize,
} from "@/lib/chart-layout";
import { useFunction } from "@/lib/useFunction";
import { SymbolBar } from "@/shell/SymbolBar";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface OHLCRow {
  date?: string;
  ts?: string;
  time?: string | number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface GPData {
  ohlcv?: OHLCRow[] | Record<string, unknown>;
  indicators?: Record<string, Array<{ time: string | number; value: number }>>;
  [key: string]: unknown;
}

const RANGES = [
  { id: "1M", days: 30 },
  { id: "3M", days: 90 },
  { id: "6M", days: 180 },
  { id: "1Y", days: 365 },
  { id: "5Y", days: 365 * 5 },
  { id: "MAX", days: 365 * 25 },
] as const;
type RangeId = (typeof RANGES)[number]["id"];
const RANGE_IDS = RANGES.map((r) => r.id);
const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"] as const;
type IntervalId = (typeof INTERVALS)[number];
const DEPTHS = [
  { id: "300", label: "300" },
  { id: "1000", label: "1K" },
  { id: "3000", label: "3K" },
  { id: "10000", label: "10K" },
] as const;
type DepthId = (typeof DEPTHS)[number]["id"];
const DEPTH_IDS = DEPTHS.map((d) => d.id);

export function GPPane({ code, symbol }: FunctionPaneProps) {
  const [range, setRange] = usePersistentOption<RangeId>(
    `showme.${code.toLowerCase()}-range`,
    RANGE_IDS,
    "1Y",
  );
  const [interval, setInterval] = usePersistentOption<IntervalId>(
    `showme.${code.toLowerCase()}-interval`,
    INTERVALS,
    "1d",
  );
  const [depth, setDepth] = usePersistentOption<DepthId>(
    `showme.${code.toLowerCase()}-depth`,
    DEPTH_IDS,
    "1000",
  );
  const days = useMemo(
    () => RANGES.find((r) => r.id === range)?.days ?? 365,
    [range],
  );
  const { state, data, error, refetch } = useFunction<GPData>({
    code,
    symbol,
    enabled: !!symbol,
    params: { days, range, interval, bars: Number(depth) },
  });

  const ohlc = useMemo(() => normalizeOHLC(data?.data?.ohlcv), [data]);

  const body = !symbol ? (
    <Empty title="Pick a symbol" body="GP needs a ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <Skeleton height={360} />
  ) : state === "error" ? (
    <Empty
      title="Function error"
      body={error?.message ?? "—"}
      icon="!"
      action={
        <button onClick={refetch} className="btn">Retry</button>
      }
    />
  ) : (
    <ChartView
      chartId={code.toUpperCase()}
      candles={ohlc}
      indicators={data?.data?.indicators}
      interval={interval}
    />
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title={`Price — ${symbol ?? ""}`}
          subtitle={`${range} · ${interval} · ${ohlc.length} candles`}
          trailing={
            <FunctionControlGroup>
              <Tabs
                variant="segmented"
                items={RANGES.map((r) => ({ id: r.id, label: r.id }))}
                active={range}
                onChange={(id) => setRange(id as RangeId)}
              />
              <Tabs
                variant="segmented"
                items={INTERVALS.map((id) => ({ id, label: id }))}
                active={interval}
                onChange={(id) => setInterval(id as IntervalId)}
              />
              <Tabs
                variant="segmented"
                items={DEPTHS.map((d) => ({ id: d.id, label: d.label }))}
                active={depth}
                onChange={(id) => setDepth(id as DepthId)}
              />
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!symbol}
                title="Run price graph"
                label="Run"
              />
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={symbol} />
        <PaneBody style={{ padding: 0 }}>{body}</PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
          {data?.warnings?.length ? (
            <Pill tone="warn" withDot={false}>
              {data.warnings.length} warn
            </Pill>
          ) : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function normalizeOHLC(input: GPData["ohlcv"]): OHLCRow[] {
  if (!input) return [];
  if (Array.isArray(input)) return input as OHLCRow[];
  // dict-of-rows {ts: {open,high,low,close,volume}}
  if (typeof input === "object") {
    return Object.entries(input as Record<string, unknown>)
      .map(([ts, row]) => ({
        ts,
        ...(row as Omit<OHLCRow, "ts">),
      }))
      .filter((r) => Number.isFinite(r.open));
  }
  return [];
}

function timeOf(row: OHLCRow): Time {
  const v = row.time ?? row.ts ?? row.date;
  if (typeof v === "number") return (v > 10_000_000_000 ? Math.floor(v / 1000) : v) as Time;
  const text = String(v ?? "");
  if (text.includes("T")) {
    const ts = Date.parse(text);
    if (Number.isFinite(ts)) return Math.floor(ts / 1000) as Time;
  }
  return text.slice(0, 10) as Time;
}

function ChartView({
  chartId,
  candles,
  indicators,
  interval,
}: {
  chartId: string;
  candles: OHLCRow[];
  indicators?: GPData["indicators"];
  interval: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const resize = usePersistentChartSize(`${chartId}.price`);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const size = measureChartElement(el, 460);
    const chart = createChart(el, {
      layout: {
        background: { color: "transparent" },
        textColor: "rgba(240,242,245,0.85)",
        fontFamily: "JetBrains Mono, SF Mono, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      timeScale: {
        rightOffset: 8,
        barSpacing: 7,
        minBarSpacing: 0.3,
        timeVisible: interval !== "1d" && interval !== "1w",
        secondsVisible: interval === "1m",
        borderColor: "rgba(255,255,255,0.08)",
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      crosshair: { mode: 1 },
      width: size.width,
      height: size.height,
    });

    const candleSeries: ISeriesApi<"Candlestick"> = chart.addCandlestickSeries({
      upColor: "#00d183",
      downColor: "#ff3b58",
      borderUpColor: "#00d183",
      borderDownColor: "#ff3b58",
      wickUpColor: "#00d183",
      wickDownColor: "#ff3b58",
    });
    const volSeries: ISeriesApi<"Histogram"> = chart.addHistogramSeries({
      priceScaleId: "volume",
      color: "rgba(160,164,171,0.4)",
      priceFormat: { type: "volume" },
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });

    candleSeries.setData(
      candles.map<CandlestickData>((c) => ({
        time: timeOf(c),
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
      })),
    );
    volSeries.setData(
      candles.map<HistogramData>((c) => ({
        time: timeOf(c),
        value: Number(c.volume ?? 0),
        color:
          Number(c.close) >= Number(c.open)
            ? "rgba(0,209,131,0.4)"
            : "rgba(255,59,88,0.4)",
      })),
    );

    if (indicators) {
      const palette = ["#ff7a00", "#00d183", "#a0a4ab", "#ffb547"];
      Object.entries(indicators).forEach(([key, points], idx) => {
        if (!Array.isArray(points) || points.length === 0) return;
        const series = chart.addLineSeries({
          color: palette[idx % palette.length],
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        series.setData(
          points
            .filter((p) => Number.isFinite(p.value))
            .map<LineData>((p) => ({
              time: typeof p.time === "number" ? (p.time as Time) : (String(p.time).slice(0, 10) as Time),
              value: p.value,
            })),
        );
        // Tag the series with the indicator name in the legend (handled below)
        (series as unknown as { __label?: string }).__label = key;
      });
    }

    chartRef.current = chart;
    focusLatestBars(chart, candles.length, size.width);

    const ro = new ResizeObserver(() => {
      resizeChartToElement(chart, el, 460);
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, indicators, interval]);

  if (candles.length === 0) {
    return <Empty title="No price data" body="Function returned no candles." />;
  }

  return (
    <div
      ref={resize.frameRef}
      style={{ ...terminalChartViewportStyle, ...resize.frameStyle }}
    >
      <div style={chartToolbarStyle}>
        <span>{candles.length.toLocaleString()} candles loaded · drag/scroll to inspect history</span>
        <div style={{ display: "flex", gap: 6, pointerEvents: "auto" }}>
          <button type="button" className="btn btn--ghost" onClick={() => chartRef.current?.timeScale().fitContent()}>
            Fit
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              const el = containerRef.current;
              if (chartRef.current && el) focusLatestBars(chartRef.current, candles.length, el.clientWidth);
            }}
          >
            Last
          </button>
        </div>
      </div>
      <div ref={containerRef} style={terminalChartHostStyle} />
      <button
        type="button"
        aria-label="Resize chart"
        title="Drag to resize chart. Double-click to reset."
        onPointerDown={resize.startResize}
        onDoubleClick={resize.resetSize}
        style={chartResizeHandleStyle}
      />
    </div>
  );
}

function focusLatestBars(chart: IChartApi, count: number, width: number): void {
  if (count <= 0) return;
  const visible = Math.max(90, Math.min(240, Math.floor(width / 7)));
  chart.timeScale().setVisibleLogicalRange({
    from: Math.max(0, count - visible),
    to: count + 8,
  });
}

const chartToolbarStyle: CSSProperties = {
  position: "absolute",
  top: 8,
  left: 10,
  right: 10,
  zIndex: 2,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  pointerEvents: "none",
  color: "var(--text-mute)",
  fontSize: 10,
  textTransform: "uppercase",
};
