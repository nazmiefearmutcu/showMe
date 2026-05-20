/**
 * HP — Historical price (Bloomberg HP<GO> analogue).
 *
 * Bloomberg-grade chart panel:
 *   - symbol header strip (price, delta, OHLC, RT badge)
 *   - timeframe pill row + chart-style + indicators dropdown + compare + export
 *   - chart canvas (lightweight-charts) with crosshair readout
 *   - right rail: KEY LEVELS · INDICATORS · NEWS
 *   - footer: OHLC value list + provider + cache indicator
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MutableRefObject,
} from "react";
import {
  type CandlestickData,
  type HistogramData,
  type IChartApi,
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
import { buildCsv, type HPRow } from "./HP.csv";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";
import { alpha, useChartPalette, type ChartPalette } from "@/lib/chart-palette";

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

const INDICATOR_PRESETS = ["SMA(20)", "EMA(50)", "RSI(14)", "MACD", "BB(20,2)"];

const MAX_COMPARE = 3;
/**
 * Compare overlay colors (Session 16 BugHunt) — derived from the live
 * chart palette so Papyrus / Matrix / custom-slot presets actually
 * recolor the chip dots, chip borders, and compare-series strokes
 * instead of leaking the old dark-mode hex literals.
 */
function compareColorsFromPalette(palette: ChartPalette): [string, string, string, string] {
  return [palette.accent, palette.warn, palette.positive, palette.negative];
}
const EQUITY_PEERS = ["MSFT", "NVDA", "AAPL", "GOOG", "AMZN", "TSLA", "META", "AMD", "SPY", "QQQ"];
const CRYPTO_PEERS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"];
const FX_PEERS = ["EURUSD", "GBPUSD", "USDJPY", "DXY"];

function suggestPeers(primary: string | undefined): string[] {
  if (!primary) return EQUITY_PEERS.slice(0, 5);
  const sym = primary.toUpperCase();
  const isCrypto = /USDT$|USD$|^BTC|^ETH|^SOL|^DOGE/.test(sym);
  const isFx = /=X$|^[A-Z]{6}$|^DXY$/.test(sym);
  const pool = isCrypto ? CRYPTO_PEERS : isFx ? FX_PEERS : EQUITY_PEERS;
  return pool.filter((p) => p !== sym).slice(0, 5);
}

function usePersistentSymbols(
  key: string,
  max: number,
): [string[], React.Dispatch<React.SetStateAction<string[]>>] {
  const [value, setValue] = useState<string[]>(() => {
    if (typeof localStorage === "undefined") return [];
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((s): s is string => typeof s === "string" && s.trim().length > 0)
        .map((s) => s.trim().toUpperCase())
        .slice(0, max);
    } catch {
      return [];
    }
  });
  useEffect(() => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(key, JSON.stringify(value));
    }
  }, [key, value]);
  return [value, setValue];
}

interface ComparedSeries {
  symbol: string;
  rows: HPRow[];
  state: "idle" | "loading" | "ok" | "error";
  color: string;
}

interface CrosshairState {
  price: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  time: string | null;
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
  const [interval, setInterval] = usePersistentOption<IntervalId>(
    "showme.hp-interval",
    INTERVAL_IDS,
    "1d",
  );
  const [depth, setDepth] = usePersistentOption<DepthId>(
    "showme.hp-depth",
    DEPTH_IDS,
    "1000",
  );
  const [chartStyle, setChartStyle] = useState<ChartStyle>("candle");
  const [activeIndicators, setActiveIndicators] = useState<string[]>([
    "SMA(20)",
    "EMA(50)",
  ]);
  const [indicatorOpen, setIndicatorOpen] = useState(false);
  const [comparedSymbols, setComparedSymbols] = usePersistentSymbols(
    `showme.hp-compare.${code}`,
    MAX_COMPARE,
  );
  const [compareOpen, setCompareOpen] = useState(false);

