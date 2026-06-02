import { useEffect, useMemo, useState } from "react";
import { Pill, Skeleton, Sparkline } from "@/design-system";
import { navigate } from "@/lib/router";
import { useSentimentStore } from "@/lib/sentiment-store";
import type { FunctionEntry } from "@/lib/sidecar";
import { useAppStore } from "@/lib/store";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { useLiveQuotes, type QuoteView } from "@/lib/market-data";
import { formatPrice } from "@/lib/format";
import { loadWatchlist, type WatchlistRow } from "@/lib/watchlist";
import {
  describeNyseMarketState,
  getNyseMarketState,
} from "@/lib/market-state";
import {
  formatDateStamp,
  formatNewsTimestamp,
  formatTime,
  useTimezone,
} from "@/lib/timezone";

const SENTIMENT_FALLBACK_SYMBOLS = ["AAPL", "MSFT", "GOOG", "BTC/USDT", "ETH/USDT"];
const SENTIMENT_REFRESH_MS = 60_000;
/**
 * Hard ceiling on how long we keep the sentiment gauge in `Loading…` before
 * surfacing an "unavailable" UI with a Retry button. The backend hanger fix
 * is Agent A's scope; here we just make sure the UI never stays stuck.
 */
const SENTIMENT_LOAD_TIMEOUT_MS = 30_000;


interface PortfolioPosition {
  symbol: string;
  asset_class?: string;
  market_value?: number;
  unrealized_pnl?: number;
  weight_pct?: number;
}

interface PortfolioData {
  positions?: PortfolioPosition[];
  totals?: {
    market_value?: number;
    unrealized_pnl?: number;
    n_positions?: number;
  };
  by_asset_class?: Record<string, number>;
}

interface MarketTile {
  symbol: string;
  /** Live quote symbol for the sidecar (may differ from display symbol). */
  quoteSymbol?: string;
  label: string;
  value: string;
  change: number;
  detail: string;
  /** When true, render the tile with a "DEMO" pill — no quote endpoint. */
  demo?: boolean;
}

interface WatchRow {
  symbol: string;
  name: string;
  sector: string;
  /** Bid price as displayed; "—" when no live quote is available. */
  bid: string;
  /** Ask price as displayed; "—" when no live quote is available. */
  ask: string;
  last: string;
  change: number;
  /** Optional trend series — empty array means "no history; render placeholder". */
  trend: number[];
  volume: string;
  /**
   * Notional one-day change in dollars (change_pct × last × proxy notional).
   * Replaces the QA-flagged "negative market cap" column. "—" when missing.
   */
  notional: string;
}

interface NewsItem {
  time: string;
  source: string;
  title: string;
  tone: "positive" | "negative" | "neutral" | "warn";
}

interface BriefItem {
  tag: string;
  tone: "positive" | "negative" | "neutral" | "warn";
  text: string;
}

/**
 * KPI strip seed values. Tiles whose `quoteSymbol` resolves at `/api/quote/`
 * get overlaid with live data; everything else stays a clearly-flagged demo.
 * The seeds for live tiles are still placeholders — they only show until the
 * first network response replaces them and `demo` flips to false at runtime.
 *
 * Canonical quote symbols (validated against backend/showme/quotes.py +
 * server_routes/quote.py — regex `^[A-Za-z0-9._:=\-^]+$`, NO slash allowed):
 *   - Yahoo cash indices: `^GSPC`, `^NDX`, `^TNX` (10Y yield ÷10), `^VIX`.
 *   - Yahoo FX: `DX-Y.NYB` (dollar index), `EURUSD=X`.
 *   - Yahoo futures: `CL=F` (WTI), `GC=F` (gold).
 *   - Binance crypto: `BTCUSDT` — slash form returns 404 (route regex
 *     rejects '/'; canonical_route_symbol assumes pre-cleaned input).
 */
export const MARKET_STRIP_SEED: MarketTile[] = [
  {
    symbol: "SPX",
    quoteSymbol: "^GSPC",
    label: "S&P 500",
    value: "—",
    change: 0,
    detail: "cash index",
    demo: true,
  },
  {
    symbol: "NDX",
    quoteSymbol: "^NDX",
    label: "Nasdaq 100",
    value: "—",
    change: 0,
    detail: "mega-cap bid",
    demo: true,
  },
  {
    symbol: "BTC",
    quoteSymbol: "BTCUSDT",
    label: "Bitcoin",
    value: "—",
    change: 0,
    detail: "crypto beta",
    demo: true,
  },
  {
    symbol: "US10Y",
    quoteSymbol: "^TNX",
    label: "10Y yield",
    value: "—",
    change: 0,
    detail: "rates",
    demo: true,
  },
  {
    symbol: "DXY",
    quoteSymbol: "DX-Y.NYB",
    label: "Dollar",
    value: "—",
    change: 0,
    detail: "fx",
    demo: true,
  },
  {
    symbol: "VIX",
    quoteSymbol: "^VIX",
    label: "Volatility",
    value: "—",
    change: 0,
    detail: "risk",
    demo: true,
  },
  {
    symbol: "WTI",
    quoteSymbol: "CL=F",
    label: "Crude",
    value: "—",
    change: 0,
    detail: "energy",
    demo: true,
  },
  {
    symbol: "XAU",
    quoteSymbol: "GC=F",
    label: "Gold",
    value: "—",
    change: 0,
    detail: "metal",
    demo: true,
  },
  {
    symbol: "EURUSD",
    quoteSymbol: "EURUSD=X",
    label: "Euro",
    value: "—",
    change: 0,
    detail: "fx",
    demo: true,
  },
];

