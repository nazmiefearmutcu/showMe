/**
 * GP / TECH — Price chart + technical indicator overlays.
 *
 * Bloomberg-grade chart panel with full indicator overlay treatment:
 *   - symbol header strip
 *   - timeframe + style + indicator legend toolbar
 *   - chart canvas (lightweight-charts) with overlays
 *   - right rail: KEY LEVELS · INDICATORS · NEWS
 *   - footer with OHLC value list + provider + cache
 */
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
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
  DeltaChip,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  ResizableChartFrame,
  Skeleton,
  Sparkline,
  StatusSection,
  StatusDivider,
} from "@/design-system";
import {
  measureChartElement,
  resizeChartToElement,
} from "@/lib/chart-layout";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { SymbolBar } from "@/shell/SymbolBar";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";
import { alpha, useChartPalette } from "@/lib/chart-palette";

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
  { id: "1M", label: "1M", days: 30 },
  { id: "3M", label: "3M", days: 90 },
  { id: "6M", label: "6M", days: 180 },
  { id: "1Y", label: "1Y", days: 365 },
  { id: "5Y", label: "5Y", days: 365 * 5 },
  { id: "MAX", label: "Max", days: 365 * 25 },
] as const;
type RangeId = (typeof RANGES)[number]["id"];
const RANGE_IDS = RANGES.map((r) => r.id);

const INTERVALS = [
  { id: "1m", label: "1m" },
  { id: "5m", label: "5m" },
  { id: "15m", label: "15m" },
  { id: "1h", label: "1h" },
  { id: "4h", label: "4h" },
  { id: "1d", label: "1D" },
  { id: "1w", label: "1W" },
] as const;
type IntervalId = (typeof INTERVALS)[number]["id"];
const INTERVAL_IDS = INTERVALS.map((i) => i.id);

const DEPTHS = [
  { id: "300", label: "300" },
  { id: "1000", label: "1K" },
  { id: "3000", label: "3K" },
  { id: "10000", label: "10K" },
] as const;
type DepthId = (typeof DEPTHS)[number]["id"];
const DEPTH_IDS = DEPTHS.map((d) => d.id);

type ChartStyle = "candle" | "line" | "area";

const CHART_STYLES: { id: ChartStyle; label: string }[] = [
  { id: "candle", label: "Candle" },
  { id: "line", label: "Line" },
  { id: "area", label: "Area" },
];

interface CrosshairState {
  price: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  time: string | null;
}

