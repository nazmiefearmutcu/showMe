/**
 * GP / TECH — Price chart + technical indicator rail.
 *
 * The chart itself is rendered by the in-house showMe chart engine
 * (`@/chart/Chart`), which owns the timeframe/type pickers, the searchable
 * indicator picker, zoom/pan and theming. GP keeps the function payload
 * (range/interval) that feeds the header strip, key-level rail and footer,
 * plus the resizable frame, the 52-week rail and the honest transport pills.
 */
import { useMemo, type CSSProperties } from "react";
import { useLiveQuote } from "@/lib/market-data";
import type { TransportState } from "@/lib/market-data";
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
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { maxOf, minOf } from "@/lib/maxOf";
import { SymbolBar } from "@/shell/SymbolBar";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";
import { Chart } from "@/chart/Chart";
import { formatPrice } from "@/lib/format";

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

// GP's historical default fetch depth for the rail payload. The BARS chips
// are gone (the engine fetches its own bars), so the payload pins the pane's
// previous default instead of a persisted preference.
const DEFAULT_BARS = 1000;

type ChartStyle = "candle" | "line" | "area";

/**
 * The engine's timeframe catalog is case-sensitive in ways GP's ids were
 * not: "1d"/"1w" (GP) map to the engine's "1D"/"1W", while "1m" (minute)
 * and "1M" (month) stay distinct instruments.
 */
function mapInterval(interval: IntervalId): string {
  if (interval === "1d") return "1D";
  if (interval === "1w") return "1W";
  return interval;
}

/** GP's historical default chart style, mapped to the engine vocabulary. */
const GP_CHART_STYLE: ChartStyle = "candle";

function mapStyle(style: ChartStyle): "candles" | "line" | "area" {
  return style === "candle" ? "candles" : style;
}

