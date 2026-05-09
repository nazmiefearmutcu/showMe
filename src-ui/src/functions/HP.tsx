/**
 * HP — Historical price (Bloomberg HP<GO> analogue).
 *
 * Symbol + range selector → OHLCV table with CSV export. Range presets
 * mirror ShowMe (`1M / 3M / 6M / 1Y / 5Y / max`) and the table is sortable
 * with a Download CSV button that uses an in-memory Blob — no sidecar
 * round-trip required.
 */
import { useEffect, useMemo, useRef, type CSSProperties } from "react";
import {
  type CandlestickData,
  type HistogramData,
  type IChartApi,
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
  terminalChartSurfaceStyle,
  usePersistentChartSize,
} from "@/lib/chart-layout";
import { useFunction } from "@/lib/useFunction";
import { SymbolBar } from "@/shell/SymbolBar";
import { buildCsv, type HPRow } from "./HP.csv";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const RANGES = [
  { id: "1M", label: "1M", days: 30 },
  { id: "3M", label: "3M", days: 90 },
  { id: "6M", label: "6M", days: 180 },
  { id: "1Y", label: "1Y", days: 365 },
  { id: "5Y", label: "5Y", days: 365 * 5 },
  { id: "max", label: "Max", days: 365 * 25 },
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

export function HPPane({ code, symbol }: FunctionPaneProps) {
  const [range, setRange] = usePersistentOption<RangeId>(
    "showme.hp-range",
    RANGE_IDS,
    "3M",
  );
  const [interval, setInterval] = usePersistentOption<IntervalId>(
    "showme.hp-interval",
    INTERVALS,
    "1d",
  );
  const [depth, setDepth] = usePersistentOption<DepthId>(
    "showme.hp-depth",
    DEPTH_IDS,
    "1000",
  );
  const days = useMemo(() => RANGES.find((r) => r.id === range)!.days, [range]);
  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { days, range, interval, bars: Number(depth) },
    enabled: !!symbol,
  });

  const rows = useMemo(() => decorate(normalizeRows(data?.data)), [data]);

  const stats = useMemo(() => {
    if (!rows.length) return null;
    const closes = rows
      .map((r) => r.close ?? r.adj_close ?? r.adjClose)
      .filter((v): v is number => v != null);
    if (!closes.length) return null;
    const high = Math.max(...closes);
    const low = Math.min(...closes);
    const first = closes[closes.length - 1];
    const last = closes[0];
    const totalPct = first ? ((last - first) / first) * 100 : null;
    return { high, low, totalPct, n: rows.length };
  }, [rows]);

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title={`Historical price${symbol ? ` — ${symbol}` : ""}`}
          subtitle={
            stats
              ? `${stats.n} bars · range Δ ${stats.totalPct?.toFixed(2)}%`
              : "Pick a symbol"
          }
          trailing={
            <FunctionControlGroup>
              <Tabs
                variant="segmented"
                items={RANGES.map((r) => ({ id: r.id, label: r.label }))}
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
                title="Run historical price"
                label="Run"
              />
              <button
                type="button"
                className="btn btn--accent"
                disabled={!rows.length || !symbol}
                onClick={() => downloadCsv(symbol ?? "data", range, rows)}
                title="Download CSV"
              >
                CSV
              </button>
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={symbol} />
        <PaneBody>
          {!symbol ? (
            <Empty
              title="Pick a symbol"
              body="HP downloads OHLCV rows for one ticker."
              icon="⌖"
            />
          ) : state === "loading" || state === "idle" ? (
            <Skeleton height={320} />
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
          ) : rows.length === 0 ? (
            <Empty title="No bars" body={`No HP payload for ${symbol}.`} />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {stats && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Pill tone="muted" withDot={false}>
                    bars · {stats.n}
                  </Pill>
                  <Pill tone="positive" withDot={false}>
                    high · {fmtNum(stats.high)}
                  </Pill>
                  <Pill tone="negative" withDot={false}>
                    low · {fmtNum(stats.low)}
                  </Pill>
                  {stats.totalPct != null && (
                    <Pill
                      tone={stats.totalPct >= 0 ? "positive" : "negative"}
                      withDot={false}
                    >
                      total · {stats.totalPct.toFixed(2)}%
                    </Pill>
                  )}
                </div>
              )}
              <PriceChart chartId={code.toUpperCase()} rows={rows} interval={interval} />
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>range · {range}</span>
          <span>resolution · {interval}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function PriceChart({
  chartId,
  rows,
  interval,
}: {
  chartId: string;
  rows: Array<HPRow & { _change?: number; _changePct?: number }>;
  interval: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const resize = usePersistentChartSize(`${chartId}.price`);
  const chartRows = useMemo(
    () => [...rows]
      .filter((row) => row.open != null && row.high != null && row.low != null && row.close != null)
      .sort((a, b) => new Date(a.date ?? a.ts ?? "").getTime() - new Date(b.date ?? b.ts ?? "").getTime()),
    [rows],
  );

  useEffect(() => {
    const el = hostRef.current;
    if (!el || chartRows.length < 2) return;
    const size = measureChartElement(el);
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
    const candles = chart.addCandlestickSeries({
      upColor: "#00d183",
      downColor: "#ff3b58",
      borderUpColor: "#00d183",
      borderDownColor: "#ff3b58",
      wickUpColor: "#00d183",
      wickDownColor: "#ff3b58",
    });
    candles.setData(
      chartRows.map<CandlestickData>((row) => ({
        time: chartTime(row.date ?? row.ts),
        open: Number(row.open),
        high: Number(row.high),
        low: Number(row.low),
        close: Number(row.close),
      })),
    );
    const volume = chart.addHistogramSeries({
      priceScaleId: "volume",
      color: "rgba(160,164,171,0.35)",
      priceFormat: { type: "volume" },
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });
    volume.setData(
      chartRows.map<HistogramData>((row) => ({
        time: chartTime(row.date ?? row.ts),
        value: Number(row.volume ?? 0),
        color:
          Number(row.close) >= Number(row.open)
            ? "rgba(0,209,131,0.35)"
            : "rgba(255,59,88,0.35)",
      })),
    );
    chartRef.current = chart;
    focusLatestBars(chart, chartRows.length, size.width);
    const ro = new ResizeObserver(() => {
      resizeChartToElement(chart, el);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [chartRows, interval]);

  if (chartRows.length < 2) return null;
  return (
    <section
      ref={resize.frameRef}
      style={{ ...terminalChartSurfaceStyle, ...resize.frameStyle }}
    >
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        color: "var(--text-mute)",
        fontSize: 10,
        textTransform: "uppercase",
        marginBottom: 6,
      }}>
        <span>Candlestick</span>
        <span>OHLCV price chart</span>
      </div>
      <div style={chartToolbarStyle}>
        <span>{chartRows.length.toLocaleString()} loaded</span>
        <div style={{ display: "flex", gap: 6, pointerEvents: "auto" }}>
          <button type="button" className="btn btn--ghost" onClick={() => chartRef.current?.timeScale().fitContent()}>
            Fit
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              const el = hostRef.current;
              if (chartRef.current && el) focusLatestBars(chartRef.current, chartRows.length, el.clientWidth);
            }}
          >
            Last
          </button>
        </div>
      </div>
      <div ref={hostRef} style={terminalChartHostStyle} />
      <button
        type="button"
        aria-label="Resize chart"
        title="Drag to resize chart. Double-click to reset."
        onPointerDown={resize.startResize}
        onDoubleClick={resize.resetSize}
        style={chartResizeHandleStyle}
      />
    </section>
  );
}

function chartTime(value: string | undefined): Time {
  const text = String(value ?? "");
  if (text.includes("T")) {
    const ts = Date.parse(text);
    if (Number.isFinite(ts)) return Math.floor(ts / 1000) as Time;
  }
  return text.slice(0, 10) as Time;
}

function normalizeRows(payload: unknown): HPRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as HPRow[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.bars ?? o.rows ?? o.history ?? o.items ?? o.candles ?? null;
    if (Array.isArray(items)) return items as HPRow[];
  }
  return [];
}

function decorate(rows: HPRow[]): Array<HPRow & { _change?: number; _changePct?: number }> {
  // Rows come back newest-first by convention; if older-first, reverse for delta.
  const sorted = [...rows].sort((a, b) => {
    const ad = new Date(a.date ?? a.ts ?? "").getTime();
    const bd = new Date(b.date ?? b.ts ?? "").getTime();
    return bd - ad;
  });
  return sorted.map((r, i) => {
    const prev = sorted[i + 1];
    if (!prev) return r;
    const c = r.close ?? r.adj_close ?? r.adjClose;
    const p = prev.close ?? prev.adj_close ?? prev.adjClose;
    if (c == null || p == null) return r;
    return { ...r, _change: c - p, _changePct: ((c - p) / p) * 100 };
  });
}

function fmtNum(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function downloadCsv(symbol: string, range: string, rows: HPRow[]): void {
  const csv = buildCsv(rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${symbol}-${range}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 0);
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
  top: 30,
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