/** Symbols on the KPI strip whose live snapshot we should fan out for. */
const MARKET_STRIP_QUOTE_SYMBOLS = MARKET_STRIP_SEED.filter(
  (t) => !!t.quoteSymbol,
).map((t) => t.quoteSymbol as string);

/**
 * No hardcoded watchlist fallback. If the user hasn't saved any symbols and
 * the portfolio is empty, the panel renders the "Add symbols" CTA below.
 * Previous mock collisions (DOGEUSDT $86,617 etc.) caused the Preferences
 * theme-preview to leak fake AAPL price ($224.18) into the dashboard while
 * `/api/quote/AAPL` returned the real $308.82.
 */
const DEFAULT_WATCHLIST: WatchRow[] = [];

const BRIEF_ITEMS: BriefItem[] = [
  {
    tag: "WATCH",
    tone: "positive",
    text: "NVDA breaking $940 puts $1T of derivatives notional in the money.",
  },
  {
    tag: "RISK",
    tone: "negative",
    text: "JPY carry rebuild keeps USD/JPY 158 unwind risk back on the desk.",
  },
  {
    tag: "EVENT",
    tone: "warn",
    text: "10Y auction at 17:00 UTC; last 5 tailed by 1.2bps average.",
  },
];

interface TopArticle {
  title?: string;
  headline?: string;
  source?: string;
  url?: string;
  link?: string;
  publishedAt?: string;
  published_at?: string;
  published_on?: string;
  published?: string;
  date?: string;
  datetime?: string;
  time?: string;
  ts?: string;
  sentiment?: string;
  severity?: string;
  importance_score?: number;
}

interface TopResponse {
  items?: TopArticle[];
  status?: string;
}

function pickArticleTimestamp(a: TopArticle): string | undefined {
  return (
    a.published_at ??
    a.publishedAt ??
    a.published_on ??
    a.published ??
    a.datetime ??
    a.date ??
    a.time ??
    a.ts
  );
}

function pickArticleSource(a: TopArticle): string {
  if (a.source && a.source.trim()) return a.source.trim().toUpperCase();
  try {
    const href = a.url ?? a.link;
    if (!href) return "NEWS";
    const host = new URL(href).hostname.replace(/^www\./, "");
    return host.split(".")[0]!.toUpperCase();
  } catch {
    return "NEWS";
  }
}

function articleTone(a: TopArticle): NewsItem["tone"] {
  const sent = String(a.sentiment ?? "").toLowerCase();
  if (sent.includes("pos") || sent === "bullish") return "positive";
  if (sent.includes("neg") || sent === "bearish") return "negative";
  const sev = String(a.severity ?? "").toLowerCase();
  if (sev === "high" || sev === "critical") return "warn";
  const score = Number(a.importance_score);
  if (Number.isFinite(score) && score >= 80) return "warn";
  return "neutral";
}

const QUICK_CODES = [
  "OMON",
  "GEX",
  "FA",
  "BTMM",
  "DES",
  "WEI",
  "NI",
  "PORT",
  "WATCH",
  "SCAN",
];
/**
 * Demo-only movers shown when the `/api/fn/MOST` endpoint isn't registered
 * yet or returns nothing. Every row is rendered with a per-row DEMO pill so
 * users can't confuse the placeholder with live tape.
 */
const DEMO_MOVERS: { symbol: string; price: string; change: number; demo: true }[] = [
  { symbol: "NVDA", price: "—", change: 0, demo: true },
  { symbol: "AMD", price: "—", change: 0, demo: true },
  { symbol: "COIN", price: "—", change: 0, demo: true },
  { symbol: "AAPL", price: "—", change: 0, demo: true },
  { symbol: "TSLA", price: "—", change: 0, demo: true },
  { symbol: "BTC", price: "—", change: 0, demo: true },
  { symbol: "INTC", price: "—", change: 0, demo: true },
  { symbol: "AMZN", price: "—", change: 0, demo: true },
];

interface MoverRowData {
  symbol: string;
  price: string;
  change: number;
  demo?: boolean;
}

/** MOST endpoint payload shape (mirrors `functions/MOST.tsx::MostRow`). */
interface MostMoverRow {
  symbol?: string;
  ticker?: string;
  last?: number;
  price?: number;
  change_pct?: number;
  changePercent?: number;
}
interface MostMoverPayload {
  rows?: MostMoverRow[];
}

