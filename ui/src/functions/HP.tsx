/**
 * HP — Historical price (Bloomberg HP<GO> analogue).
 *
 * The main historical price chart is rendered by the in-house showMe chart
 * engine (`@/chart/Chart`), which owns the timeframe/type pickers, the
 * searchable indicator picker, unlimited zoom/pan/fit and theming. HP keeps
 * the function payload (range / interval / bars) that feeds the symbol header
 * strip, the key-level rail and the footer, plus the resizable frame and the
 * honest transport pills.
 *
 * Bloomberg-grade panel:
 *   - symbol header strip (price, delta, OHLC, RT badge)
 *   - RANGE pill row (drives the function payload) + CSV export
 *   - chart engine surface (timeframe / style / indicators owned by it)
 *   - right rail: KEY LEVELS · INDICATORS · NEWS
 *   - footer: OHLC value list + provider + history indicator
 *
 * The retired chart-library series also carried the Compare % overlay
 * and the screenshot-based PNG export; both were bound to that chart instance
 * and went with it (no dead controls). CSV export and the RANGE chips stay.
 */
import { useMemo, type CSSProperties } from "react";
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
import { useLiveQuote, type TransportState } from "@/lib/market-data";
import { maxOf, minOf } from "@/lib/maxOf";
import { SymbolBar } from "@/shell/SymbolBar";
import { buildCsv, type HPRow } from "./HP.csv";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";
import { Chart } from "@/chart/Chart";
import { formatPrice } from "@/lib/format";

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

// HP's historical fetch depth for the rail/header payload. The BARS chips are
// gone (the engine fetches its own bars), so the payload pins the pane's
// previous default instead of a persisted preference.
const DEFAULT_BARS = 1000;

type ChartStyle = "candle" | "line" | "area";

/** HP's historical default chart style, mapped to the engine vocabulary. */
const HP_CHART_STYLE: ChartStyle = "candle";

/**
 * The engine's timeframe catalog is case-sensitive in ways HP's ids were
 * not: "1d"/"1w" (HP) map to the engine's "1D"/"1W", while "1m" (minute)
 * and "1M" (month) stay distinct instruments.
 */
function mapInterval(interval: IntervalId): string {
  if (interval === "1d") return "1D";
  if (interval === "1w") return "1W";
  return interval;
}

function mapStyle(style: ChartStyle): "candles" | "line" | "area" {
  return style === "candle" ? "candles" : style;
}

