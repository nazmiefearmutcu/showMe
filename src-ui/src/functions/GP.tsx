/**
 * GP / TECH — Price chart + technical indicators (lightweight-charts).
 *
 * The ShowMe GP / TECH functions return OHLCV records keyed by ISO date. We
 * render a candlestick series + volume histogram and overlay any returned
 * indicators (sma, ema, rsi, macd, bollinger).
 */
import { useEffect, useMemo, useRef } from "react";
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
] as const;
type RangeId = (typeof RANGES)[number]["id"];
const RANGE_IDS = RANGES.map((r) => r.id);

export function GPPane({ code, symbol }: FunctionPaneProps) {
  const [range, setRange] = usePersistentOption<RangeId>(
    `showme.${code.toLowerCase()}-range`,
    RANGE_IDS,
    "1Y",
  );
  const days = useMemo(
    () => RANGES.find((r) => r.id === range)?.days ?? 365,
    [range],
  );
  const { state, data, error, refetch } = useFunction<GPData>({
    code,
    symbol,
    enabled: !!symbol,
    params: { days },
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
    <ChartView candles={ohlc} indicators={data?.data?.indicators} />
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title={`Price — ${symbol ?? ""}`}
          subtitle={`${range} · ${ohlc.length} candles`}
          trailing={
            <FunctionControlGroup>
              <Tabs
                variant="segmented"
                items={RANGES.map((r) => ({ id: r.id, label: r.id }))}
                active={range}
                onChange={(id) => setRange(id as RangeId)}
              />
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!symbol}
                title="Refresh chart"
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
  const v = row.date ?? row.ts ?? row.time;
  if (typeof v === "number") return v as Time;
  // lightweight-charts accepts {year,month,day} or 'YYYY-MM-DD'
  return String(v ?? "").slice(0, 10) as Time;
}

function ChartView({
  candles,
  indicators,
}: {
  candles: OHLCRow[];
  indicators?: GPData["indicators"];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
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
        rightOffset: 4,
        borderColor: "rgba(255,255,255,0.08)",
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      crosshair: { mode: 1 },
      width: el.clientWidth,
      height: el.clientHeight,
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
    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (!el) return;
      chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, indicators]);

  if (candles.length === 0) {
    return <Empty title="No price data" body="Function returned no candles." />;
  }

  return (
    <div
      style={{
        position: "relative",
        height: "calc(100vh - 320px)",
        minHeight: 360,
      }}
    >
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