  const days = useMemo(() => RANGES.find((r) => r.id === range)!.days, [range]);
  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol: effectiveSymbol,
    params: { days, range, interval, bars: Number(depth) },
    enabled: !!effectiveSymbol,
  });

  const compareParams = { days, range, interval, bars: Number(depth) };
  const compareA = useFunction<unknown>({
    code,
    symbol: comparedSymbols[0] ?? "",
    params: compareParams,
    enabled: !!comparedSymbols[0] && !!effectiveSymbol,
  });
  const compareB = useFunction<unknown>({
    code,
    symbol: comparedSymbols[1] ?? "",
    params: compareParams,
    enabled: !!comparedSymbols[1] && !!effectiveSymbol,
  });
  const compareC = useFunction<unknown>({
    code,
    symbol: comparedSymbols[2] ?? "",
    params: compareParams,
    enabled: !!comparedSymbols[2] && !!effectiveSymbol,
  });

  const rows = useMemo(() => decorate(normalizeRows(data?.data)), [data]);
  // Theme-aware compare overlay palette — replaces the prior dark-mode
  // hex literal so Papyrus / Matrix / custom slots track correctly.
  const compareChartPalette = useChartPalette();
  const compareColors = useMemo(
    () => compareColorsFromPalette(compareChartPalette),
    [compareChartPalette],
  );

  const comparedSeries = useMemo<ComparedSeries[]>(() => {
    const slots = [compareA, compareB, compareC];
    return comparedSymbols
      .map((sym, idx) => {
        const slot = slots[idx];
        return slot
          ? {
              symbol: sym,
              rows: normalizeRows(slot.data?.data),
              state: slot.state,
              color: compareColors[(idx + 1) % compareColors.length],
            }
          : null;
      })
      .filter((s): s is ComparedSeries => s !== null);
  }, [comparedSymbols, compareA, compareB, compareC, compareColors]);

  const addCompareSymbol = useCallback(
    (raw: string) => {
      const next = raw.trim().toUpperCase();
      if (!next || next === effectiveSymbol?.toUpperCase()) return;
      setComparedSymbols((prev) => {
        if (prev.includes(next)) return prev;
        if (prev.length >= MAX_COMPARE) return prev;
        return [...prev, next];
      });
    },
    [effectiveSymbol, setComparedSymbols],
  );
  const removeCompareSymbol = useCallback(
    (sym: string) => {
      setComparedSymbols((prev) => prev.filter((s) => s !== sym));
    },
    [setComparedSymbols],
  );

  const chartApiRef = useRef<IChartApi | null>(null);
  const handleExportPng = useCallback(() => {
    const chart = chartApiRef.current;
    if (!chart) return;
    const canvas = chart.takeScreenshot();
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${effectiveSymbol ?? "chart"}-${range}-${new Date()
        .toISOString()
        .slice(0, 10)}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 0);
    });
  }, [effectiveSymbol, range]);

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

  const newsItems = useMemo(() => buildMockNews(effectiveSymbol), [effectiveSymbol]);

  const provider = data?.sources?.[0] ?? "pending";
  const cached = !!(data as { cached?: boolean } | undefined)?.cached;
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
          name={(data?.data as { longName?: string; shortName?: string } | undefined)?.longName}
          exchange={(data?.data as { exchange?: string } | undefined)?.exchange}
          last={lastClose}
          change={dayChange}
          changePct={dayChangePct}
          ohlc={latest}
          spark={sparkValues}
          state={state}
        />

        {/* Toolbar row */}
        <ChartToolbar
          range={range}
          onRangeChange={setRange}
          interval={interval}
          onIntervalChange={setInterval}
          depth={depth}
          onDepthChange={setDepth}
          chartStyle={chartStyle}
          onChartStyleChange={setChartStyle}
          activeIndicators={activeIndicators}
          indicatorOpen={indicatorOpen}
          onIndicatorOpen={setIndicatorOpen}
          onIndicatorToggle={(name) =>
            setActiveIndicators((prev) =>
              prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name],
            )
          }
          comparedSymbols={comparedSymbols}
          compareOpen={compareOpen}
          onCompareOpen={setCompareOpen}
          onCompareAdd={addCompareSymbol}
          onCompareRemove={removeCompareSymbol}
          comparePeerSuggestions={suggestPeers(effectiveSymbol)}
          onExportPng={handleExportPng}
          canExport={!!rows.length}
        />

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
              rows={rows}
              interval={interval}
              chartStyle={chartStyle}
              activeIndicators={activeIndicators}
              stats={stats}
              news={newsItems}
              symbol={effectiveSymbol ?? ""}
              comparedSeries={comparedSeries}
              chartApiRef={chartApiRef}
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
}) {
  if (!symbol) return null;
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
        {state === "ok" && (
          <Pill tone="positive" variant="soft">
            RT SESSION
          </Pill>
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
            {change.toFixed(2)}
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

function ChartToolbar({
  range,
  onRangeChange,
  interval,
  onIntervalChange,
  depth,
  onDepthChange,
  chartStyle,
  onChartStyleChange,
  activeIndicators,
  indicatorOpen,
  onIndicatorOpen,
  onIndicatorToggle,
  comparedSymbols,
  compareOpen,
  onCompareOpen,
  onCompareAdd,
  onCompareRemove,
  comparePeerSuggestions,
  onExportPng,
  canExport,
}: {
  range: RangeId;
  onRangeChange: (id: RangeId) => void;
  interval: IntervalId;
  onIntervalChange: (id: IntervalId) => void;
  depth: DepthId;
  onDepthChange: (id: DepthId) => void;
  chartStyle: ChartStyle;
  onChartStyleChange: (style: ChartStyle) => void;
  activeIndicators: string[];
  indicatorOpen: boolean;
  onIndicatorOpen: (open: boolean) => void;
  onIndicatorToggle: (name: string) => void;
  comparedSymbols: string[];
  compareOpen: boolean;
  onCompareOpen: (open: boolean) => void;
  onCompareAdd: (sym: string) => void;
  onCompareRemove: (sym: string) => void;
  comparePeerSuggestions: string[];
  onExportPng: () => void;
  canExport: boolean;
}) {
  return (
    <div style={toolbarRowStyle}>
      <div style={toolbarSegmentStyle}>
        <span style={toolbarLabelStyle}>TIMEFRAME</span>
        <PillRow
          items={INTERVALS.map((i) => ({ id: i.id, label: i.label }))}
          active={interval}
          onChange={(id) => onIntervalChange(id as IntervalId)}
        />
      </div>
      <div style={toolbarSegmentStyle}>
        <span style={toolbarLabelStyle}>RANGE</span>
        <PillRow
          items={RANGES.map((r) => ({ id: r.id, label: r.label }))}
          active={range}
          onChange={(id) => onRangeChange(id as RangeId)}
        />
      </div>
      <div style={toolbarSegmentStyle}>
        <span style={toolbarLabelStyle}>STYLE</span>
        <PillRow
          items={CHART_STYLES}
          active={chartStyle}
          onChange={(id) => onChartStyleChange(id as ChartStyle)}
        />
      </div>
      <div style={toolbarSegmentStyle}>
        <span style={toolbarLabelStyle}>BARS</span>
        <PillRow
          items={DEPTHS.map((d) => ({ id: d.id, label: d.label }))}
          active={depth}
          onChange={(id) => onDepthChange(id as DepthId)}
        />
      </div>
      <div className="u-position-relative">
        <button
          type="button"
          onClick={() => onIndicatorOpen(!indicatorOpen)}
          style={toolbarButtonStyle}
          title="Indicators"
        >
          Indicators
          <span className="hp-ind-count">
            ({activeIndicators.length})
          </span>
        </button>
        {indicatorOpen && (
          <div style={indicatorMenuStyle}>
            {INDICATOR_PRESETS.map((name) => {
              const active = activeIndicators.includes(name);
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => onIndicatorToggle(name)}
                  style={{
                    ...indicatorMenuItemStyle,
                    background: active ? "var(--accent-soft)" : "transparent",
                    color: active ? "var(--accent)" : "var(--text-secondary)",
                  }}
                >
                  <span className="hp-ind-check">
                    {active ? "✓" : ""}
                  </span>
                  {name}
                </button>
              );
            })}
          </div>
        )}
      </div>
      <ComparePopup
        comparedSymbols={comparedSymbols}
        open={compareOpen}
        onOpen={onCompareOpen}
        onAdd={onCompareAdd}
        onRemove={onCompareRemove}
        suggestions={comparePeerSuggestions}
      />
      <button
        type="button"
        style={toolbarIconButtonStyle}
        title={canExport ? "Export PNG" : "No chart data to export"}
        aria-label="Export chart as PNG"
        onClick={() => {
          if (canExport) onExportPng();
        }}
        disabled={!canExport}
      >
        ⇪
      </button>
    </div>
  );
}

function ComparePopup({
  comparedSymbols,
  open,
  onOpen,
  onAdd,
  onRemove,
  suggestions,
}: {
  comparedSymbols: string[];
  open: boolean;
  onOpen: (open: boolean) => void;
  onAdd: (sym: string) => void;
  onRemove: (sym: string) => void;
  suggestions: string[];
}) {
  const [draft, setDraft] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const full = comparedSymbols.length >= MAX_COMPARE;
  // Session 16 BugHunt: compare chip dots / borders must follow the
  // active chart palette. The popup is a sibling of HPPane so it cannot
  // inherit the parent's compareColors memo — recompute locally.
  const popupPalette = useChartPalette();
  const compareColors = useMemo(
    () => compareColorsFromPalette(popupPalette),
    [popupPalette],
  );

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) onOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open, onOpen]);

  const submit = () => {
    if (!draft.trim() || full) return;
    onAdd(draft);
    setDraft("");
  };

  return (
    <div ref={containerRef} className="u-position-relative">
      <button
        type="button"
        onClick={() => onOpen(!open)}
        style={toolbarButtonStyle}
        title="Compare with peer symbols"
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid="hp-compare-toggle"
      >
        Compare {comparedSymbols.length > 0 ? `(${comparedSymbols.length})` : "+"}
      </button>
      {open && (
        <div style={comparePopupStyle} role="dialog" aria-label="Compare symbols">
          <div style={comparePopupHeaderStyle}>
            <span>COMPARE OVERLAY</span>
            <span style={comparePopupHintStyle}>
              {comparedSymbols.length}/{MAX_COMPARE} · % rebased
            </span>
          </div>
          {comparedSymbols.length > 0 && (
            <div style={compareChipRowStyle}>
              {comparedSymbols.map((s, idx) => (
                <span
                  key={s}
                  style={{
                    ...compareChipStyle,
                    borderColor: compareColors[(idx + 1) % compareColors.length],
                  }}
                >
                  <span
                    aria-hidden
                    style={{
                      ...compareChipDotStyle,
                      background: compareColors[(idx + 1) % compareColors.length],
                    }}
                  />
                  <span>{s}</span>
                  <button
                    type="button"
                    onClick={() => onRemove(s)}
                    style={compareChipRemoveStyle}
                    aria-label={`Remove ${s} from compare`}
                    title={`Remove ${s}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            style={compareFormStyle}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={full ? "Max 3 peers" : "Add peer (e.g. MSFT)"}
              style={compareInputStyle}
              disabled={full}
              aria-label="Peer symbol to compare"
              data-testid="hp-compare-input"
            />
            <button
              type="submit"
              style={compareAddBtnStyle}
              disabled={full || !draft.trim()}
              data-testid="hp-compare-add"
            >
              Add
            </button>
          </form>
          {suggestions.length > 0 && (
            <>
              <div style={comparePopupSubLabelStyle}>SUGGESTED</div>
              <div style={compareSuggestionRowStyle}>
                {suggestions
                  .filter((s) => !comparedSymbols.includes(s))
                  .slice(0, 5)
                  .map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => onAdd(s)}
                      style={compareSuggestionBtnStyle}
                      disabled={full}
                      data-testid={`hp-compare-suggest-${s}`}
                    >
                      {s}
                    </button>
                  ))}
              </div>
            </>
          )}
        </div>
      )}
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
  chartStyle,
  activeIndicators,
  stats,
  news,
  symbol,
  comparedSeries,
  chartApiRef,
}: {
  chartId: string;
  rows: Array<HPRow & { _change?: number; _changePct?: number }>;
  interval: string;
  chartStyle: ChartStyle;
  activeIndicators: string[];
  stats: { high: number; low: number; totalPct: number | null; n: number; last: number; first: number } | null;
  news: { headline: string; ts: string }[];
  symbol: string;
  comparedSeries: ComparedSeries[];
  chartApiRef: MutableRefObject<IChartApi | null>;
}) {
  const [crosshair, setCrosshair] = useState<CrosshairState>({
    price: null,
    open: null,
    high: null,
    low: null,
    close: null,
    volume: null,
    time: null,
  });
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
          <PriceChart
            chartId={chartId}
            rows={rows}
            interval={interval}
            chartStyle={chartStyle}
            activeIndicators={activeIndicators}
            onCrosshair={setCrosshair}
            comparedSeries={comparedSeries}
            chartApiRef={chartApiRef}
          />
          <CrosshairReadout state={crosshair} />
        </ResizableChartFrame>
      </div>
      <RightRail stats={stats} rows={rows} news={news} symbol={symbol} />
    </div>
  );
}

function CrosshairReadout({ state }: { state: CrosshairState }) {
  if (state.price == null) return null;
  return (
    <div style={crosshairBoxStyle}>
      <div style={crosshairRowStyle}>
        <span style={crosshairLabelStyle}>PRICE</span>
        <span style={crosshairValueStyle}>{fmtNum(state.price)}</span>
      </div>
      {state.volume != null && (
        <div style={crosshairRowStyle}>
          <span style={crosshairLabelStyle}>VOL</span>
          <span style={crosshairValueStyle}>{fmtVolume(state.volume)}</span>
        </div>
      )}
      {state.time && (
        <div style={crosshairRowStyle}>
          <span style={crosshairLabelStyle}>TIME</span>
          <span style={crosshairValueStyle}>{state.time}</span>
        </div>
      )}
    </div>
  );
}

function RightRail({
  stats,
  rows,
  news,
  symbol,
}: {
  stats: { high: number; low: number; totalPct: number | null; n: number; last: number; first: number } | null;
  rows: Array<HPRow & { _change?: number; _changePct?: number }>;
  news: { headline: string; ts: string }[];
  symbol: string;
}) {
  const closes = useMemo(
    () =>
      rows
        .map((r) => r.close ?? r.adj_close ?? r.adjClose)
        .filter((v): v is number => v != null),
    [rows],
  );
  const indicators = useMemo(() => computeIndicators(closes), [closes]);
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

function PriceChart({
  chartId: _chartId,
  rows,
  interval,
  chartStyle,
  activeIndicators,
  onCrosshair,
  comparedSeries,
  chartApiRef,
}: {
  chartId: string;
  rows: Array<HPRow & { _change?: number; _changePct?: number }>;
  interval: string;
  chartStyle: ChartStyle;
  activeIndicators: string[];
  onCrosshair: (state: CrosshairState) => void;
  comparedSeries: ComparedSeries[];
  chartApiRef: MutableRefObject<IChartApi | null>;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const palette = useChartPalette();
  const chartRows = useMemo(
    () =>
      [...rows]
        .filter(
          (row) =>
            row.open != null &&
            row.high != null &&
            row.low != null &&
            row.close != null,
        )
        .sort(
          (a, b) =>
            new Date(a.date ?? a.ts ?? "").getTime() -
            new Date(b.date ?? b.ts ?? "").getTime(),
        ),
    [rows],
  );
  const compareMode = comparedSeries.some((s) => s.rows.length > 0);

  useEffect(() => {
    const el = hostRef.current;
    if (!el || chartRows.length < 2) return;
    const size = measureChartElement(el);
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

    if (compareMode) {
      // Rebased % overlay mode: primary becomes a line, peers each get a line,
      // all sharing the same Y-axis showing % change from each series' first bar.
      const primaryLine = chart.addLineSeries({
        color: palette.accent,
        lineWidth: 2,
        priceLineVisible: false,
        priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(2)}%`, minMove: 0.01 },
      });
      primaryLine.setData(rebaseToPct(chartRows));

      comparedSeries.forEach((s) => {
        if (!s.rows.length) return;
        const sorted = [...s.rows]
          .filter((r) => r.close != null || r.adj_close != null || r.adjClose != null)
          .sort(
            (a, b) =>
              new Date(a.date ?? a.ts ?? "").getTime() -
              new Date(b.date ?? b.ts ?? "").getTime(),
          );
        if (sorted.length < 2) return;
        const peerLine = chart.addLineSeries({
          color: s.color,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          title: s.symbol,
        });
        peerLine.setData(rebaseToPct(sorted));
      });
    } else {
      if (chartStyle === "candle") {
        const candles = chart.addCandlestickSeries({
          upColor: palette.positive,
          downColor: palette.negative,
          borderUpColor: palette.positive,
          borderDownColor: palette.negative,
          wickUpColor: palette.positive,
          wickDownColor: palette.negative,
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
      } else if (chartStyle === "line") {
        const line = chart.addLineSeries({
          color: palette.accent,
          lineWidth: 2,
          priceLineVisible: false,
        });
        line.setData(
          chartRows.map<LineData>((row) => ({
            time: chartTime(row.date ?? row.ts),
            value: Number(row.close),
          })),
        );
      } else {
        const area = chart.addAreaSeries({
          lineColor: palette.accent,
          topColor: alpha(palette.accent, 0.32),
          bottomColor: alpha(palette.accent, 0.02),
          lineWidth: 2,
        });
        area.setData(
          chartRows.map<LineData>((row) => ({
            time: chartTime(row.date ?? row.ts),
            value: Number(row.close),
          })),
        );
      }

      const volume = chart.addHistogramSeries({
        priceScaleId: "volume",
        color: palette.volNeutral,
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
            Number(row.close) >= Number(row.open) ? palette.volPos : palette.volNeg,
        })),
      );

      // Optional MA overlays driven by active indicator chips.
      const closes = chartRows.map((r) => Number(r.close));
      const indicatorColors = [palette.accent, palette.positive, palette.warn, palette.negative];
      activeIndicators.forEach((name, idx) => {
        const m = name.match(/(SMA|EMA)\((\d+)\)/);
        if (!m) return;
        const period = Number(m[2]);
        const series = chart.addLineSeries({
          color: indicatorColors[idx % indicatorColors.length],
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        const values = m[1] === "SMA" ? sma(closes, period) : ema(closes, period);
        series.setData(
          values
            .map((v, i) =>
              v == null
                ? null
                : ({
                    time: chartTime(chartRows[i].date ?? chartRows[i].ts),
                    value: v,
                  } as LineData),
            )
            .filter((p): p is LineData => p !== null),
        );
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
      const seriesValues = Array.from(param.seriesData.values())[0] as
        | { close?: number; open?: number; high?: number; low?: number; value?: number }
        | undefined;
      const t = param.time;
      const tStr =
        typeof t === "number"
          ? new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")
          : String(t);
      const idx = chartRows.findIndex(
        (r) => chartTime(r.date ?? r.ts) === param.time,
      );
      const row = idx >= 0 ? chartRows[idx] : null;
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
    chartApiRef.current = chart;
    focusLatestBars(chart, chartRows.length, size.width);
    const ro = new ResizeObserver(() => {
      resizeChartToElement(chart, el);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      chartApiRef.current = null;
    };
  }, [chartRows, interval, chartStyle, activeIndicators, onCrosshair, compareMode, comparedSeries, chartApiRef, palette]);

  if (chartRows.length < 2) return null;
  return (
    <>
      <div style={chartFitToolbarStyle}>
        <span>{chartRows.length.toLocaleString()} bars loaded</span>
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
              const el = hostRef.current;
              if (chartRef.current && el)
                focusLatestBars(chartRef.current, chartRows.length, el.clientWidth);
            }}
          >
            Last
          </button>
        </div>
      </div>
      <div ref={hostRef} style={chartHostStyle} />
    </>
  );
}

// ----- helpers -----

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

function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
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

function rebaseToPct(rows: HPRow[]): LineData[] {
  const out: LineData[] = [];
  let base: number | null = null;
  for (const r of rows) {
    const close = (r.close ?? r.adj_close ?? r.adjClose) as number | undefined;
    if (close == null || !Number.isFinite(close)) continue;
    if (base == null) {
      if (close === 0) continue;
      base = close;
    }
    out.push({
      time: chartTime(r.date ?? r.ts),
      value: ((close - base) / base) * 100,
    });
  }
  return out;
}

function computeIndicators(closes: number[]) {
  if (closes.length < 15) {
    return {
      rsi: null,
      macd: null,
      atr: null,
      rsiSpark: [] as number[],
      macdSpark: [] as number[],
      atrSpark: [] as number[],
    };
  }
  // RSI(14)
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

  // MACD: EMA12 - EMA26
  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const macdSeries = closes.map((_, i) =>
    ema12[i] != null && ema26[i] != null ? (ema12[i] as number) - (ema26[i] as number) : null,
  );
  const macd = macdSeries[macdSeries.length - 1];

  // ATR(14): simple range mean
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
    macd: typeof macd === "number" ? macd : null,
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
    { headline: `${base} prints fresh session high on volume spike`, ts: "12 min" },
    { headline: `Sector rotation lifts ${base} ahead of macro print`, ts: "47 min" },
    { headline: `${base} options skew turns bullish into expiry`, ts: "1 h" },
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

const symbolTickerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 18,
  fontWeight: 700,
  letterSpacing: "0.04em",
  color: "var(--text-display)",
};

const symbolNameStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--text-secondary)",
  maxWidth: 280,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
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

const indicatorMenuStyle: CSSProperties = {
  position: "absolute",
  top: 30,
  right: 0,
  zIndex: 30,
  width: 180,
  background: "var(--surface-3)",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-md)",
  boxShadow: "var(--shadow-elev-2)",
  padding: 4,
  display: "grid",
  gap: 1,
};

const indicatorMenuItemStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 8px",
  border: "none",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  cursor: "default",
  textAlign: "left",
};

const comparePopupStyle: CSSProperties = {
  position: "absolute",
  top: 30,
  right: 0,
  zIndex: 30,
  width: 240,
  background: "var(--surface-3)",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-md)",
  boxShadow: "var(--shadow-elev-2)",
  padding: 10,
  display: "grid",
  gap: 8,
};

const comparePopupHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const comparePopupHintStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontWeight: 500,
};

const comparePopupSubLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  marginTop: 2,
};

const compareChipRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 4,
};

const compareChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "3px 6px",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-primary)",
};

const compareChipDotStyle: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: "50%",
  display: "inline-block",
};

const compareChipRemoveStyle: CSSProperties = {
  border: "none",
  background: "transparent",
  color: "var(--text-mute)",
  fontSize: 12,
  lineHeight: 1,
  padding: 0,
  marginLeft: 2,
  cursor: "default",
};

const compareFormStyle: CSSProperties = {
  display: "flex",
  gap: 4,
};

const compareInputStyle: CSSProperties = {
  flex: 1,
  height: 24,
  padding: "0 8px",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  textTransform: "uppercase",
};

const compareAddBtnStyle: CSSProperties = {
  height: 24,
  padding: "0 10px",
  background: "var(--accent)",
  color: "var(--accent-on)",
  border: "none",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  fontWeight: 600,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  cursor: "default",
};

const compareSuggestionRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 4,
};

const compareSuggestionBtnStyle: CSSProperties = {
  height: 22,
  padding: "0 6px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.04em",
  cursor: "default",
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