export function Welcome() {
  const status = useAppStore((s) => s.sidecarStatus);
  const engineRoot = useAppStore((s) => s.engineRoot);
  const port = useAppStore((s) => s.sidecarPort);
  const index = useAppStore((s) => s.functionIndex);
  const nativeCodes = useMemo(() => new Set(index.map((e) => e.code)), [index]);
  const functionByCode = useMemo(
    () => new Map(index.map((entry) => [entry.code, entry])),
    [index],
  );
  const portfolio = useFunction<PortfolioData>({
    code: "PORT",
    enabled: status === "healthy" && index.length > 0,
  });

  const totals = portfolio.data?.data?.totals;
  const positions = portfolio.data?.data?.positions ?? [];
  const exposureRows = useMemo(
    () =>
      Object.entries(portfolio.data?.data?.by_asset_class ?? {})
        .sort(([, a], [, b]) => b - a)
        .slice(0, 5),
    [portfolio.data?.data?.by_asset_class],
  );
  // User watchlist persisted via Tauri filesystem / localStorage.
  const [savedWatchlist, setSavedWatchlist] = useState<WatchlistRow[]>([]);
  const [watchlistHydrated, setWatchlistHydrated] = useState(false);
  useEffect(() => {
    let cancelled = false;
    void loadWatchlist().then((rows) => {
      if (cancelled) return;
      setSavedWatchlist(rows);
      setWatchlistHydrated(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const savedWatchSymbols = useMemo(
    () => savedWatchlist.map((r) => r.symbol).filter(Boolean),
    [savedWatchlist],
  );

  // Live quote fan-out for the watchlist + KPI strip in one batch. Empty array
  // is a hard short-circuit inside `useLiveQuotesInternal`, so when the user
  // has no saved symbols we don't fire network requests.
  //
  // UA-CRITICAL-06: `positions` identity is replaced on every snapshot poll
  // (~5s). That used to invalidate `liveQuoteSymbols`, which invalidated the
  // `useLiveQuotes` arg, which tore down + reopened every WS channel — a
  // textbook reconnect storm. Fix: derive a stable string key (sorted symbols
  // joined), then memoize the actual array on that key alone.
  const liveQuoteKey = useMemo(() => {
    const baseSymbols = positions.length
      ? positions.slice(0, 12).map((p) => p.symbol).filter(Boolean)
      : savedWatchSymbols;
    const merged = [...baseSymbols, ...MARKET_STRIP_QUOTE_SYMBOLS];
    return Array.from(new Set(merged)).sort().join(",");
  }, [positions, savedWatchSymbols]);
  const liveQuoteSymbols = useMemo(
    () => (liveQuoteKey ? liveQuoteKey.split(",") : []),
    [liveQuoteKey],
  );

  const liveQuotes = useLiveQuotes(liveQuoteSymbols, {
    enabled: status === "healthy" && liveQuoteSymbols.length > 0,
  });

  // Watchlist rows: portfolio wins if attached, else saved symbols rendered
  // live, else an empty list (UI shows the "Add symbols" CTA).
  const portfolioWatchRows = useMemo(
    () => buildPortfolioWatchRows(positions, liveQuotes),
    [positions, liveQuotes],
  );
  const savedWatchRows = useMemo(
    () => buildSavedWatchRows(savedWatchlist, liveQuotes),
    [savedWatchlist, liveQuotes],
  );
  const watchRows = portfolioWatchRows.length
    ? portfolioWatchRows
    : savedWatchRows.length
      ? savedWatchRows
      : DEFAULT_WATCHLIST;
  const watchEmpty = watchRows.length === 0 && watchlistHydrated && positions.length === 0;

  // KPI strip: overlay live data where we have a quoteSymbol.
  const marketTiles = useMemo(
    () => buildMarketTiles(MARKET_STRIP_SEED, liveQuotes),
    [liveQuotes],
  );

  // Movers: prefer `/api/fn/MOST` if the function is registered.
  const moversAvailable = functionByCode.has("MOST");
  const moversFn = useFunction<MostMoverPayload>({
    code: "MOST",
    params: { limit: 24 },
    enabled: status === "healthy" && moversAvailable,
  });
  const liveMovers = useMemo(
    () => buildMovers(moversFn.data?.data),
    [moversFn.data],
  );
  const moversRows: MoverRowData[] = liveMovers.length ? liveMovers : DEMO_MOVERS;
  const moversAreDemo = liveMovers.length === 0;

  const tz = useTimezone();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  // Faz 5: sentiment panel — fan-out /api/x/symbol_chip for watchlist symbols
  // (or a default mega-cap deck when the watchlist is empty) and aggregate
  // the score into the gauge.
  const sentimentScore = useSentimentStore((s) => s.score);
  const sentimentLabel = useSentimentStore((s) => s.label);
  const sentimentLoading = useSentimentStore((s) => s.loading);
  const sentimentError = useSentimentStore((s) => s.error);
  const sentimentUpdated = useSentimentStore((s) => s.lastUpdated);
  const sentimentMentions = useSentimentStore((s) => s.mentions);
  const refreshSentiment = useSentimentStore((s) => s.refresh);
  // Stabilise the symbol list so the refresh effect only refires when the
  // watchlist composition actually changes, not on every render.
  const sentimentSymbols = useMemo(() => {
    const fromWatch = watchRows.map((r) => r.symbol).slice(0, 12);
    return fromWatch.length ? fromWatch : SENTIMENT_FALLBACK_SYMBOLS;
  }, [watchRows]);
  const sentimentSymbolsKey = sentimentSymbols.join("|");
  useEffect(() => {
    if (status !== "healthy") return;
    refreshSentiment(sentimentSymbols);
    const id = window.setInterval(
      () => refreshSentiment(sentimentSymbols),
      SENTIMENT_REFRESH_MS,
    );
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, sentimentSymbolsKey, refreshSentiment]);

  // Sentiment loading-watchdog: if the store stays `loading=true` past
  // SENTIMENT_LOAD_TIMEOUT_MS without ever resolving (`lastUpdated` still
  // null), surface a synthetic error so the gauge transitions out of the
  // infinite "Loading…0%" trap that prompted the QA report. Agent A is
  // fixing the backend hang; this is the UI-side belt.
  useEffect(() => {
    if (!sentimentLoading || sentimentUpdated) return;
    const id = window.setTimeout(() => {
      // Pull a fresh snapshot before clobbering — another refresh may have
      // resolved between scheduling and firing.
      const snap = useSentimentStore.getState();
      if (snap.loading && snap.lastUpdated == null) {
        useSentimentStore.setState({
          loading: false,
          error: "Sentiment unavailable (timeout)",
        });
      }
    }, SENTIMENT_LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(id);
  }, [sentimentLoading, sentimentUpdated]);

  const sentimentRetry = () => {
    refreshSentiment(sentimentSymbols);
  };
  const session = marketSession(now);
  const dateStamp = formatDateStamp(now, tz);
  const localTime = formatTime(now, { tz });
  const tzLabel = tz.split("/").pop()?.replace(/_/g, " ") ?? tz;
  const totalMarketValue = money(totals?.market_value);

  return (
    <main className="terminal-home showme-home">
      <section className="terminal-home__masthead showme-home__section showme-home__section--0">
        <div className="terminal-home__headline-wrap">
          <p className="terminal-home__eyebrow">
            OVERVIEW / {dateStamp} / {localTime} {tzLabel.toUpperCase()} / {session.toUpperCase()}
          </p>
        </div>
        <div className="terminal-home__runtime">
          <Pill tone={status === "healthy" ? "positive" : "warn"} variant="soft">
            {status}
          </Pill>
          <Pill tone="muted" variant="soft" withDot={false}>
            {port ? `:${port}` : "sidecar pending"}
          </Pill>
          <button
            type="button"
            className="terminal-action terminal-action--solid"
            onClick={() => navigate("/fn/INSTANT")}
          >
            Trade ticket
          </button>
        </div>
      </section>

      <section
        className="terminal-market-strip showme-home__section showme-home__section--1"
        aria-labelledby="terminal-market-strip-heading"
      >
        <h3 id="terminal-market-strip-heading" className="u-sr-only">
          Market strip
        </h3>
        {marketTiles.map((tile) => (
          <button
            key={tile.symbol}
            type="button"
            className="terminal-market-tile"
            data-testid={`kpi-tile-${tile.symbol}`}
            data-demo={tile.demo ? "1" : "0"}
            onClick={() => navigate(`/symbol/${tile.symbol}/DES`)}
          >
            <span className="terminal-market-tile__top">
              <strong>{tile.symbol}</strong>
              <span>{tile.label}</span>
            </span>
            <span className="terminal-market-tile__value">{tile.value}</span>
            <span className={toneClass("terminal-change", tile.change)}>
              {formatPct(tile.change)}
            </span>
            {tile.demo && (
              <span
                className="terminal-market-tile__demo"
                data-testid={`kpi-tile-${tile.symbol}-demo`}
                title="No live quote endpoint — showing demo placeholder"
              >
                DEMO
              </span>
            )}
          </button>
        ))}
      </section>

      <section className="terminal-home__layout showme-home__section showme-home__section--2">
        <div className="terminal-panel terminal-panel--brief">
          <div className="terminal-panel__header">
            <h3>Today's brief - AI narrative</h3>
            <span>Portfolio {totalMarketValue}</span>
          </div>
          {/* Prominent demo banner sits at the top of the card so users don't
              mistake the placeholder narrative for live editorial. */}
          <div
            className="terminal-brief-demo-banner"
            data-testid="brief-demo-banner"
            role="status"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 12px",
              borderBottom: "1px solid var(--color-border-strong, #2a2a2a)",
              background: "var(--color-bg-warn-soft, rgba(255, 200, 0, 0.06))",
              fontSize: 12,
              letterSpacing: 0.4,
            }}
          >
            <Pill tone="warn" variant="soft" withDot={false}>
              Demo data
            </Pill>
            <span>
              Today's brief shows placeholder narrative. The BRIEF/TOP endpoint
              is not yet wired — copy below is illustrative only.
            </span>
          </div>
          <p className="terminal-brief-copy">
            Three weeks of cooling inflation prints left a still-resilient labor market, and
            a Fed path has rediscovered patience. The tape is calm, but cross-asset
            positioning underneath it is the most lopsided it has been since November.
          </p>
          <div className="terminal-brief-ribbons">
            {BRIEF_ITEMS.map((item) => (
              <div key={`${item.tag}-${item.text}`} className="terminal-brief-ribbon">
                <span className={`terminal-tag terminal-tag--${item.tone}`}>
                  {item.tag}
                </span>
                <span>{item.text}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="terminal-panel terminal-panel--sentiment">
          <div
            className="terminal-gauge"
            aria-label={
              sentimentError && !sentimentUpdated
                ? "Sentiment unavailable"
                : `Sentiment ${sentimentLabel.toLowerCase()}`
            }
            data-testid="sentiment-gauge"
            data-score={sentimentScore.toFixed(3)}
          >
            <span className="terminal-gauge__arc" />
            <span
              className="terminal-gauge__needle"
              data-testid="sentiment-needle"
              style={{
                transform: `rotate(${sentimentNeedleAngle(sentimentScore)}deg)`,
              }}
            />
          </div>
          <div>
            <span className="terminal-panel__meta">
              {sentimentEyebrow({
                loading: sentimentLoading,
                error: sentimentError,
                lastUpdated: sentimentUpdated,
                mentions: sentimentMentions,
              })}
            </span>
            {sentimentError && !sentimentUpdated ? (
              <>
                {/* Error-with-retry replaces the infinite Loading… trap. */}
                <strong data-testid="sentiment-label">Sentiment unavailable</strong>
                <span
                  className="terminal-change terminal-change--neutral"
                  data-testid="sentiment-change"
                >
                  —
                </span>
                <button
                  type="button"
                  data-testid="sentiment-retry"
                  onClick={sentimentRetry}
                  style={{
                    marginTop: 8,
                    padding: "4px 10px",
                    fontSize: 11,
                    letterSpacing: 0.4,
                    background: "transparent",
                    border: "1px solid var(--color-border, #3a3a3a)",
                    color: "var(--color-fg-primary, #e6e6e6)",
                    borderRadius: 3,
                    cursor: "pointer",
                  }}
                >
                  Retry
                </button>
              </>
            ) : (
              <>
                <strong data-testid="sentiment-label">
                  {sentimentUpdated || !sentimentLoading ? sentimentLabel : "Loading…"}
                </strong>
                {sentimentUpdated || sentimentLoading ? (
                  <span
                    className={toneClass("terminal-change", sentimentScore)}
                    data-testid="sentiment-change"
                  >
                    {formatSentimentPct(sentimentScore)}
                  </span>
                ) : (
                  <span
                    className="terminal-change terminal-change--neutral"
                    data-testid="sentiment-change"
                  >
                    —
                  </span>
                )}
              </>
            )}
          </div>
        </div>

        <div className="terminal-panel terminal-panel--movers">
          <div className="terminal-panel__header">
            <h3>Today's movers</h3>
            <span data-testid="movers-demo-banner">
              {moversAreDemo ? (
                <>
                  <Pill tone="warn" variant="soft" withDot={false}>
                    Demo data
                  </Pill>{" "}
                  MOST endpoint unavailable
                </>
              ) : (
                <>
                  <Pill tone="positive" variant="soft" withDot={false}>
                    Live
                  </Pill>{" "}
                  {moversRows.length} symbols
                </>
              )}
            </span>
          </div>
          <div className="terminal-movers-grid">
            <div>
              <span className="terminal-panel__meta">Gainers</span>
              {moversRows.filter((m) => m.change > 0).map((mover) => (
                <MoverRow key={`g-${mover.symbol}`} mover={mover} />
              ))}
              {moversRows.filter((m) => m.change > 0).length === 0 && moversAreDemo && (
                <DemoMoverRows kind="gainer" />
              )}
            </div>
            <div>
              <span className="terminal-panel__meta">Losers</span>
              {moversRows.filter((m) => m.change < 0).map((mover) => (
                <MoverRow key={`l-${mover.symbol}`} mover={mover} />
              ))}
              {moversRows.filter((m) => m.change < 0).length === 0 && moversAreDemo && (
                <DemoMoverRows kind="loser" />
              )}
            </div>
          </div>
        </div>

        <div className="terminal-panel terminal-panel--watchlist">
          <div className="terminal-panel__header">
            <h3>Watchlist</h3>
            <span>
              {watchRows.length
                ? `${watchRows.length} symbols / ${
                    positions.length ? "live portfolio" : "saved deck"
                  }`
                : "no symbols"}
            </span>
          </div>
          {portfolio.state === "loading" ? (
            <div className="terminal-watchlist__loading">
              <Skeleton height={22} />
              <Skeleton height={22} />
              <Skeleton height={22} />
            </div>
          ) : watchEmpty ? (
            <div
              className="terminal-empty"
              data-testid="watchlist-empty-state"
              style={{ padding: 16 }}
            >
              <strong>No watchlist symbols yet</strong>
              <span style={{ display: "block", marginBottom: 8, opacity: 0.7 }}>
                Save symbols in WATCH to see live quotes on the dashboard.
              </span>
              <button
                type="button"
                className="terminal-action terminal-action--solid"
                data-testid="watchlist-empty-cta"
                onClick={() => navigate("/fn/WATCH")}
              >
                Add symbols to watchlist
              </button>
            </div>
          ) : (
            <div
              className="terminal-watchlist"
              role="grid"
              aria-label="Watchlist"
              aria-rowcount={watchRows.length + 1}
            >
              <div role="rowgroup">
                <div
                  className="terminal-watchlist__row terminal-watchlist__row--head"
                  role="row"
                >
                  <span role="columnheader">Symbol</span>
                  <span role="columnheader">Sector</span>
                  <span role="columnheader">Bid</span>
                  <span role="columnheader">Ask</span>
                  <span role="columnheader">Last</span>
                  <span role="columnheader">Chg</span>
                  <span role="columnheader">Trend</span>
                  <span role="columnheader">Vol</span>
                  <span role="columnheader">1D Notional</span>
                </div>
              </div>
              <div role="rowgroup">
                {watchRows.map((row) => (
                  <button
                    key={row.symbol}
                    type="button"
                    className="terminal-watchlist__row"
                    role="row"
                    onClick={() => navigate(`/symbol/${row.symbol}/DES`)}
                  >
                    <span className="terminal-watchlist__symbol" role="gridcell">
                      <strong>{row.symbol}</strong>
                      <small>{row.name}</small>
                    </span>
                    <span role="gridcell">{row.sector}</span>
                    <span role="gridcell">{row.bid}</span>
                    <span role="gridcell">{row.ask}</span>
                    <span role="gridcell">{row.last}</span>
                    <span
                      role="gridcell"
                      className={toneClass("terminal-change", row.change)}
                    >
                      {formatPct(row.change)}
                    </span>
                    <span role="gridcell" className="terminal-watchlist__spark">
                      {row.trend.length > 0 ? (
                        <Sparkline
                          values={row.trend}
                          width={78}
                          height={24}
                          tone={row.change >= 0 ? "positive" : "negative"}
                          ariaLabel={`${row.symbol} trend`}
                        />
                      ) : (
                        <span
                          className="terminal-watchlist__spark-empty"
                          data-testid={`spark-empty-${row.symbol}`}
                          aria-label="Trend data unavailable"
                          style={{
                            display: "inline-block",
                            width: 78,
                            height: 24,
                            borderTop: "1px dashed currentColor",
                            opacity: 0.35,
                            verticalAlign: "middle",
                          }}
                        />
                      )}
                    </span>
                    <span role="gridcell">{row.volume}</span>
                    <span role="gridcell">{row.notional}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <aside className="terminal-home__right-rail">
          <NewsflowPanel
            ready={status === "healthy" && index.length > 0}
            tz={tz}
          />

          <div className="terminal-panel terminal-panel--commands">
            <div className="terminal-panel__header">
              <h3>Quick functions</h3>
              <span>{index.length || "--"} registered</span>
            </div>
            <div className="terminal-command-grid">
              {QUICK_CODES.map((code) => {
                const fn = functionByCode.get(code) ?? fallbackEntry(code);
                return (
                  <button
                    key={code}
                    type="button"
                    className="terminal-command"
                    onClick={() => navigate(`/fn/${code}`)}
                  >
                    <strong>{code}</strong>
                    <span>{shortName(fn)}</span>
                    {nativeCodes.has(code) && <em>N</em>}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="terminal-panel terminal-panel--exposure">
            <div className="terminal-panel__header">
              <h3>Exposure</h3>
              <span>{engineRoot ? "engine attached" : "engine pending"}</span>
            </div>
            {exposureRows.length ? (
              <div className="terminal-exposure">
                {exposureRows.map(([label, value]) => (
                  <ExposureLine
                    key={label}
                    label={label}
                    value={value}
                    total={totals?.market_value ?? 0}
                  />
                ))}
              </div>
            ) : (
              <div className="terminal-empty">
                <strong>No local exposure rows</strong>
                <span>Open PORT to attach account or paper portfolio state.</span>
              </div>
            )}
          </div>
        </aside>
      </section>
    </main>
  );
}

function MoverRow({ mover }: { mover: MoverRowData }) {
  return (
    <button
      type="button"
      className="terminal-mover-row"
      data-testid={`mover-row-${mover.symbol}`}
      data-demo={mover.demo ? "1" : "0"}
      onClick={() => navigate(`/symbol/${mover.symbol}/DES`)}
    >
      <strong>{mover.symbol}</strong>
      <span>{mover.price}</span>
      <span className={toneClass("terminal-change", mover.change)}>
        {formatPct(mover.change)}
      </span>
      {mover.demo && (
        <span
          className="terminal-mover-row__demo"
          data-testid={`mover-demo-${mover.symbol}`}
          title="MOST endpoint not registered — demo placeholder"
          style={{
            fontSize: 9,
            letterSpacing: 0.6,
            opacity: 0.7,
            marginLeft: 6,
          }}
        >
          DEMO
        </span>
      )}
    </button>
  );
}

/**
 * Renders the demo gainers/losers slot when MOST isn't registered. Splits the
 * DEMO_MOVERS array so users see both sides of the panel even though every
 * entry's `change` is 0 by construction.
 */
function DemoMoverRows({ kind }: { kind: "gainer" | "loser" }) {
  const slice = kind === "gainer"
    ? DEMO_MOVERS.slice(0, 4)
    : DEMO_MOVERS.slice(4);
  return (
    <>
      {slice.map((m) => (
        <MoverRow
          key={`demo-${kind}-${m.symbol}`}
          mover={{ ...m, change: kind === "gainer" ? 0.01 : -0.01 }}
        />
      ))}
    </>
  );
}

function ExposureLine({
  label,
  value,
  total,
}: {
  label: string;
  value: number;
  total: number;
}) {
  const pct = total > 0 ? Math.max(0, Math.min(100, (value / total) * 100)) : 0;
  return (
    <div className="terminal-exposure__line">
      <div>
        <strong>{label}</strong>
        <span>
          {money(value)} / {pct.toFixed(1)}%
        </span>
      </div>
      <span className="terminal-exposure__track" aria-hidden>
        <span style={{ width: `${pct}%` }} />
      </span>
    </div>
  );
}

/**
 * Build watchlist rows for an attached portfolio. Per-symbol live quote
 * (from {@link useLiveQuotes}) supplies bid/ask + last; we no longer
 * fabricate bid as `market_value` or ask as `market_value + |pnl|*0.03`.
 * The trailing column is **1D notional change** (`change_pct × last`),
 * sign-correct, replacing the QA-flagged "negative market cap" column.
 */
export function buildPortfolioWatchRows(
  positions: PortfolioPosition[],
  liveQuotes: Record<string, QuoteView> = {},
): WatchRow[] {
  return [...positions]
    .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))
    .slice(0, 12)
    .map((position) => {
      const pnl = position.unrealized_pnl ?? 0;
      const mv = Math.max(1, position.market_value ?? 0);
      const change = mv > 0 ? (pnl / mv) * 100 : 0;
      const quote = liveQuotes[position.symbol.toUpperCase()];
      const livePrice = quote?.price ?? null;
      const liveBid = quote?.lastTick?.bid ?? quote?.snapshot?.bid ?? null;
      const liveAsk = quote?.lastTick?.ask ?? quote?.snapshot?.ask ?? null;
      const liveChangePct = quote?.changePct ?? null;
      // Live trumps portfolio-derived last; portfolio-derived stays as last-good.
      const lastNumeric = livePrice ?? (position.market_value ?? null);
      const last = lastNumeric != null ? formatPrice(lastNumeric) : "—";
      const effectiveChange = liveChangePct != null ? liveChangePct : change;
      const notionalValue =
        livePrice != null && liveChangePct != null
          ? (liveChangePct / 100) * livePrice
          : null;
      return {
        symbol: position.symbol,
        name: position.asset_class ?? "Portfolio position",
        sector: position.asset_class ?? "Asset",
        bid: liveBid != null ? formatPrice(liveBid) : "—",
        ask: liveAsk != null ? formatPrice(liveAsk) : "—",
        last,
        change: effectiveChange,
        trend: [],
        volume:
          position.weight_pct != null ? `${position.weight_pct.toFixed(1)}% wt` : "—",
        notional: notionalValue != null ? signedMoney(notionalValue) : "—",
      };
    });
}

/**
 * Build watchlist rows from a saved-symbol list when no portfolio is
 * attached. Quote-only path — `bid`/`ask` come from the live snapshot,
 * never fabricated. `trend` stays empty until a tick history hook ships.
 */
export function buildSavedWatchRows(
  saved: WatchlistRow[],
  liveQuotes: Record<string, QuoteView> = {},
): WatchRow[] {
  return saved.slice(0, 12).map((row) => {
    const quote = liveQuotes[row.symbol.toUpperCase()];
    const price = quote?.price ?? null;
    const changePct = quote?.changePct ?? 0;
    const bid = quote?.lastTick?.bid ?? quote?.snapshot?.bid ?? null;
    const ask = quote?.lastTick?.ask ?? quote?.snapshot?.ask ?? null;
    const notionalValue =
      price != null && quote?.changePct != null
        ? (quote.changePct / 100) * price
        : null;
    return {
      symbol: row.symbol,
      name: row.label ?? row.symbol,
      sector: quote?.snapshot?.asset_class ?? "—",
      bid: bid != null ? formatPrice(bid) : "—",
      ask: ask != null ? formatPrice(ask) : "—",
      last: price != null ? formatPrice(price) : "—",
      change: changePct,
      trend: [],
      volume: quote?.snapshot?.volume != null ? compactVolume(quote.snapshot.volume) : "—",
      notional: notionalValue != null ? signedMoney(notionalValue) : "—",
    };
  });
}

/**
 * Overlay live quotes onto the KPI strip seed. Tiles whose `quoteSymbol`
 * resolves to a finite live price drop the DEMO flag; everything else stays
 * a clearly-flagged placeholder.
 */
export function buildMarketTiles(
  seed: MarketTile[],
  liveQuotes: Record<string, QuoteView> = {},
): MarketTile[] {
  return seed.map((tile) => {
    if (!tile.quoteSymbol) return tile;
    const q = liveQuotes[tile.quoteSymbol.toUpperCase()];
    if (!q || q.price == null) return tile;
    return {
      ...tile,
      value: formatPrice(q.price),
      change: q.changePct ?? 0,
      demo: false,
    };
  });
}

/** Format a numeric volume into "1.2B" / "230.4M" style without inventing data. */
function compactVolume(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(abs / 1e3).toFixed(1)}K`;
  return abs.toFixed(0);
}

/**
 * Pull the top gainers + top losers from a `/api/fn/MOST` payload. Returns
 * an empty array if the payload is missing, malformed, or contains no rows
 * with finite percent changes.
 */
export function buildMovers(payload: MostMoverPayload | undefined | null): MoverRowData[] {
  if (!payload || !Array.isArray(payload.rows)) return [];
  const candidates = payload.rows
    .map((row) => {
      const symbol = row.symbol ?? row.ticker ?? "";
      const price = row.last ?? row.price ?? null;
      const change = row.change_pct ?? row.changePercent ?? null;
      if (!symbol || price == null || change == null) return null;
      if (!Number.isFinite(price) || !Number.isFinite(change)) return null;
      return {
        symbol,
        price: formatPrice(price),
        change,
      } as MoverRowData;
    })
    .filter((r): r is MoverRowData => !!r);
  // Top 4 gainers + top 4 losers, sorted by magnitude.
  const sortedAsc = [...candidates].sort((a, b) => a.change - b.change);
  const losers = sortedAsc.filter((r) => r.change < 0).slice(0, 4);
  const gainers = [...candidates]
    .filter((r) => r.change > 0)
    .sort((a, b) => b.change - a.change)
    .slice(0, 4);
  return [...gainers, ...losers];
}

function fallbackEntry(code: string): FunctionEntry {
  const names: Record<string, string> = {
    OMON: "Option Monitor",
    GEX: "Gamma Exposure",
    FA: "Financial Analysis",
    BTMM: "Rates Environment",
    DES: "Description",
    WEI: "World Markets",
    NI: "News Index",
    PORT: "Portfolio",
    WATCH: "Watchlist",
    SCAN: "Scanner",
  };
  return {
    code,
    name: names[code] ?? code,
    category: "quick",
    description: names[code] ?? code,
  };
}

function shortName(fn: FunctionEntry): string {
  if (fn.name.length <= 22) return fn.name;
  return `${fn.name.slice(0, 20)}...`;
}

/**
 * Trend sparkline helper removed (QA report flagged the sin/cos generator
 * as fabricating fake history). Watchlist rows now ship `trend: []`; the
 * UI renders a dashed placeholder with `aria-label="Trend data unavailable"`
 * instead of synthetic data.
 *
 * If/when a tick-history hook lands (`useTickHistory(symbol)`), wire it into
 * the row builders and the JSX <Sparkline /> branch will activate again.
 */

function toneClass(base: string, value: number): string {
  if (value > 0) return `${base} ${base}--positive`;
  if (value < 0) return `${base} ${base}--negative`;
  return `${base} ${base}--neutral`;
}

function formatPct(value: number): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}%`;
}

// Sentiment helpers — exported for unit tests in Welcome.sentiment.test.tsx.
export function sentimentNeedleAngle(score: number): number {
  // Map `[-1, +1]` → `[-90deg, +90deg]`. score=0 lands at 0deg (straight up).
  const clamped = Math.max(-1, Math.min(1, score));
  return -90 + ((clamped + 1) / 2) * 180;
}

export function formatSentimentPct(score: number): string {
  const pct = Math.round(score * 100);
  const prefix = pct > 0 ? "+" : "";
  return `${prefix}${pct}%`;
}

function sentimentEyebrow({
  loading,
  error,
  lastUpdated,
  mentions,
}: {
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  mentions: number;
}): string {
  if (loading && !lastUpdated) return "SENTIMENT / loading…";
  if (error && !lastUpdated) return "SENTIMENT / unavailable";
  if (!lastUpdated) return "SENTIMENT / 24H";
  const suffix = mentions > 0 ? ` / ${mentions.toLocaleString()} mentions` : "";
  return `SENTIMENT / 24H${suffix}`;
}

function money(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  return `${sign}$${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function signedMoney(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${value >= 0 ? "+" : "-"}${money(Math.abs(value))}`;
}

/**
 * Eyebrow session label is the canonical NYSE state machine
 * (`lib/market-state.ts`). Replaces the heuristic UTC-hour rule that lit
 * `OPEN` on Saturday 14:00 UTC even though the cash session was closed.
 * We re-use the Statusbar display copy so both surfaces never disagree.
 */
function marketSession(date: Date): string {
  return describeNyseMarketState(getNyseMarketState(date)).label;
}

// formatDateStamp moved to lib/timezone.ts so the masthead, statusbar,
// and newsflow all share one wall clock anchored at the user's tz.

function NewsflowPanel({ ready, tz }: { ready: boolean; tz: string }) {
  // UA-HIGH-25: previously `enabled: ready` was a one-shot — when the sidecar
  // restarted (warm-up bumps the auth token / connection epoch), the
  // newsflow stayed pinned to the pre-restart payload until the user
  // navigated away and back. Inject an `epochKey` derived from
  // visibility-tick into params so the fetch identity rotates and the
  // useFunction cache key invalidates on tab refocus + every 5min anyway.
  const epochKey = useVisibilityTick(5 * 60 * 1000);
  const top = useFunction<TopResponse>({
    code: "TOP",
    params: { query: "market", limit: 24, days: 7, _epoch: epochKey },
    enabled: ready,
  });
  const items: TopArticle[] = useMemo(() => {
    const payload = top.data?.data;
    if (Array.isArray(payload)) return payload as TopArticle[];
    if (payload && Array.isArray((payload as TopResponse).items)) {
      return (payload as TopResponse).items ?? [];
    }
    return [];
  }, [top.data]);

  return (
    <div className="terminal-panel terminal-panel--news">
      <div className="terminal-panel__header">
        <h3>Newsflow</h3>
        <span>
          {top.state === "loading"
            ? "loading…"
            : items.length
              ? `${items.length} headlines`
              : "live RSS"}
        </span>
      </div>
      <div className="terminal-newsflow" role="list">
        {top.state === "idle" && (
          <div className="terminal-newsflow__placeholder">
            Engine offline — start the sidecar to stream live headlines.
          </div>
        )}
        {top.state === "loading" && !items.length && (
          <div className="terminal-newsflow__placeholder">Fetching headlines…</div>
        )}
        {top.state === "error" && (
          <div className="terminal-newsflow__placeholder terminal-newsflow__placeholder--error">
            Couldn't reach the news provider. Retry from /fn/TOP.
          </div>
        )}
        {top.state === "ok" && !items.length && (
          <div className="terminal-newsflow__placeholder">
            No headlines yet — adjust filters in /fn/TOP.
          </div>
        )}
        {items.map((item, idx) => {
          const title = item.title ?? item.headline ?? "(untitled)";
          const href = item.url ?? item.link;
          const tone = articleTone(item);
          const source = pickArticleSource(item);
          const ts = pickArticleTimestamp(item);
          const stamp = ts ? formatNewsTimestamp(ts, tz) : "";
          const key = `${href ?? title}-${idx}`;
          const content = (
            <>
              <span
                className={`terminal-newsflow__dot terminal-newsflow__dot--${tone}`}
              />
              <span className="terminal-newsflow__time">{stamp || "—"}</span>
              <span className="terminal-newsflow__body">
                <strong>{source}</strong>
                <span className="terminal-newsflow__title">{title}</span>
              </span>
            </>
          );
          if (href) {
            return (
              <a
                key={key}
                role="listitem"
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="terminal-newsflow__item"
                title={title}
              >
                {content}
              </a>
            );
          }
          return (
            <button
              key={key}
              role="listitem"
              type="button"
              className="terminal-newsflow__item"
              onClick={() => navigate("/fn/TOP")}
              title={title}
            >
              {content}
            </button>
          );
        })}
      </div>
    </div>
  );
}