export function GPPane({ code, symbol }: FunctionPaneProps) {
  // 2026-05-11 hotfix: default-symbol fallback so palette-cold GP renders.
  const effectiveSymbol = symbol || defaultSymbolForFunction(code);
  const [range, setRange] = usePersistentOption<RangeId>(
    `showme.${code.toLowerCase()}-range`,
    RANGE_IDS,
    "1Y",
  );
  // The engine owns the live timeframe picker; GP keeps the persisted
  // interval only to seed the engine and to serve the payload's resolution
  // (the rail stats derive from the candles it returns).
  const [interval] = usePersistentOption<IntervalId>(
    `showme.${code.toLowerCase()}-interval`,
    INTERVAL_IDS,
    "1d",
  );
  const days = useMemo(
    () => RANGES.find((r) => r.id === range)?.days ?? 365,
    [range],
  );
  const { state, data, error, refetch } = useFunction<GPData>({
    code,
    symbol: effectiveSymbol,
    enabled: !!effectiveSymbol,
    params: { days, range, interval, bars: DEFAULT_BARS },
  });

  const ohlc = useMemo(() => normalizeOHLC(data?.data?.ohlcv), [data]);

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

  const computed = useMemo(() => computeIndicators(ohlc), [ohlc]);
  const stats = useMemo(() => {
    if (!ohlc.length) return null;
    const highs = ohlc.map((c) => Number(c.high));
    const lows = ohlc.map((c) => Number(c.low));
    // UA-CRITICAL-01: stack-safe; OHLC arrays cross ~100k on intraday history.
    return {
      high: maxOf(highs),
      low: minOf(lows),
      n: ohlc.length,
    };
  }, [ohlc]);

  // GP-specific news is not wired into the backend yet. Until the news plug
  // lands we surface an honest empty state instead of fabricating headlines.
  // See S03-R: no mock news is allowed in the chart pane.
  const newsItems: { headline: string; ts: string; url?: string }[] = [];
  const newsState: "empty" | "loading" | "ok" = "empty";
  const provider = data?.sources?.[0] ?? "pending";
  // GP wire-truth: the alias now emits 52-week provider meta + a
  // `deep_history` flag; when the winning provider carries neither the rail
  // labels range extremes honestly and the history chip reads "windowed".
  const payloadExtras = data?.data as
    | {
        deep_history?: boolean;
        fifty_two_week_high?: number | null;
        fifty_two_week_low?: number | null;
      }
    | undefined;
  const deepHistory = payloadExtras?.deep_history === true;
  const week52High =
    typeof payloadExtras?.fifty_two_week_high === "number" &&
    Number.isFinite(payloadExtras.fifty_two_week_high)
      ? payloadExtras.fifty_two_week_high
      : null;
  const week52Low =
    typeof payloadExtras?.fifty_two_week_low === "number" &&
    Number.isFinite(payloadExtras.fifty_two_week_low)
      ? payloadExtras.fifty_two_week_low
      : null;
  const week52 =
    week52High != null && week52Low != null
      ? { high: week52High, low: week52Low }
      : null;

  // S03-R: the pane keeps a live quote subscription so the header strip can
  // show a real transport state and the current price without waiting for the
  // next function refetch. The chart itself is refreshed by the engine.
  const liveQuote = useLiveQuote(effectiveSymbol, { enabled: !!effectiveSymbol });
  const transportState: TransportState = liveQuote.transportState;
  const isStale =
    !!liveQuote.snapshot &&
    typeof liveQuote.freshnessMs === "number" &&
    liveQuote.stale;
  const isRefreshing = state === "ok" && (liveQuote.refreshing ?? false);
  const isOffline =
    transportState === "offline" || transportState === "error";
  const isReconnecting =
    transportState === "reconnecting" ||
    transportState === "connecting" ||
    transportState === "stale";
  const snapshotOnly = state === "ok" && ohlc.length === 0 && !!liveQuote.snapshot;
  const liveTickPrice = liveQuote.lastTick?.price ?? null;

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
              <Pill tone="muted" variant="soft" withDot={false}>
                {interval.toUpperCase()}
              </Pill>
              {state === "ok" && transportState === "live" && (
                <span data-testid="gp-transport-pill" data-state="live">
                  <Pill tone="positive" variant="soft">RT LIVE</Pill>
                </span>
              )}
              {state === "ok" && isReconnecting && (
                <span data-testid="gp-transport-pill" data-state={transportState}>
                  <Pill tone="warn" variant="soft">
                    {transportState === "stale" ? "STALE" : "RECONNECTING"}
                  </Pill>
                </span>
              )}
              {state === "ok" && isOffline && (
                <span data-testid="gp-transport-pill" data-state="offline">
                  <Pill tone="negative" variant="soft">OFFLINE</Pill>
                </span>
              )}
              {snapshotOnly && (
                <span data-testid="gp-snapshot-only">
                  <Pill tone="warn" variant="soft">SNAPSHOT ONLY</Pill>
                </span>
              )}
              {isStale && !isOffline && (
                <span data-testid="gp-stale">
                  <Pill tone="warn" variant="soft">STALE</Pill>
                </span>
              )}
              {isRefreshing && (
                <span data-testid="gp-refreshing">
                  <Pill tone="accent" variant="soft">REFRESHING</Pill>
                </span>
              )}
            </div>
            <div className="u-flex u-items-center u-gap-14">
              {/*
               * S12 GP truth: when the live transport is actually open
               * (`transportState === "live"`) and a tick has landed,
               * show that tick — not the candle-frozen `lastClose`. The
               * engine already reflects the tick on the canvas; the header
               * must mirror it or the surface lies. We keep the
               * historical `lastClose` as a fallback so the header
               * doesn't blank between refreshes when the channel hasn't
               * delivered a first tick yet.
               */}
              {(() => {
                const displayPrice =
                  transportState === "live" && liveTickPrice != null
                    ? liveTickPrice
                    : lastClose;
                const displayChange =
                  transportState === "live" &&
                  liveTickPrice != null &&
                  prevClose != null
                    ? liveTickPrice - prevClose
                    : change;
                const displayChangePct =
                  transportState === "live" &&
                  liveTickPrice != null &&
                  prevClose
                    ? ((liveTickPrice - prevClose) / prevClose) * 100
                    : changePct;
                return (
                  <>
                    {displayPrice != null && (
                      <span
                        style={lastPriceStyle}
                        data-testid="gp-display-price"
                        data-live={transportState === "live" && liveTickPrice != null ? "1" : "0"}
                      >
                        {fmtNum(displayPrice)}
                      </span>
                    )}
                    {displayChangePct != null && (
                      <DeltaChip
                        value={displayChangePct}
                        format="percent"
                        fractionDigits={2}
                      />
                    )}
                    {displayChange != null && (
                      <span style={changeAbsStyle}>
                        {displayChange >= 0 ? "+" : ""}
                        {fmtNum(displayChange)}
                      </span>
                    )}
                  </>
                );
              })()}
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

        {/*
         * Toolbar — RANGE drives the function payload behind the header
         * stats and the key-level rail. Timeframe / chart type / indicators
         * are owned by the chart engine's own toolbar, so their chip rows
         * are gone.
         */}
        <div style={toolbarRowStyle}>
          <div style={toolbarSegmentStyle}>
            <span style={toolbarLabelStyle}>RANGE</span>
            <PillRow
              items={RANGES.map((r) => ({ id: r.id, label: r.label }))}
              active={range}
              onChange={(id) => setRange(id as RangeId)}
            />
          </div>
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
                  <Chart
                    symbol={effectiveSymbol}
                    fill
                    layoutScope={code.toUpperCase()}
                    initialInterval={mapInterval(interval)}
                    initialType={mapStyle(GP_CHART_STYLE)}
                  />
                </ResizableChartFrame>
              </div>
              <RightRail
                stats={stats}
                week52={week52}
                computed={computed}
                news={newsItems}
                newsState={newsState}
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
            tone="muted"
            label="history"
            value={deepHistory ? "deep" : "windowed"}
            title={
              deepHistory
                ? "Winner raced against every provider's deepest reach"
                : "Adapter fallback window (deep race unavailable)"
            }
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
  week52,
  computed,
  news,
  newsState,
  symbol,
}: {
  stats: { high: number; low: number; n: number } | null;
  week52: { high: number; low: number } | null;
  computed: ReturnType<typeof computeIndicators>;
  news: { headline: string; ts: string; url?: string }[];
  newsState: "empty" | "loading" | "ok";
  symbol: string;
}) {
  const support = stats ? stats.low + (stats.high - stats.low) * 0.236 : null;
  const resist = stats ? stats.low + (stats.high - stats.low) * 0.786 : null;
  // True 52-week extremes when the provider meta carried them; otherwise the
  // label is honest about being the selected range's high/low.
  const highLabel = week52 ? "52w high" : "Range high";
  const lowLabel = week52 ? "52w low" : "Range low";

  return (
    <aside style={rightRailStyle}>
      <RailSection title="Key levels">
        <RailKv label="Support" value={fmtNum(support)} tone="positive" />
        <RailKv label="Resistance" value={fmtNum(resist)} tone="negative" />
        <RailKv
          label={highLabel}
          value={fmtNum(week52?.high ?? stats?.high)}
          tone="positive"
        />
        <RailKv
          label={lowLabel}
          value={fmtNum(week52?.low ?? stats?.low)}
          tone="negative"
        />
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
        <div className="u-grid-gap-8" data-testid="gp-news">
          {newsState === "ok" && news.length > 0 ? (
            news.map((item, idx) => (
              <div key={idx} style={newsItemStyle}>
                {item.url ? (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    style={newsHeadlineStyle}
                  >
                    {item.headline}
                  </a>
                ) : (
                  <span style={newsHeadlineStyle}>{item.headline}</span>
                )}
                <span style={newsTimestampStyle}>{item.ts}</span>
              </div>
            ))
          ) : (
            <div data-testid="gp-news-empty" style={newsEmptyStyle}>
              <div style={newsEmptyTitleStyle}>News not wired</div>
              <div style={newsEmptyBodyStyle}>
                Per-symbol GP headlines aren't connected to a live source yet.
                Use NEWS or TOP for verified headlines.
              </div>
            </div>
          )}
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

function fmtNum(v: number | undefined | null): string {
  // Adaptive precision — sub-cent assets (PENGU $0.000620) keep digits
  // instead of collapsing to "0.0006" with maxFractionDigits:4.
  return formatPrice(v);
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

function lastDefined(values: (number | null)[]): number | null {
  for (let i = values.length - 1; i >= 0; i--) {
    const value = values[i];
    if (value != null && Number.isFinite(value)) return value;
  }
  return null;
}

/** Wilder RSI, aligned to the close series (null before the first value). */
function rsiSeries(closes: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length <= period) return out;
  let gains = 0;
  let losses = 0;
  for (let i = 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    if (i <= period) {
      if (diff >= 0) gains += diff;
      else losses -= diff;
      if (i === period) {
        const rs = losses === 0 ? 100 : gains / losses;
        out[i] = 100 - 100 / (1 + rs);
      }
    } else {
      const gain = diff >= 0 ? diff : 0;
      const loss = diff < 0 ? -diff : 0;
      gains = (gains * (period - 1) + gain) / period;
      losses = (losses * (period - 1) + loss) / period;
      const rs = losses === 0 ? 100 : gains / losses;
      out[i] = 100 - 100 / (1 + rs);
    }
  }
  return out;
}

/**
 * True ATR — Wilder-smoothed average of the true range:
 *   TR = max(H−L, |H−prevC|, |L−prevC|)
 * Shared definition with HP and with the backend TECH function (ewm
 * alpha = 1/period, seeded on the first TR). The pre-fix GP "ATR" was the
 * mean absolute close change — no high/low, no gaps.
 */
function trueAtrSeries(
  rows: Array<{ high?: number; low?: number; close?: number }>,
  period = 14,
): (number | null)[] {
  const out: (number | null)[] = new Array(rows.length).fill(null);
  if (rows.length === 0) return out;
  let previousClose: number | null = null;
  let atr: number | null = null;
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const high = row.high;
    const low = row.low;
    const close = row.close;
    if (
      high == null ||
      low == null ||
      !Number.isFinite(high) ||
      !Number.isFinite(low)
    ) {
      if (close != null && Number.isFinite(close)) previousClose = close;
      continue;
    }
    const trueRange =
      previousClose == null
        ? high - low
        : Math.max(
            high - low,
            Math.abs(high - previousClose),
            Math.abs(low - previousClose),
          );
    atr = atr == null ? trueRange : ((period - 1) * atr + trueRange) / period;
    out[i] = atr;
    if (close != null && Number.isFinite(close)) previousClose = close;
  }
  return out;
}

function computeIndicators(rows: OHLCRow[]) {
  const closes = rows
    .map((c) => Number(c.close))
    .filter((v) => Number.isFinite(v));
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
  const rsiAll = rsiSeries(closes, 14);
  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const macdSeries = closes.map((_, i) =>
    ema12[i] != null && ema26[i] != null
      ? (ema12[i] as number) - (ema26[i] as number)
      : null,
  );
  const atrAll = trueAtrSeries(rows, 14);

  return {
    rsi: lastDefined(rsiAll),
    macd: lastDefined(macdSeries),
    atr: lastDefined(atrAll),
    rsiSpark: rsiAll.filter((v): v is number => v != null).slice(-24),
    macdSpark: macdSeries
      .filter((v): v is number => typeof v === "number")
      .slice(-24),
    atrSpark: atrAll.filter((v): v is number => v != null).slice(-24),
  };
}

// S03-R: `buildMockNews` was removed. GP must never fabricate per-symbol
// headlines; show an honest "not wired" empty state instead until a real
// news source is plugged in. See RightRail (`newsState === 'empty'`).

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
  fontSize: "var(--font-size-2xl)",
  fontWeight: 700,
  letterSpacing: "0.04em",
  color: "var(--text-display)",
};

const lastPriceStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-3xl)",
  fontWeight: 600,
  color: "var(--text-display)",
  fontVariantNumeric: "tabular-nums",
};

const changeAbsStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
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
  fontSize: "var(--font-size-2xs)",
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
  fontSize: "var(--font-size-xs)",
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
  fontSize: "var(--font-size-2xs)",
  cursor: "default",
  transition: "background var(--motion-fast), color var(--motion-fast)",
  letterSpacing: "0.04em",
};

const newsEmptyStyle: CSSProperties = {
  padding: "8px 0 2px",
  display: "grid",
  gap: 4,
};

const newsEmptyTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-secondary)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};

const newsEmptyBodyStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--text-mute)",
  lineHeight: 1.4,
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

// Pure resize chrome for ResizableChartFrame — the chart engine paints its
// own border/background/radius, so a second frame border would double up.
const chartSurfaceStyle: CSSProperties = {
  position: "relative",
  boxSizing: "border-box",
  overflow: "hidden",
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
  fontSize: "var(--font-size-xs)",
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
  fontSize: "var(--font-size-sm)",
  color: "var(--text-secondary)",
};

const railKvValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
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
  fontSize: "var(--font-size-sm)",
  color: "var(--text-primary)",
  lineHeight: 1.35,
};

const newsTimestampStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};