export function HPPane({ code, symbol }: FunctionPaneProps) {
  // 2026-05-11 hotfix: fall back to a sensible default so palette-cold HP
  // renders price history immediately instead of stalling on "Pick a symbol".
  const effectiveSymbol = symbol || defaultSymbolForFunction(code);
  const [range, setRange] = usePersistentOption<RangeId>(
    "showme.hp-range",
    RANGE_IDS,
    "3M",
  );
  // The engine owns the live timeframe picker; HP keeps the persisted
  // interval to seed the engine and to size the rail/header payload.
  const [interval] = usePersistentOption<IntervalId>(
    "showme.hp-interval",
    INTERVAL_IDS,
    "1d",
  );

  const days = useMemo(() => RANGES.find((r) => r.id === range)!.days, [range]);
  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol: effectiveSymbol,
    params: { days, range, interval, bars: DEFAULT_BARS },
    enabled: !!effectiveSymbol,
  });

  const rows = useMemo(() => decorate(normalizeRows(data?.data)), [data]);
  // S12 HP live-data wiring: HP subscribes to the canonical live quote
  // channel (`useLiveQuote`) so the header strip reports honest transport
  // state (RT LIVE / RECONNECTING / STALE / SNAPSHOT ONLY / OFFLINE) and
  // shows the freshest tick. The chart engine owns its own canvas refresh.
  const liveQuote = useLiveQuote(effectiveSymbol, {
    enabled: !!effectiveSymbol,
  });
  const transportState: TransportState = liveQuote.transportState;
  const isLiveTransport = transportState === "live";
  const isReconnectingTransport =
    transportState === "reconnecting" ||
    transportState === "connecting" ||
    transportState === "stale";
  const isOfflineTransport =
    transportState === "offline" || transportState === "error";
  const isStaleQuote =
    !!liveQuote.snapshot &&
    typeof liveQuote.freshnessMs === "number" &&
    liveQuote.stale;
  const snapshotOnlyTransport =
    state === "ok" && rows.length === 0 && !!liveQuote.snapshot;
  const liveTickPrice = liveQuote.lastTick?.price ?? null;

  const stats = useMemo(() => {
    if (!rows.length) return null;
    const closes = rows
      .map((r) => r.close ?? r.adj_close ?? r.adjClose)
      .filter((v): v is number => v != null);
    if (!closes.length) return null;
    // UA-CRITICAL-01: stack-safe; closes can be 10k+ rows on intraday history.
    const high = maxOf(closes);
    const low = minOf(closes);
    const first = closes[closes.length - 1];
    const last = closes[0];
    const totalPct = first ? ((last - first) / first) * 100 : null;
    return { high, low, totalPct, n: rows.length, last, first };
  }, [rows]);

  const latest = rows[0];
  const prevRow = rows[1];
  const lastClose = latest?.close ?? latest?.adj_close ?? latest?.adjClose ?? null;
  const prevClose = prevRow?.close ?? prevRow?.adj_close ?? prevRow?.adjClose ?? null;
  const dayChange = lastClose != null && prevClose != null ? lastClose - prevClose : null;
  const dayChangePct =
    lastClose != null && prevClose ? ((lastClose - prevClose) / prevClose) * 100 : null;

  const sparkValues = useMemo(() => {
    if (!rows.length) return [];
    const reversed = [...rows].reverse();
    const slice = reversed.slice(-32);
    return slice
      .map((r) => r.close ?? r.adj_close ?? r.adjClose)
      .filter((v): v is number => v != null);
  }, [rows]);

  // 2026-05-20 S03-H: HP backend payload is OHLCV-only. Until a real news
  // source is wired through (provider + cache + i18n), the NEWS rail panel
  // shows an honest "not wired" empty state instead of fabricated headlines.
  // The previously inlined fake-headline helper was deleted in this patch.

  const provider = data?.sources?.[0] ?? "pending";
  // HP wire-truth: the alias now emits company identity + 52-week meta from
  // the winning provider's chart meta (Yahoo). Absent = honest unknown; the
  // rail falls back to range extremes and the strip simply hides the pill.
  const payloadData = data?.data as
    | {
        deep_history?: boolean;
        long_name?: string | null;
        short_name?: string | null;
        exchange?: string | null;
        fifty_two_week_high?: number | null;
        fifty_two_week_low?: number | null;
      }
    | undefined;
  const displayName = payloadData?.long_name ?? payloadData?.short_name ?? undefined;
  const displayExchange = payloadData?.exchange ?? undefined;
  const deepHistory = payloadData?.deep_history === true;
  const week52High =
    typeof payloadData?.fifty_two_week_high === "number" &&
    Number.isFinite(payloadData.fifty_two_week_high)
      ? payloadData.fifty_two_week_high
      : null;
  const week52Low =
    typeof payloadData?.fifty_two_week_low === "number" &&
    Number.isFinite(payloadData.fifty_two_week_low)
      ? payloadData.fifty_two_week_low
      : null;
  const week52 =
    week52High != null && week52Low != null
      ? { high: week52High, low: week52Low }
      : null;
  const sourcesConsidered = (data?.data as
    | { sources_considered?: Array<{ name: string; ok?: boolean; bars_available?: number; first_ts_ms?: number; error?: string }> }
    | undefined)?.sources_considered ?? [];
  const winnerSummary = sourcesConsidered.length > 0
    ? `winner=${provider} · tried ${sourcesConsidered.length} sources (${sourcesConsidered
        .map((s) => `${s.name}${s.ok ? `:${s.bars_available ?? "?"}` : ":x"}`)
        .join(", ")})`
    : `provider=${provider}`;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Historical price${effectiveSymbol ? ` — ${effectiveSymbol}` : ""}`}
          subtitle={
            stats
              ? `${stats.n} bars · range Δ ${stats.totalPct?.toFixed(2)}%`
              : "Pick a symbol"
          }
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Run historical price"
                label="Run"
              />
              <button
                type="button"
                className="btn btn--accent u-btn-24 u-pad-x-10"
                disabled={!rows.length || !effectiveSymbol}
                onClick={() => downloadCsv(effectiveSymbol ?? "data", range, rows)}
                title="Download CSV"
              >
                CSV
              </button>
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={effectiveSymbol} />

        {/* Symbol header strip */}
        <SymbolHeaderStrip
          symbol={effectiveSymbol}
          name={displayName}
          exchange={displayExchange}
          /*
           * S12 HP truth: prefer the live tick price when the transport
           * is actually live (`isLiveTransport`), otherwise fall back to
           * the most-recent historical close so the header doesn't go
           * blank between refreshes. Same rule for change/changePct —
           * recompute against the historical previous close so the chip
           * reflects the freshest available bar instead of staying
           * locked to the candle-frozen value.
           */
          last={isLiveTransport && liveTickPrice != null ? liveTickPrice : lastClose}
          change={
            isLiveTransport && liveTickPrice != null && prevClose != null
              ? liveTickPrice - prevClose
              : dayChange
          }
          changePct={
            isLiveTransport && liveTickPrice != null && prevClose
              ? ((liveTickPrice - prevClose) / prevClose) * 100
              : dayChangePct
          }
          ohlc={latest}
          spark={sparkValues}
          state={state}
          transportState={transportState}
          isReconnecting={isReconnectingTransport}
          isOffline={isOfflineTransport}
          isStale={isStaleQuote}
          snapshotOnly={snapshotOnlyTransport}
        />

        {/*
         * Toolbar — RANGE drives the function payload behind the header
         * stats and the key-level rail. Timeframe / chart type / indicators
         * are owned by the chart engine's own toolbar, so their chip rows
         * (and the chart-instance-bound Compare / PNG export) are gone.
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
            <Empty
              title="Pick a symbol"
              body="HP downloads OHLCV rows for one ticker."
              icon="⌖"
            />
          ) : state === "loading" || state === "idle" ? (
            <div className="u-p-14 u-flex-1">
              <Skeleton height={360} />
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
          ) : rows.length === 0 ? (
            <Empty title="No bars" body={`No HP payload for ${effectiveSymbol}.`} />
          ) : (
            <ChartLayout
              chartId={code.toUpperCase()}
              interval={interval}
              stats={stats}
              week52={week52}
              rows={rows}
              symbol={effectiveSymbol ?? ""}
            />
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="O"
            value={fmtNum(latest?.open)}
            tone="neutral"
          />
          <StatusSection label="H" value={fmtNum(latest?.high)} tone="positive" />
          <StatusSection label="L" value={fmtNum(latest?.low)} tone="negative" />
          <StatusSection label="C" value={fmtNum(latest?.close)} tone="neutral" />
          <StatusSection
            label="V"
            value={fmtVolume(latest?.volume)}
            tone="muted"
          />
          <StatusDivider />
          <StatusSection
            label="provider"
            value={
              sourcesConsidered.length > 1
                ? `${provider} · deepest of ${sourcesConsidered.length}`
                : provider
            }
            tone="muted"
            title={winnerSummary}
          />
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
          <StatusSection label="range" value={range} tone="muted" />
          <StatusSection label="resolution" value={interval} tone="muted" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function SymbolHeaderStrip({
  symbol,
  name,
  exchange,
  last,
  change,
  changePct,
  ohlc,
  spark,
  state,
  transportState,
  isReconnecting,
  isOffline,
  isStale,
  snapshotOnly,
}: {
  symbol?: string;
  name?: string;
  exchange?: string;
  last: number | null;
  change: number | null;
  changePct: number | null;
  ohlc?: HPRow;
  spark: number[];
  state: string;
  /**
   * S12 HP truth: the strip only shows live-session wording when the
   * canonical `useLiveQuote` transport reports it. The historical
   * `useFunction` `state === "ok"` is NOT the same as a live channel
   * being open and ticking. Without these props HP fell back to the
   * misleading "real-time session" badge any time the historical fetch
   * succeeded — including when the WebSocket bridge was offline.
   */
  transportState: TransportState;
  isReconnecting: boolean;
  isOffline: boolean;
  isStale: boolean;
  snapshotOnly: boolean;
}) {
  if (!symbol) return null;
  const isLive = transportState === "live";
  return (
    <div style={symbolStripStyle}>
      <div className="u-flex u-items-center u-gap-12 u-min-w-0">
        <span style={symbolTickerStyle}>{symbol}</span>
        {name && (
          <span style={symbolNameStyle} title={name}>
            {name}
          </span>
        )}
        {exchange && (
          <Pill tone="muted" variant="soft" withDot={false}>
            {exchange}
          </Pill>
        )}
        {state === "ok" && isLive && (
          <span data-testid="hp-transport-pill" data-state="live">
            <Pill tone="positive" variant="soft">RT LIVE</Pill>
          </span>
        )}
        {state === "ok" && isReconnecting && !isLive && (
          <span data-testid="hp-transport-pill" data-state={transportState}>
            <Pill tone="warn" variant="soft">
              {transportState === "stale" ? "STALE" : "RECONNECTING"}
            </Pill>
          </span>
        )}
        {state === "ok" && isOffline && (
          <span data-testid="hp-transport-pill" data-state="offline">
            <Pill tone="negative" variant="soft">OFFLINE</Pill>
          </span>
        )}
        {snapshotOnly && (
          <span data-testid="hp-snapshot-only">
            <Pill tone="warn" variant="soft">SNAPSHOT ONLY</Pill>
          </span>
        )}
        {isStale && !isOffline && (
          <span data-testid="hp-stale">
            <Pill tone="warn" variant="soft">STALE</Pill>
          </span>
        )}
      </div>
      <div className="u-flex u-items-center u-gap-14">
        <span style={lastPriceStyle}>{fmtNum(last)}</span>
        {changePct != null && (
          <DeltaChip value={changePct} format="percent" fractionDigits={2} />
        )}
        {change != null && (
          <span style={changeAbsStyle}>
            {change >= 0 ? "+" : ""}
            {fmtNum(change)}
          </span>
        )}
        {ohlc && (
          <div style={ohlcMiniStyle}>
            <span>
              <em>O</em>
              {fmtNum(ohlc.open)}
            </span>
            <span>
              <em>H</em>
              {fmtNum(ohlc.high)}
            </span>
            <span>
              <em>L</em>
              {fmtNum(ohlc.low)}
            </span>
            <span>
              <em>C</em>
              {fmtNum(ohlc.close)}
            </span>
          </div>
        )}
        {spark.length > 1 && (
          <Sparkline
            values={spark}
            width={88}
            height={26}
            tone={(changePct ?? 0) >= 0 ? "positive" : "negative"}
          />
        )}
      </div>
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

function ChartLayout({
  chartId,
  rows,
  interval,
  stats,
  week52,
  symbol,
}: {
  chartId: string;
  rows: Array<HPRow & { _change?: number; _changePct?: number }>;
  interval: IntervalId;
  stats: { high: number; low: number; totalPct: number | null; n: number; last: number; first: number } | null;
  week52: { high: number; low: number } | null;
  symbol: string;
}) {
  return (
    <div style={chartLayoutStyle}>
      <div style={chartCanvasWrapStyle}>
        <ResizableChartFrame
          storageId={`${chartId}.price`}
          defaultHeight={{ vh: 0.34, max: 420, min: 240 }}
          minWidth={420}
          minHeight={280}
          maxHeight={1200}
          style={chartSurfaceStyle}
          ariaLabel="Resize price chart"
        >
          <Chart
            symbol={symbol}
            fill
            initialInterval={mapInterval(interval)}
            initialType={mapStyle(HP_CHART_STYLE)}
          />
        </ResizableChartFrame>
      </div>
      <RightRail stats={stats} week52={week52} rows={rows} symbol={symbol} />
    </div>
  );
}

function RightRail({
  stats,
  week52,
  rows,
  symbol,
}: {
  stats: { high: number; low: number; totalPct: number | null; n: number; last: number; first: number } | null;
  week52: { high: number; low: number } | null;
  rows: Array<HPRow & { _change?: number; _changePct?: number }>;
  symbol: string;
}) {
  const indicators = useMemo(() => computeIndicators(rows), [rows]);
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
          value={indicators.rsi != null ? indicators.rsi.toFixed(1) : "—"}
          tone={
            indicators.rsi == null
              ? "neutral"
              : indicators.rsi > 70
                ? "negative"
                : indicators.rsi < 30
                  ? "positive"
                  : "neutral"
          }
          spark={indicators.rsiSpark}
        />
        <IndicatorRow
          label="MACD"
          value={indicators.macd != null ? indicators.macd.toFixed(3) : "—"}
          tone={
            indicators.macd == null
              ? "neutral"
              : indicators.macd >= 0
                ? "positive"
                : "negative"
          }
          spark={indicators.macdSpark}
        />
        <IndicatorRow
          label="ATR(14)"
          value={indicators.atr != null ? indicators.atr.toFixed(2) : "—"}
          tone="accent"
          spark={indicators.atrSpark}
        />
      </RailSection>
      <RailSection title={`News · ${symbol}`}>
        {/* S03-H: news feed not yet wired to a real provider.
            We show an honest empty/not-wired state instead of
            fabricating template headlines. */}
        <div
          data-testid="hp-news-empty"
          style={newsEmptyStyle}
        >
          <span style={newsEmptyTitleStyle}>News feed not wired</span>
          <span style={newsEmptyBodyStyle}>
            HP does not yet pipe a real news provider for this symbol.
            This panel will populate once a verified source is connected.
          </span>
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

function normalizeRows(payload: unknown): HPRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as HPRow[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    // `ohlcv` is the alias contract's canonical field (hp_seed
    // output_contract.must_have); bars/rows are the same array under legacy
    // aliases. Reading all three keeps HP rendering if the envelope trims
    // one of the duplicates.
    const items =
      o.ohlcv ?? o.bars ?? o.rows ?? o.history ?? o.items ?? o.candles ?? null;
    if (Array.isArray(items)) return items as HPRow[];
  }
  return [];
}

function decorate(
  rows: HPRow[],
): Array<HPRow & { _change?: number; _changePct?: number }> {
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

function macdBundle(closes: number[]): {
  macd: (number | null)[];
  signal: (number | null)[];
  hist: (number | null)[];
} {
  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const macd = closes.map((_, i) =>
    ema12[i] != null && ema26[i] != null
      ? (ema12[i] as number) - (ema26[i] as number)
      : null,
  );
  const firstIdx = macd.findIndex((v) => v != null);
  const signal: (number | null)[] = new Array(closes.length).fill(null);
  if (firstIdx >= 0) {
    const signalTail = ema(macd.slice(firstIdx) as number[], 9);
    signalTail.forEach((value, i) => {
      if (value != null) signal[firstIdx + i] = value;
    });
  }
  const hist = macd.map((value, i) =>
    value != null && signal[i] != null ? value - (signal[i] as number) : null,
  );
  return { macd, signal, hist };
}

/**
 * True ATR — Wilder-smoothed average of the true range:
 *   TR = max(H−L, |H−prevC|, |L−prevC|)
 * Aligned with the backend TECH function's definition (ewm alpha =
 * 1/period, seeded on the first TR). The pre-fix HP "ATR" was the mean
 * absolute close change — no high/low, no gaps — and understated ranges.
 */
function trueAtrSeries(
  rows: Array<HPRow & { _change?: number; _changePct?: number }>,
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
    const close = row.close ?? row.adj_close ?? row.adjClose;
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

function computeIndicators(
  rows: Array<HPRow & { _change?: number; _changePct?: number }>,
) {
  const closes = rows
    .map((r) => r.close ?? r.adj_close ?? r.adjClose)
    .filter((v): v is number => v != null && Number.isFinite(v));
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
  const macd = macdBundle(closes);
  const atrAll = trueAtrSeries(rows, 14);

  return {
    rsi: lastDefined(rsiAll),
    macd: lastDefined(macd.macd),
    atr: lastDefined(atrAll),
    rsiSpark: rsiAll.filter((v): v is number => v != null).slice(-24),
    macdSpark: macd.macd.filter((v): v is number => v != null).slice(-24),
    atrSpark: atrAll.filter((v): v is number => v != null).slice(-24),
  };
}

// Fabricated-news helper removed in S03-H — HP no longer manufactures
// headlines. See the "News feed not wired" empty state inside `RightRail`
// and the guard tests in HP.test.tsx for the contract this patch enforces.

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

const symbolTickerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xl)",
  fontWeight: 700,
  letterSpacing: "0.04em",
  color: "var(--text-display)",
};

const symbolNameStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  color: "var(--text-secondary)",
  maxWidth: 280,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
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
// Re-resizable's own handle wrappers anchor against this same box, so
// the bottom-right grip sits flush against the chart canvas with no gap.
const chartSurfaceStyle: CSSProperties = {
  position: "relative",
  boxSizing: "border-box",
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  borderRadius: "var(--radius-md)",
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

const newsEmptyStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: "10px 2px",
};

const newsEmptyTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
};

const newsEmptyBodyStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--text-secondary)",
  lineHeight: 1.4,
};