export function GPPane({ code, symbol }: FunctionPaneProps) {
  // 2026-05-11 hotfix: default-symbol fallback so palette-cold GP renders.
  const effectiveSymbol = symbol || defaultSymbolForFunction(code);
  const palette = useChartPalette();
  const indicatorColors = [palette.accent, palette.positive, palette.warn, palette.negative];
  const [range, setRange] = usePersistentOption<RangeId>(
    `showme.${code.toLowerCase()}-range`,
    RANGE_IDS,
    "1Y",
  );
  const [interval, setInterval] = usePersistentOption<IntervalId>(
    `showme.${code.toLowerCase()}-interval`,
    INTERVAL_IDS,
    "1d",
  );
  const [depth, setDepth] = usePersistentOption<DepthId>(
    `showme.${code.toLowerCase()}-depth`,
    DEPTH_IDS,
    "1000",
  );
  const [chartStyle, setChartStyle] = useState<ChartStyle>("candle");
  const [crosshair, setCrosshair] = useState<CrosshairState>({
    price: null,
    open: null,
    high: null,
    low: null,
    close: null,
    volume: null,
    time: null,
  });
  const days = useMemo(
    () => RANGES.find((r) => r.id === range)?.days ?? 365,
    [range],
  );
  const { state, data, error, refetch } = useFunction<GPData>({
    code,
    symbol: effectiveSymbol,
    enabled: !!effectiveSymbol,
    params: { days, range, interval, bars: Number(depth) },
  });

  const ohlc = useMemo(() => normalizeOHLC(data?.data?.ohlcv), [data]);
  const indicators = data?.data?.indicators;
  const indicatorNames = useMemo(
    () => (indicators ? Object.keys(indicators) : []),
    [indicators],
  );

  const last = ohlc[ohlc.length - 1];
  const prev = ohlc[ohlc.length - 2];
  const lastClose = last ? Number(last.close) : null;
  const prevClose = prev ? Number(prev.close) : null;
  const change = lastClose != null && prevClose != null ? lastClose - prevClose : null;
  const changePct =
    lastClose != null && prevClose ? ((lastClose - prevClose) / prevClose) * 100 : null;

  const sparkValues = useMemo(() => {
    if (!ohlc.length) return [] as number[];
    return ohlc
      .slice(-32)
      .map((c) => Number(c.close))
      .filter((v) => Number.isFinite(v));
  }, [ohlc]);

  const closeSeries = useMemo(
    () => ohlc.map((c) => Number(c.close)).filter((v) => Number.isFinite(v)),
    [ohlc],
  );
  const computed = useMemo(() => computeIndicators(closeSeries), [closeSeries]);
  const stats = useMemo(() => {
    if (!ohlc.length) return null;
    const highs = ohlc.map((c) => Number(c.high));
    const lows = ohlc.map((c) => Number(c.low));
    return {
      high: Math.max(...highs),
      low: Math.min(...lows),
      n: ohlc.length,
    };
  }, [ohlc]);

  const newsItems = useMemo(() => buildMockNews(symbol), [symbol]);
  const provider = data?.sources?.[0] ?? "pending";
  const cached = !!(data as { cached?: boolean } | undefined)?.cached;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Price${effectiveSymbol ? ` — ${effectiveSymbol}` : ""}`}
          subtitle={`${range} · ${interval} · ${ohlc.length} candles`}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Run price graph"
                label="Run"
              />
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={effectiveSymbol} />

        {/* Symbol header strip */}
        {symbol && (
          <div style={symbolStripStyle}>
            <div
              className="u-flex u-items-center u-gap-12 u-min-w-0"
            >
              <span style={tickerStyle}>{symbol}</span>
              <Pill tone="accent" variant="soft" withDot={false}>
                {chartStyle.toUpperCase()}
              </Pill>
              <Pill tone="muted" variant="soft" withDot={false}>
                {interval.toUpperCase()}
              </Pill>
              {state === "ok" && (
                <Pill tone="positive" variant="soft">
                  RT SESSION
                </Pill>
              )}
            </div>
            <div className="u-flex u-items-center u-gap-14">
              {lastClose != null && <span style={lastPriceStyle}>{fmtNum(lastClose)}</span>}
              {changePct != null && (
                <DeltaChip value={changePct} format="percent" fractionDigits={2} />
              )}
              {change != null && (
                <span style={changeAbsStyle}>
                  {change >= 0 ? "+" : ""}
                  {change.toFixed(2)}
                </span>
              )}
              {last && (
                <div style={ohlcMiniStyle}>
                  <span>
                    <em>O</em>
                    {fmtNum(last.open)}
                  </span>
                  <span>
                    <em>H</em>
                    {fmtNum(last.high)}
                  </span>
                  <span>
                    <em>L</em>
                    {fmtNum(last.low)}
                  </span>
                  <span>
                    <em>C</em>
                    {fmtNum(last.close)}
                  </span>
                </div>
              )}
              {sparkValues.length > 1 && (
                <Sparkline
                  values={sparkValues}
                  width={88}
                  height={26}
                  tone={(changePct ?? 0) >= 0 ? "positive" : "negative"}
                />
              )}
            </div>
          </div>
        )}

        {/* Toolbar */}
        <div style={toolbarRowStyle}>
          <div style={toolbarSegmentStyle}>
            <span style={toolbarLabelStyle}>TIMEFRAME</span>
            <PillRow
              items={INTERVALS.map((i) => ({ id: i.id, label: i.label }))}
              active={interval}
              onChange={(id) => setInterval(id as IntervalId)}
            />
          </div>
          <div style={toolbarSegmentStyle}>
            <span style={toolbarLabelStyle}>RANGE</span>
            <PillRow
              items={RANGES.map((r) => ({ id: r.id, label: r.label }))}
              active={range}
              onChange={(id) => setRange(id as RangeId)}
            />
          </div>
          <div style={toolbarSegmentStyle}>
            <span style={toolbarLabelStyle}>STYLE</span>
            <PillRow
              items={CHART_STYLES}
              active={chartStyle}
              onChange={(id) => setChartStyle(id as ChartStyle)}
            />
          </div>
          <div style={toolbarSegmentStyle}>
            <span style={toolbarLabelStyle}>BARS</span>
            <PillRow
              items={DEPTHS.map((d) => ({ id: d.id, label: d.label }))}
              active={depth}
              onChange={(id) => setDepth(id as DepthId)}
            />
          </div>
          {indicatorNames.length > 0 && (
            <div style={legendRowStyle}>
              <span style={toolbarLabelStyle}>INDICATORS</span>
              {indicatorNames.map((name, idx) => (
                <span key={name} style={legendChipStyle}>
                  <span
                    aria-hidden
                    style={{
                      ...legendDotStyle,
                      background: indicatorColors[idx % indicatorColors.length],
                    }}
                  />
                  {name.toUpperCase()}
                </span>
              ))}
            </div>
          )}
          <button type="button" style={toolbarButtonStyle} title="Compare symbol">
            Compare +
          </button>
          <button type="button" style={toolbarIconButtonStyle} title="Export">
            ⇪
          </button>
        </div>

        <PaneBody className="u-p-0 u-flex u-min-h-0">
          {!effectiveSymbol ? (
            <Empty title="Pick a symbol" body="GP needs a ticker." icon="⌖" />
          ) : state === "loading" || state === "idle" ? (
            <div className="u-p-14 u-flex-1">
              <Skeleton height={400} />
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
          ) : ohlc.length === 0 ? (
            <Empty title="No price data" body="Function returned no candles." />
          ) : (
            <div style={chartLayoutStyle}>
              <div style={chartCanvasWrapStyle}>
                <ResizableChartFrame
                  storageId={`${code.toUpperCase()}.price`}
                  defaultHeight={{ vh: 0.34, max: 420, min: 240 }}
                  minWidth={420}
                  minHeight={280}
                  maxHeight={1200}
                  style={chartSurfaceStyle}
                  ariaLabel="Resize chart"
                >
                  <ChartView
                    chartId={code.toUpperCase()}
                    candles={ohlc}
                    indicators={indicators}
                    interval={interval}
                    chartStyle={chartStyle}
                    onCrosshair={setCrosshair}
                  />
                  {crosshair.price != null && (
                    <div style={crosshairBoxStyle}>
                      <div style={crosshairRowStyle}>
                        <span style={crosshairLabelStyle}>PRICE</span>
                        <span style={crosshairValueStyle}>
                          {fmtNum(crosshair.price)}
                        </span>
                      </div>
                      {crosshair.volume != null && (
                        <div style={crosshairRowStyle}>
                          <span style={crosshairLabelStyle}>VOL</span>
                          <span style={crosshairValueStyle}>
                            {fmtVolume(crosshair.volume)}
                          </span>
                        </div>
                      )}
                      {crosshair.time && (
                        <div style={crosshairRowStyle}>
                          <span style={crosshairLabelStyle}>TIME</span>
                          <span style={crosshairValueStyle}>{crosshair.time}</span>
                        </div>
                      )}
                    </div>
                  )}
                </ResizableChartFrame>
              </div>
              <RightRail
                stats={stats}
                computed={computed}
                news={newsItems}
                symbol={symbol ?? ""}
              />
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="O" value={fmtNum(last?.open)} tone="neutral" />
          <StatusSection label="H" value={fmtNum(last?.high)} tone="positive" />
          <StatusSection label="L" value={fmtNum(last?.low)} tone="negative" />
          <StatusSection label="C" value={fmtNum(last?.close)} tone="neutral" />
          <StatusSection label="V" value={fmtVolume(last?.volume)} tone="muted" />
          <StatusDivider />
          <StatusSection label="provider" value={provider} tone="muted" />
          <StatusSection
            withDot
            tone={cached ? "warn" : "positive"}
            label="cache"
            value={cached ? "hit" : "live"}
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
            tone="muted"
          />
          {data?.warnings?.length ? (
            <StatusSection
              tone="warn"
              withDot
              label="warn"
              value={String(data.warnings.length)}
            />
          ) : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function PillRow({
  items,
  active,
  onChange,
}: {
  items: readonly { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div style={pillRowContainerStyle}>
      {items.map((it) => {
        const isActive = it.id === active;
        return (
          <button
            key={it.id}
            type="button"
            onClick={() => onChange(it.id)}
            style={{
              ...pillButtonStyle,
              background: isActive ? "var(--accent)" : "transparent",
              color: isActive ? "var(--accent-on)" : "var(--text-secondary)",
              fontWeight: isActive ? 700 : 500,
            }}
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );
}

function RightRail({
  stats,
  computed,
  news,
  symbol,
}: {
  stats: { high: number; low: number; n: number } | null;
  computed: ReturnType<typeof computeIndicators>;
  news: { headline: string; ts: string }[];
  symbol: string;
}) {
  const support = stats ? stats.low + (stats.high - stats.low) * 0.236 : null;
  const resist = stats ? stats.low + (stats.high - stats.low) * 0.786 : null;

  return (
    <aside style={rightRailStyle}>
      <RailSection title="Key levels">
        <RailKv label="Support" value={fmtNum(support)} tone="positive" />
        <RailKv label="Resistance" value={fmtNum(resist)} tone="negative" />
        <RailKv label="52w high" value={fmtNum(stats?.high)} tone="positive" />
        <RailKv label="52w low" value={fmtNum(stats?.low)} tone="negative" />
      </RailSection>
      <RailSection title="Indicators">
        <IndicatorRow
          label="RSI(14)"
          value={computed.rsi != null ? computed.rsi.toFixed(1) : "—"}
          tone={
            computed.rsi == null
              ? "neutral"
              : computed.rsi > 70
                ? "negative"
                : computed.rsi < 30
                  ? "positive"
                  : "neutral"
          }
          spark={computed.rsiSpark}
        />
        <IndicatorRow
          label="MACD"
          value={computed.macd != null ? computed.macd.toFixed(3) : "—"}
          tone={
            computed.macd == null
              ? "neutral"
              : computed.macd >= 0
                ? "positive"
                : "negative"
          }
          spark={computed.macdSpark}
        />
        <IndicatorRow
          label="ATR(14)"
          value={computed.atr != null ? computed.atr.toFixed(2) : "—"}
          tone="accent"
          spark={computed.atrSpark}
        />
      </RailSection>
      <RailSection title={`News · ${symbol}`}>
        <div className="u-grid-gap-8">
          {news.map((item, idx) => (
            <div key={idx} style={newsItemStyle}>
              <span style={newsHeadlineStyle}>{item.headline}</span>
              <span style={newsTimestampStyle}>{item.ts}</span>
            </div>
          ))}
        </div>
      </RailSection>
    </aside>
  );
}

function RailSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={railSectionStyle}>
      <div style={railSectionTitleStyle}>{title}</div>
      <div className="u-grid-gap-6">{children}</div>
    </section>
  );
}

function RailKv({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "neutral" | "accent";
}) {
  const color =
    tone === "positive"
      ? "var(--positive)"
      : tone === "negative"
        ? "var(--negative)"
        : tone === "accent"
          ? "var(--accent)"
          : "var(--text-primary)";
  return (
    <div style={railKvRowStyle}>
      <span style={railKvLabelStyle}>{label}</span>
      <span style={{ ...railKvValueStyle, color }}>{value}</span>
    </div>
  );
}

function IndicatorRow({
  label,
  value,
  tone,
  spark,
}: {
  label: string;
  value: string;
  tone: "positive" | "negative" | "neutral" | "accent";
  spark: number[];
}) {
  const color =
    tone === "positive"
      ? "var(--positive)"
      : tone === "negative"
        ? "var(--negative)"
        : tone === "accent"
          ? "var(--accent)"
          : "var(--text-primary)";
  return (
    <div style={indicatorRowStyle}>
      <span style={railKvLabelStyle}>{label}</span>
      {spark.length > 1 ? (
        <Sparkline
          values={spark}
          width={56}
          height={18}
          tone={tone === "neutral" ? "neutral" : tone}
        />
      ) : (
        <span aria-hidden className="u-w-56" />
      )}
      <span style={{ ...railKvValueStyle, color }}>{value}</span>
    </div>
  );
}

function ChartView({
  chartId: _chartId,
  candles,
  indicators,
  interval,
  chartStyle,
  onCrosshair,
}: {
  chartId: string;
  candles: OHLCRow[];
  indicators?: GPData["indicators"];
  interval: string;
  chartStyle: ChartStyle;
  onCrosshair: (state: CrosshairState) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const palette = useChartPalette();
  const indicatorColors = [palette.accent, palette.positive, palette.warn, palette.negative];

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
        timeVisible: interval !== "1d" && interval !== "1w",
        secondsVisible: interval === "1m",
        borderColor: palette.border,
      },
      rightPriceScale: { borderColor: palette.border },
      crosshair: { mode: 1 },
      width: size.width,
      height: size.height,
    });

    let mainSeries:
      | ISeriesApi<"Candlestick">
      | ISeriesApi<"Line">
      | ISeriesApi<"Area">
      | null = null;
    if (chartStyle === "candle") {
      const candleSeries: ISeriesApi<"Candlestick"> = chart.addCandlestickSeries({
        upColor: palette.positive,
        downColor: palette.negative,
        borderUpColor: palette.positive,
        borderDownColor: palette.negative,
        wickUpColor: palette.positive,
        wickDownColor: palette.negative,
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
      mainSeries = candleSeries;
    } else if (chartStyle === "line") {
      const line = chart.addLineSeries({
        color: palette.accent,
        lineWidth: 2,
        priceLineVisible: false,
      });
      line.setData(
        candles.map<LineData>((c) => ({
          time: timeOf(c),
          value: Number(c.close),
        })),
      );
      mainSeries = line;
    } else {
      const area = chart.addAreaSeries({
        lineColor: palette.accent,
        topColor: alpha(palette.accent, 0.32),
        bottomColor: alpha(palette.accent, 0.02),
        lineWidth: 2,
      });
      area.setData(
        candles.map<LineData>((c) => ({
          time: timeOf(c),
          value: Number(c.close),
        })),
      );
      mainSeries = area;
    }

    const volSeries: ISeriesApi<"Histogram"> = chart.addHistogramSeries({
      priceScaleId: "volume",
      color: palette.volNeutral,
      priceFormat: { type: "volume" },
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });

    volSeries.setData(
      candles.map<HistogramData>((c) => ({
        time: timeOf(c),
        value: Number(c.volume ?? 0),
        color:
          Number(c.close) >= Number(c.open) ? palette.volPos : palette.volNeg,
      })),
    );

    if (indicators) {
      Object.entries(indicators).forEach(([key, points], idx) => {
        if (!Array.isArray(points) || points.length === 0) return;
        const series = chart.addLineSeries({
          color: indicatorColors[idx % indicatorColors.length],
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        series.setData(
          points
            .filter((p) => Number.isFinite(p.value))
            .map<LineData>((p) => ({
              time:
                typeof p.time === "number"
                  ? (p.time as Time)
                  : (String(p.time).slice(0, 10) as Time),
              value: p.value,
            })),
        );
        (series as unknown as { __label?: string }).__label = key;
      });
    }

    // Crosshair → readout box.
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData.size) {
        onCrosshair({
          price: null,
          open: null,
          high: null,
          low: null,
          close: null,
          volume: null,
          time: null,
        });
        return;
      }
      const seriesValues =
        (mainSeries && (param.seriesData.get(mainSeries) as
          | { close?: number; open?: number; high?: number; low?: number; value?: number }
          | undefined)) ||
        (Array.from(param.seriesData.values())[0] as
          | { close?: number; open?: number; high?: number; low?: number; value?: number }
          | undefined);
      const t = param.time;
      const tStr =
        typeof t === "number"
          ? new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")
          : String(t);
      const idx = candles.findIndex((c) => timeOf(c) === param.time);
      const row = idx >= 0 ? candles[idx] : null;
      onCrosshair({
        price: seriesValues?.close ?? seriesValues?.value ?? null,
        open: seriesValues?.open ?? row?.open ?? null,
        high: seriesValues?.high ?? row?.high ?? null,
        low: seriesValues?.low ?? row?.low ?? null,
        close: seriesValues?.close ?? row?.close ?? null,
        volume: row?.volume ?? null,
        time: tStr,
      });
    });

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
  }, [candles, indicators, interval, chartStyle, onCrosshair, palette]);

  if (candles.length === 0) {
    return <Empty title="No price data" body="Function returned no candles." />;
  }

  return (
    <>
      <div style={chartFitToolbarStyle}>
        <span>
          {candles.length.toLocaleString()} candles · drag/scroll to inspect history
        </span>
        <div className="u-flex u-gap-6 hp-chart-toolbar-actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => chartRef.current?.timeScale().fitContent()}
          >
            Fit
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              const el = containerRef.current;
              if (chartRef.current && el)
                focusLatestBars(chartRef.current, candles.length, el.clientWidth);
            }}
          >
            Last
          </button>
        </div>
      </div>
      <div ref={containerRef} style={chartHostStyle} />
    </>
  );
}

// ----- helpers -----

function normalizeOHLC(input: GPData["ohlcv"]): OHLCRow[] {
  if (!input) return [];
  if (Array.isArray(input)) return input as OHLCRow[];
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
  if (typeof v === "number")
    return (v > 10_000_000_000 ? Math.floor(v / 1000) : v) as Time;
  const text = String(v ?? "");
  if (text.includes("T")) {
    const ts = Date.parse(text);
    if (Number.isFinite(ts)) return Math.floor(ts / 1000) as Time;
  }
  return text.slice(0, 10) as Time;
}

function focusLatestBars(chart: IChartApi, count: number, width: number): void {
  if (count <= 0) return;
  const visible = Math.max(90, Math.min(240, Math.floor(width / 7)));
  chart.timeScale().setVisibleLogicalRange({
    from: Math.max(0, count - visible),
    to: count + 8,
  });
}

function fmtNum(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function fmtVolume(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return v.toFixed(0);
}

function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  const k = 2 / (period + 1);
  let prev: number | null = null;
  for (let i = 0; i < values.length; i++) {
    if (prev == null) {
      if (i >= period - 1) {
        let s = 0;
        for (let j = i - period + 1; j <= i; j++) s += values[j];
        prev = s / period;
        out.push(prev);
      } else {
        out.push(null);
      }
    } else {
      prev = values[i] * k + prev * (1 - k);
      out.push(prev);
    }
  }
  return out;
}

function computeIndicators(closes: number[]) {
  if (closes.length < 15) {
    return {
      rsi: null as number | null,
      macd: null as number | null,
      atr: null as number | null,
      rsiSpark: [] as number[],
      macdSpark: [] as number[],
      atrSpark: [] as number[],
    };
  }
  const rsiSeries: number[] = [];
  let gains = 0;
  let losses = 0;
  for (let i = 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    if (i <= 14) {
      if (diff >= 0) gains += diff;
      else losses -= diff;
      if (i === 14) {
        const rs = losses === 0 ? 100 : gains / losses;
        rsiSeries.push(100 - 100 / (1 + rs));
      }
    } else {
      const gain = diff >= 0 ? diff : 0;
      const loss = diff < 0 ? -diff : 0;
      gains = (gains * 13 + gain) / 14;
      losses = (losses * 13 + loss) / 14;
      const rs = losses === 0 ? 100 : gains / losses;
      rsiSeries.push(100 - 100 / (1 + rs));
    }
  }
  const rsi = rsiSeries.length ? rsiSeries[rsiSeries.length - 1] : null;

  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const macdSeries = closes.map((_, i) =>
    ema12[i] != null && ema26[i] != null
      ? (ema12[i] as number) - (ema26[i] as number)
      : null,
  );
  const macdLast = macdSeries[macdSeries.length - 1];
  const macd = typeof macdLast === "number" ? macdLast : null;

  const ranges: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    ranges.push(Math.abs(closes[i] - closes[i - 1]));
  }
  const atrSeries: number[] = [];
  for (let i = 13; i < ranges.length; i++) {
    let s = 0;
    for (let j = i - 13; j <= i; j++) s += ranges[j];
    atrSeries.push(s / 14);
  }
  const atr = atrSeries.length ? atrSeries[atrSeries.length - 1] : null;

  return {
    rsi,
    macd,
    atr,
    rsiSpark: rsiSeries.slice(-24),
    macdSpark: macdSeries.filter((v): v is number => typeof v === "number").slice(-24),
    atrSpark: atrSeries.slice(-24),
  };
}

function buildMockNews(symbol?: string): { headline: string; ts: string }[] {
  if (!symbol) return [];
  const base = symbol.toUpperCase();
  return [
    { headline: `${base} momentum builds as MA cross fires`, ts: "8 min" },
    { headline: `Technical traders eye ${base} breakout level`, ts: "29 min" },
    { headline: `${base} closes in on key Fib retracement`, ts: "1 h" },
  ];
}

// ----- styles -----

const symbolStripStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 14,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  flexWrap: "wrap",
};

const tickerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 18,
  fontWeight: 700,
  letterSpacing: "0.04em",
  color: "var(--text-display)",
};

const lastPriceStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 22,
  fontWeight: 600,
  color: "var(--text-display)",
  fontVariantNumeric: "tabular-nums",
};

const changeAbsStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  color: "var(--text-secondary)",
  fontVariantNumeric: "tabular-nums",
};

const ohlcMiniStyle: CSSProperties = {
  display: "inline-flex",
  gap: 10,
  padding: "4px 8px",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-secondary)",
  fontVariantNumeric: "tabular-nums",
};

const toolbarRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  flexWrap: "wrap",
};

const toolbarSegmentStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const toolbarLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const pillRowContainerStyle: CSSProperties = {
  display: "inline-flex",
  gap: 2,
  padding: 2,
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
};

const pillButtonStyle: CSSProperties = {
  border: "none",
  padding: "3px 8px",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  cursor: "default",
  transition: "background var(--motion-fast), color var(--motion-fast)",
  letterSpacing: "0.04em",
};

const toolbarButtonStyle: CSSProperties = {
  height: 24,
  padding: "0 10px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  cursor: "default",
};

const toolbarIconButtonStyle: CSSProperties = {
  ...toolbarButtonStyle,
  width: 28,
  padding: 0,
  fontSize: 13,
};

const legendRowStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
};

const legendChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "2px 8px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.06em",
  color: "var(--text-secondary)",
};

const legendDotStyle: CSSProperties = {
  display: "inline-block",
  width: 8,
  height: 8,
  borderRadius: 4,
};

const chartLayoutStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr) 240px",
  gap: 12,
  padding: 12,
  flex: 1,
  minHeight: 0,
  width: "100%",
};

const chartCanvasWrapStyle: CSSProperties = {
  position: "relative",
  minWidth: 0,
};

// Outer style for ResizableChartFrame. ``position: relative`` so the
// chart host (absolutely positioned, inset: 0) fills the entire frame.
const chartSurfaceStyle: CSSProperties = {
  position: "relative",
  boxSizing: "border-box",
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  borderRadius: "var(--radius-md)",
  overflow: "hidden",
};

const chartHostStyle: CSSProperties = {
  position: "absolute",
  inset: 0,
  minWidth: 0,
  minHeight: 0,
};

const chartFitToolbarStyle: CSSProperties = {
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
  letterSpacing: "0.06em",
};

const crosshairBoxStyle: CSSProperties = {
  position: "absolute",
  top: 18,
  right: 18,
  zIndex: 3,
  background: "var(--surface-glass)",
  backdropFilter: "blur(8px)",
  WebkitBackdropFilter: "blur(8px)",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 3,
  minWidth: 140,
  pointerEvents: "none",
};

const crosshairRowStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 14,
};

const crosshairLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const crosshairValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--text-display)",
  fontVariantNumeric: "tabular-nums",
};

const rightRailStyle: CSSProperties = {
  display: "grid",
  alignContent: "start",
  gap: 10,
  width: 240,
  minWidth: 0,
};

const railSectionStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  borderRadius: "var(--radius-md)",
  padding: "10px 12px",
};

const railSectionTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.1em",
  textTransform: "uppercase",
  marginBottom: 8,
};

const railKvRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const railKvLabelStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-secondary)",
};

const railKvValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  fontWeight: 600,
  fontVariantNumeric: "tabular-nums",
};

const indicatorRowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr) auto auto",
  alignItems: "center",
  gap: 8,
};

const newsItemStyle: CSSProperties = {
  display: "grid",
  gap: 2,
  padding: "6px 0",
  borderBottom: "1px solid var(--border-row)",
};

const newsHeadlineStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-primary)",
  lineHeight: 1.35,
};

const newsTimestampStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};
