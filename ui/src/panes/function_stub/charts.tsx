import { useEffect, useRef } from "react";
import {
  createChart,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import {
  measureChartElement,
  resizeChartToElement,
} from "@/lib/chart-layout";
import { alpha, useChartPalette } from "@/lib/chart-palette";
import { getCandlePriceFormat } from "@/lib/format-helpers";
import { ResizableChartFrame } from "@/design-system";
import {
  chartAxis,
  chartHeader,
  chartPanel,
  chartStats,
  chartSvg,
  heatmapCell,
  heatmapGrid,
  lightweightChartHost,
  metaLabel,
  metricBox,
} from "./styles";
import type { ChartSeries } from "./_types";
import {
  focusLatestBars,
  formatValue,
  hasOhlcPoint,
  hasTimePoint,
  hasVolumePoint,
  motionDelayClass,
} from "./helpers";

export function SeriesChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  if (series.kind === "line" || series.kind === "ohlc") {
    return <LightweightSeriesChart chartId={chartId} series={series} />;
  }
  if (series.kind === "curve") {
    return <CurveChart chartId={chartId} series={series} />;
  }
  if (series.kind === "heatmap") {
    return <HeatmapChart chartId={chartId} series={series} />;
  }
  return <BarChart chartId={chartId} series={series} />;
}

function LightweightSeriesChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const palette = useChartPalette();
  const values = series.points.map((point) => point.y);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const first = series.points[0]?.y ?? 0;
  const last = series.points.at(-1)?.y ?? 0;
  const delta = last - first;
  const intradayTime = series.points.some((point) => typeof point.time === "number");
  const paletteKey = Object.values(palette).join("|");

  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick" | "Line"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const firstSeedFocusedRef = useRef(false);

  // 1. Rebuild effect: when series.kind or palette changes, recreate the chart and series structures.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const size = measureChartElement(el, 460);
    const chart = createChart(el, {
      layout: {
        background: { color: "transparent" },
        textColor: palette.text,
        fontFamily: "JetBrains Mono, SF Mono, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      timeScale: {
        rightOffset: 8,
        barSpacing: 7,
        minBarSpacing: 0.3,
        timeVisible: intradayTime,
        borderColor: palette.border,
      },
      rightPriceScale: { borderColor: palette.border },
      crosshair: { mode: 1 },
      width: size.width,
      height: size.height,
    });

    chartRef.current = chart;
    firstSeedFocusedRef.current = false; // Reset framing for new chart instance

    if (series.kind === "ohlc") {
      // Derive precision from the last close so sub-cent assets keep digits
      // on the price axis (PENGU $0.000620 → precision 8) instead of
      // collapsing to "0.00" with lightweight-charts' default precision 2.
      const candle = chart.addCandlestickSeries({
        upColor: palette.positive,
        downColor: palette.negative,
        borderUpColor: palette.positive,
        borderDownColor: palette.negative,
        wickUpColor: palette.positive,
        wickDownColor: palette.negative,
        priceFormat: getCandlePriceFormat(last),
      });
      seriesRef.current = candle;

      const vol = chart.addHistogramSeries({
        priceScaleId: "volume",
        color: palette.volNeutral,
        priceFormat: { type: "volume" },
      });
      volSeriesRef.current = vol;

      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.78, bottom: 0 },
      });
    } else {
      const line = chart.addLineSeries({
        color: delta >= 0 ? palette.positive : palette.negative,
        lineWidth: 2,
        priceLineVisible: false,
        priceFormat: getCandlePriceFormat(last),
      });
      seriesRef.current = line;
      volSeriesRef.current = null;
    }

    const ro = new ResizeObserver(() => {
      resizeChartToElement(chart, el, 460);
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volSeriesRef.current = null;
    };
  }, [series.kind, paletteKey]);

  // 2. Data effect: when points, delta, or series.kind changes, update the series data.
  useEffect(() => {
    const chart = chartRef.current;
    const sRef = seriesRef.current;
    if (!chart || !sRef) return;

    if (series.kind === "ohlc") {
      // Refresh priceFormat in case last close magnitude crossed a precision
      // threshold (e.g. user pivots symbol mid-instance from BTC to PENGU).
      sRef.applyOptions({ priceFormat: getCandlePriceFormat(last) });
      sRef.setData(
        series.points
          .filter(hasOhlcPoint)
          .map<CandlestickData>((point) => ({
            time: point.time,
            open: point.open,
            high: point.high,
            low: point.low,
            close: point.close,
          })),
      );

      const volume = series.points
        .filter(hasVolumePoint)
        .map<HistogramData>((point) => ({
          time: point.time,
          value: Number(point.volume),
          color:
            Number(point.close) >= Number(point.open)
              ? alpha(palette.positive, 0.35)
              : alpha(palette.negative, 0.35),
        }));
      if (volSeriesRef.current) {
        volSeriesRef.current.setData(volume);
      }
    } else {
      sRef.setData(
        series.points
          .filter(hasTimePoint)
          .map<LineData>((point) => ({
            time: point.time,
            value: point.y,
          })),
      );
      sRef.applyOptions({
        color: delta >= 0 ? palette.positive : palette.negative,
        priceFormat: getCandlePriceFormat(last),
      });
    }

    // Framing: only run focusLatestBars for the first data seed on this chart instance
    if (!firstSeedFocusedRef.current && series.points.length > 0) {
      firstSeedFocusedRef.current = true;
      const el = containerRef.current;
      const width = el ? measureChartElement(el, 460).width : 460;
      focusLatestBars(chart, series.points.length, width);
    }
  }, [series.points, delta, series.kind, paletteKey]);

  // 3. Option effect: when intradayTime changes, toggle timeScale.timeVisible.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.applyOptions({
      timeScale: {
        timeVisible: intradayTime,
      },
    });
  }, [intradayTime]);

  return (
    <ResizableChartFrame
      storageId={`${chartId}.${series.kind}`}
      defaultHeight={{ vh: 0.46, max: 420, min: 240 }}
      minWidth={420}
      minHeight={240}
      maxHeight={1200}
      className="showme-card-reveal showme-stub-block showme-stub-chart"
      style={chartPanel}
      ariaLabel="Resize chart"
    >
      <ChartTitle series={series} last={last} min={min} max={max} delta={delta} />
      <div
        ref={containerRef}
        style={lightweightChartHost}
        role="img"
        aria-label={`${series.kind} chart for ${series.yKey ?? "series"}, ${series.points.length} points`}
      />
      <div style={chartAxis}>
        <span>{series.points[0]?.xLabel ?? "—"}</span>
        <span>{series.xKey ? `${series.xKey} / ${series.yKey}` : series.yKey}</span>
        <span>{series.points.at(-1)?.xLabel ?? "—"}</span>
      </div>
    </ResizableChartFrame>
  );
}

function BarChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  const width = 1000;
  const height = 280;
  const padX = 40;
  const padY = 26;
  const points = series.points.slice(0, 30);
  const values = points.map((point) => point.y);
  const maxAbs = Math.max(...values.map((value) => Math.abs(value)), 1);
  const barGap = 6;
  const plotWidth = width - padX * 2;
  const barWidth = Math.max(5, (plotWidth - barGap * (points.length - 1)) / points.length);
  const zeroY = padY + (height - padY * 2) / 2;
  const first = series.points[0]?.y ?? 0;
  const last = series.points.at(-1)?.y ?? 0;
  const delta = last - first;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return (
    <ResizableChartFrame
      storageId={`${chartId}.${series.kind}`}
      defaultHeight={{ vh: 0.4, max: 360, min: 220 }}
      minWidth={420}
      minHeight={220}
      maxHeight={1000}
      className="showme-card-reveal showme-stub-block showme-stub-chart"
      style={chartPanel}
      ariaLabel="Resize chart"
    >
      <ChartTitle series={series} last={last} min={min} max={max} delta={delta} />
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={chartSvg}>
        <line
          x1={padX}
          x2={width - padX}
          y1={zeroY}
          y2={zeroY}
          stroke="var(--border-strong)"
        />
        {points.map((point, idx) => {
          const x = padX + idx * (barWidth + barGap);
          const magnitude = (Math.abs(point.y) / maxAbs) * ((height - padY * 2) / 2);
          const y = point.y >= 0 ? zeroY - magnitude : zeroY;
          return (
            <rect
              key={`${point.xLabel}-${idx}`}
              x={x}
              y={y}
              width={barWidth}
              height={Math.max(2, magnitude)}
              rx={2}
              fill={point.y >= 0 ? "var(--positive)" : "var(--negative)"}
              opacity={0.78}
            />
          );
        })}
      </svg>
      <div style={chartAxis}>
        <span>{series.points[0]?.xLabel ?? "—"}</span>
        <span>{series.labelKey ? `${series.labelKey} / ${series.yKey}` : series.yKey}</span>
        <span>{series.points.at(-1)?.xLabel ?? "—"}</span>
      </div>
    </ResizableChartFrame>
  );
}

function CurveChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  const width = 1000;
  const height = 280;
  const padX = 42;
  const padY = 26;
  const points = series.points.filter((point) => typeof point.x === "number");
  const values = points.map((point) => point.y);
  const xValues = points.map((point) => Number(point.x));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const first = points[0]?.y ?? 0;
  const last = points.at(-1)?.y ?? 0;
  const delta = last - first;
  const minX = Math.min(...xValues);
  const maxX = Math.max(...xValues);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(max - min, 1e-9);
  const toX = (value: number) => padX + ((value - minX) / spanX) * (width - padX * 2);
  const toY = (value: number) => height - padY - ((value - min) / spanY) * (height - padY * 2);
  const d = points
    .map((point, idx) => {
      const x = toX(Number(point.x));
      const y = toY(point.y);
      return `${idx === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const zeroY = min < 0 && max > 0 ? toY(0) : null;
  return (
    <ResizableChartFrame
      storageId={`${chartId}.${series.kind}`}
      defaultHeight={{ vh: 0.4, max: 360, min: 220 }}
      minWidth={420}
      minHeight={220}
      maxHeight={1000}
      className="showme-card-reveal showme-stub-block showme-stub-chart"
      style={chartPanel}
      ariaLabel="Resize chart"
    >
      <ChartTitle series={series} last={last} min={min} max={max} delta={delta} />
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={chartSvg}>
        {zeroY !== null ? (
          <line
            x1={padX}
            x2={width - padX}
            y1={zeroY}
            y2={zeroY}
            stroke="var(--border-strong)"
          />
        ) : null}
        <path
          d={d}
          fill="none"
          stroke={delta >= 0 ? "var(--positive)" : "var(--negative)"}
          strokeWidth={3}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
        {points.slice(0, 1).concat(points.slice(-1)).map((point, idx) => (
          <circle
            key={`${point.xLabel}-${idx}`}
            cx={toX(Number(point.x))}
            cy={toY(point.y)}
            r={4}
            fill={idx === 0 ? "var(--text-mute)" : "var(--accent)"}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <div style={chartAxis}>
        <span>{points[0]?.xLabel ?? "—"}</span>
        <span>{series.xKey ? `${series.xKey} / ${series.yKey}` : series.yKey}</span>
        <span>{points.at(-1)?.xLabel ?? "—"}</span>
      </div>
    </ResizableChartFrame>
  );
}

function HeatmapChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  const palette = useChartPalette();
  const values = series.points.map((point) => point.y);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const first = series.points[0]?.y ?? 0;
  const last = series.points.at(-1)?.y ?? 0;
  const delta = last - first;
  const maxAbs = Math.max(...values.map((value) => Math.abs(value)), 1);
  return (
    <ResizableChartFrame
      storageId={`${chartId}.${series.kind}`}
      defaultHeight={{ vh: 0.4, max: 360, min: 220 }}
      minWidth={420}
      minHeight={220}
      maxHeight={1000}
      className="showme-card-reveal showme-stub-block showme-stub-chart"
      style={chartPanel}
      ariaLabel="Resize heatmap"
    >
      <ChartTitle series={series} last={last} min={min} max={max} delta={delta} />
      <div style={heatmapGrid}>
        {series.points.slice(0, 40).map((point, idx) => {
          const opacity = 0.22 + Math.min(Math.abs(point.y) / maxAbs, 1) * 0.58;
          const color = point.y >= 0 ? alpha(palette.positive, opacity) : alpha(palette.negative, opacity);
          return (
            <div
              key={`${point.xLabel}-${idx}`}
              className={`showme-row-reveal ${motionDelayClass(idx)}`}
              style={{ ...heatmapCell, background: color }}
            >
              <strong>{point.xLabel}</strong>
              <span>{formatValue(point.y)}</span>
            </div>
          );
        })}
      </div>
      <div style={chartAxis}>
        <span>{series.points[0]?.xLabel ?? "—"}</span>
        <span>{series.labelKey ? `${series.labelKey} / ${series.yKey}` : series.yKey}</span>
        <span>{series.points.at(-1)?.xLabel ?? "—"}</span>
      </div>
    </ResizableChartFrame>
  );
}

function ChartTitle({
  series,
  last,
  min,
  max,
  delta,
}: {
  series: ChartSeries;
  last: number;
  min: number;
  max: number;
  delta: number;
}) {
  const kindLabel =
    series.kind === "ohlc"
      ? "Candlestick"
      : series.kind === "curve"
        ? "Curve"
      : series.kind === "line"
        ? "Time series"
        : series.kind === "heatmap"
          ? "Heatmap"
          : "Bar chart";
  return (
    <div style={chartHeader}>
      <div>
        <div style={metaLabel}>{kindLabel}</div>
        <strong className="u-text-primary">{series.title}</strong>
      </div>
      <div style={chartStats}>
        <Metric label="last" value={formatValue(last)} />
        <Metric label="min" value={formatValue(min)} />
        <Metric label="max" value={formatValue(max)} />
        <Metric label="delta" value={formatValue(delta)} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={metricBox}>
      <div style={metaLabel}>{label}</div>
      <div style={{ color: "var(--text-primary)", fontFamily: "JetBrains Mono, monospace" }}>
        {value}
      </div>
    </div>
  );
}
