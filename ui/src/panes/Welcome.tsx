import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Pill, Skeleton, Sparkline } from "@/design-system";
import { navigate } from "@/lib/router";
import { toast } from "@/lib/toast";
import { useSentimentStore } from "@/lib/sentiment-store";
import { sidecarFetch, type FunctionEntry } from "@/lib/sidecar";
import { useAppStore } from "@/lib/store";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { useLiveQuotes, type QuoteView } from "@/lib/market-data";
import { useWorkspace } from "@/lib/workspace";
import { BUILTIN_PRESETS, loadBuiltinPreset } from "@/lib/builtinPresets";
import {
  isFirstRunDone,
  isPristineHomeWorkspace,
  markFirstRunDone,
  seedStarterWatchlist,
  startKaosBot,
} from "@/lib/first-run";
import { useTickFlash } from "@/lib/tick-flash";
import { useTickTrend } from "@/lib/useTickTrend";
import {
  formatCompactNumber,
  formatCurrency,
  formatMissing,
  formatPrice,
  formatSignedCurrency,
} from "@/lib/format";
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
  /**
   * U10 tick-flash source: the raw live price behind `value`. `null`/absent
   * = no live quote yet (no flash — never flash a placeholder).
   */
  price?: number | null;
  /**
   * One-day percent change. `null` = no live quote yet — the tile renders the
   * missing sentinel ("—") instead of a fabricated "0.00%" flat day.
   */
  change: number | null;
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
    change: null,
    detail: "cash index",
    demo: true,
  },
  {
    symbol: "NDX",
    quoteSymbol: "^NDX",
    label: "Nasdaq 100",
    value: "—",
    change: null,
    detail: "mega-cap bid",
    demo: true,
  },
  {
    symbol: "BTC",
    quoteSymbol: "BTCUSDT",
    label: "Bitcoin",
    value: "—",
    change: null,
    detail: "crypto beta",
    demo: true,
  },
  {
    symbol: "US10Y",
    quoteSymbol: "^TNX",
    label: "10Y yield",
    value: "—",
    change: null,
    detail: "rates",
    demo: true,
  },
  {
    symbol: "DXY",
    quoteSymbol: "DX-Y.NYB",
    label: "Dollar",
    value: "—",
    change: null,
    detail: "fx",
    demo: true,
  },
  {
    symbol: "VIX",
    quoteSymbol: "^VIX",
    label: "Volatility",
    value: "—",
    change: null,
    detail: "risk",
    demo: true,
  },
  {
    symbol: "WTI",
    quoteSymbol: "CL=F",
    label: "Crude",
    value: "—",
    change: null,
    detail: "energy",
    demo: true,
  },
  {
    symbol: "XAU",
    quoteSymbol: "GC=F",
    label: "Gold",
    value: "—",
    change: null,
    detail: "metal",
    demo: true,
  },
  {
    symbol: "EURUSD",
    quoteSymbol: "EURUSD=X",
    label: "Euro",
    value: "—",
    change: null,
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

/** BRIEF function payload (see backend/showme/engine/functions/news/brief.py). */
interface BriefArticle {
  title?: string;
  headline?: string;
  source?: string;
  publisher?: string;
  url?: string;
  link?: string;
  matched_symbol?: string;
  symbol?: string;
  section?: string;
  sentiment?: string;
  severity?: string;
  importance_score?: number;
}

interface BriefResponse {
  status?: string;
  articles?: BriefArticle[];
  rows?: BriefArticle[];
}

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

function briefArticleTone(a: BriefArticle): BriefItem["tone"] {
  const sent = String(a.sentiment ?? "").toLowerCase();
  if (sent.includes("pos") || sent === "bullish") return "positive";
  if (sent.includes("neg") || sent === "bearish") return "negative";
  const sev = String(a.severity ?? "").toLowerCase();
  if (sev === "high" || sev === "critical") return "warn";
  const score = Number(a.importance_score);
  if (Number.isFinite(score) && score >= 80) return "warn";
  return "neutral";
}

/**
 * How many brief ribbons the panel renders, and the `limit` passed to the
 * BRIEF backend. Kept as one constant so the request size, the slice in
 * {@link buildBriefItems}, and the "X stories" counter never disagree.
 */
export const BRIEF_DISPLAY_LIMIT = 6;

/**
 * Build the brief ribbons from a live BRIEF payload. Watchlist-scoped stories
 * are tagged with their symbol; cross-asset macro stories get a "MARKET" tag.
 * Returns an empty array if the payload is missing/empty so the caller can
 * fall back to the honest demo banner.
 */
export function buildBriefItems(
  payload: BriefResponse | undefined | null,
  limit = BRIEF_DISPLAY_LIMIT,
): BriefItem[] {
  if (!payload) return [];
  const articles = payload.articles ?? payload.rows ?? [];
  if (!Array.isArray(articles)) return [];
  return articles
    .map((a) => {
      const text = (a.title ?? a.headline ?? "").trim();
      if (!text) return null;
      const sym = String(a.matched_symbol ?? a.symbol ?? "").toUpperCase();
      const tag = !sym || sym === "MACRO" ? "MARKET" : sym;
      return { tag, tone: briefArticleTone(a), text } as BriefItem;
    })
    .filter((item): item is BriefItem => !!item)
    .slice(0, limit);
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
 * Owner request (2026-09-16): the pinned quick functions must be swappable
 * at any time. The deck persists per browser; an invalid/empty stored deck
 * falls back to the shipped defaults (restore only what validates).
 */
const QUICK_STORE_KEY = "showme.quick-functions.v1";

function loadQuickCodes(): string[] {
  try {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(QUICK_STORE_KEY) : null;
    if (!raw) return [...QUICK_CODES];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...QUICK_CODES];
    const cleaned = parsed
      .map((value) => String(value ?? "").trim().toUpperCase())
      .filter(Boolean);
    return cleaned.length ? cleaned.slice(0, QUICK_CODES.length) : [...QUICK_CODES];
  } catch {
    return [...QUICK_CODES];
  }
}
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
  // Command entry is the hero affordance of the landing pane: the global
  // ⌘K palette already exists, so the masthead surfaces it as a clickable
  // hairline field instead of building a second input to keep in sync.
  const openPalette = useAppStore((s) => s.togglePalette);
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
  // Memoized so the `?? []` fallback stops minting a new array each render.
  // This also makes the UA-CRITICAL-06 guard below hold as intended: its key
  // memo was re-running every render, not just when positions changed.
  const positions = useMemo<PortfolioPosition[]>(
    () => portfolio.data?.data?.positions ?? [],
    [portfolio.data?.data?.positions],
  );
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

  // Honest sparklines: accumulate the real ticks already flowing through
  // `liveQuotes` (no fabrication — symbols without ticks keep `trend: []`
  // and the placeholder). See `@/lib/useTickTrend`.
  const tickTrends = useTickTrend(liveQuotes);

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
  const baseWatchRows = portfolioWatchRows.length
    ? portfolioWatchRows
    : savedWatchRows.length
      ? savedWatchRows
      : DEFAULT_WATCHLIST;
  const watchRows = useMemo(
    () => attachTrends(baseWatchRows, tickTrends),
    [baseWatchRows, tickTrends],
  );
  const watchEmpty = watchRows.length === 0 && watchlistHydrated && positions.length === 0;

  // Live cross-asset tape for the Exposure panel while the local book is
  // empty: asset-class member count + average live change from the SAME
  // quote fan-out the KPI strip and watchlist already poll (no extra
  // network). It is a market read — the panel header labels it as such —
  // not portfolio exposure, and it disappears the moment real positions
  // exist.
  const exposureTape = useMemo(() => {
    const byClass = new Map<string, { count: number; sum: number; n: number }>();
    for (const row of watchRows) {
      const quote = liveQuotes[row.symbol.toUpperCase()];
      const label =
        (quote?.snapshot?.asset_class ?? "other").trim().toUpperCase() || "OTHER";
      const slot = byClass.get(label) ?? { count: 0, sum: 0, n: 0 };
      slot.count += 1;
      const change = quote?.changePct;
      if (change != null && Number.isFinite(change)) {
        slot.sum += change;
        slot.n += 1;
      }
      byClass.set(label, slot);
    }
    return Array.from(byClass.entries())
      .map(([label, slot]) => ({
        label,
        count: slot.count,
        change: slot.n > 0 ? slot.sum / slot.n : null,
      }))
      .sort((a, b) => b.count - a.count);
  }, [watchRows, liveQuotes]);

  // U9 first-run desk setup: offer a one-time, dismissible card while the
  // desk is still the untouched cold-boot default AND the watchlist is
  // empty. `isFirstRunDone` reads the `showme.firstrun.done` localStorage
  // flag (storage-broken ⇒ treated as answered — never nag-loop).
  const workspaceTree = useWorkspace((s) => s.tree);
  const [firstRunAnswered, setFirstRunAnswered] = useState(() => isFirstRunDone());
  const showFirstRunCard =
    !firstRunAnswered && isPristineHomeWorkspace(workspaceTree) && watchEmpty;
  const onFirstRunAnswered = useCallback(() => setFirstRunAnswered(true), []);

  // KPI strip: overlay live data where we have a quoteSymbol.
  const marketTiles = useMemo(
    () => buildMarketTiles(MARKET_STRIP_SEED, liveQuotes),
    [liveQuotes],
  );

  // Movers: prefer `/api/fn/MOST` if the function is registered. `live: true`
  // is the param the MOST backend reads (via `_truthy(params["live"])`) to
  // fan out real quotes; without it the endpoint returns the deterministic
  // reference deck (status "reference") and the panel would silently show
  // demo tape even with a healthy sidecar. The demo fallback below still
  // covers the case where the live snapshot comes back empty.
  const moversAvailable = functionByCode.has("MOST");
  const moversFn = useFunction<MostMoverPayload>({
    code: "MOST",
    params: { live: true, limit: 24 },
    enabled: status === "healthy" && moversAvailable,
  });
  const liveMovers = useMemo(
    () => buildMovers(moversFn.data?.data),
    [moversFn.data],
  );
  const moversRows: MoverRowData[] = liveMovers.length ? liveMovers : DEMO_MOVERS;
  const moversAreDemo = liveMovers.length === 0;
  // Partition once per render instead of filtering four times in the JSX.
  const moverGainers = useMemo(
    () => moversRows.filter((m) => m.change > 0),
    [moversRows],
  );
  const moverLosers = useMemo(
    () => moversRows.filter((m) => m.change < 0),
    [moversRows],
  );

  // BRIEF: compose the "Today's brief" ribbons from the live BRIEF function,
  // which aggregates real TOP RSS/GDELT headlines (no LLM, no fabricated
  // prose — see backend/showme/engine/functions/news/brief.py). The demo
  // banner + placeholder copy below render ONLY when BRIEF returns nothing,
  // so users never mistake a real outage for editorial content.
  const briefAvailable = functionByCode.has("BRIEF");
  const briefFn = useFunction<BriefResponse>({
    code: "BRIEF",
    params: { limit: BRIEF_DISPLAY_LIMIT },
    enabled: status === "healthy" && briefAvailable,
  });
  const briefItems = useMemo(
    () => buildBriefItems(briefFn.data?.data, BRIEF_DISPLAY_LIMIT),
    [briefFn.data],
  );
  const briefIsLive = briefItems.length > 0;
  const briefLoading = briefFn.state === "loading";

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

  /* Quick-functions deck: swap any pinned shortcut from the panel header. */
  const [quickCodes, setQuickCodes] = useState<string[]>(loadQuickCodes);
  const [quickEditing, setQuickEditing] = useState(false);
  const [quickSlot, setQuickSlot] = useState(0);
  const [quickQuery, setQuickQuery] = useState("");
  useEffect(() => {
    try {
      window.localStorage.setItem(QUICK_STORE_KEY, JSON.stringify(quickCodes));
    } catch {
      /* private mode - the deck still works for this session */
    }
  }, [quickCodes]);
  const quickMatches = useMemo(() => {
    const q = quickQuery.trim().toLowerCase();
    const pool = index.filter((entry) => !quickCodes.includes(entry.code));
    const matches = q
      ? pool.filter((entry) =>
          `${entry.code} ${entry.name} ${entry.category}`.toLowerCase().includes(q),
        )
      : pool;
    return matches.slice(0, 8);
  }, [index, quickCodes, quickQuery]);
  const assignQuickCode = (code: string) => {
    setQuickCodes((prev) => prev.map((entry, i) => (i === quickSlot ? code : entry)));
    setQuickQuery("");
    setQuickSlot((slot) => (slot + 1) % quickCodes.length);
  };

  const session = marketSession(now);
  const dateStamp = formatDateStamp(now, tz);
  const localTime = formatTime(now, { tz });
  const tzLabel = tz.split("/").pop()?.replace(/_/g, " ") ?? tz;
  const totalMarketValue = formatCurrency(totals?.market_value, { compact: true });

  return (
    <main className="terminal-home showme-home">
      <section className="terminal-home__masthead showme-home__section showme-home__section--0">
        <div className="terminal-home__headline-wrap">
          <p className="terminal-home__eyebrow">
            OVERVIEW / {dateStamp} / {localTime} {tzLabel.toUpperCase()} / {session.toUpperCase()}
          </p>
          <button
            type="button"
            className="terminal-command-entry"
            aria-label="Open command palette"
            title="Open the command palette (⌘K)"
            onClick={() => openPalette(true)}
          >
            <span className="terminal-command-entry__glyph" aria-hidden>
              &gt;_
            </span>
            <span className="terminal-command-entry__text">
              Type a function code or company name…
            </span>
            <kbd className="terminal-command-entry__kbd">⌘K</kbd>
          </button>
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
            onClick={() => navigate("/fn/BBGT")}
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
          // U10: per-tile component keyed by symbol so the tick-flash hook
          // state persists across re-renders without leaking between tiles.
          <MarketTileButton key={tile.symbol} tile={tile} />
        ))}
      </section>

      <section className="terminal-home__layout showme-home__section showme-home__section--2">
        <div className="terminal-panel terminal-panel--brief">
          <div className="terminal-panel__header">
            <h3>Today's brief</h3>
            <span>
              {briefIsLive ? (
                <span data-testid="brief-live-banner">
                  <Pill tone="positive" variant="soft" withDot={false}>
                    Live
                  </Pill>{" "}
                  {briefItems.length} stories
                </span>
              ) : (
                `Portfolio ${totalMarketValue}`
              )}
            </span>
          </div>
          {briefIsLive ? (
            // LIVE: ribbons composed from the BRIEF function's aggregated
            // headlines (real RSS/GDELT via TOP — never fabricated prose).
            <div className="terminal-brief-ribbons terminal-brief-ribbons--live">
              {briefItems.map((item) => (
                <div key={`${item.tag}-${item.text}`} className="terminal-brief-ribbon">
                  <span className={`terminal-tag terminal-tag--${item.tone}`}>
                    {item.tag}
                  </span>
                  <span title={item.text}>{item.text}</span>
                </div>
              ))}
            </div>
          ) : briefLoading ? (
            <div
              className="terminal-brief-loading"
              role="status"
              aria-live="polite"
              data-testid="brief-loading"
              style={{ display: "grid", gap: 8, padding: 14 }}
            >
              <Skeleton height={16} />
              <Skeleton height={16} width="80%" />
              <Skeleton height={16} width="90%" />
            </div>
          ) : (
            // EMPTY / FAILED: honest demo banner — no fabricated narrative.
            <>
              <div
                className="terminal-brief-demo-banner"
                data-testid="brief-demo-banner"
                role="status"
                aria-live="polite"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 12px",
                  borderBottom: "1px solid var(--terminal-border)",
                  background: "var(--color-bg-warn-soft, rgba(255, 200, 0, 0.06))",
                  fontSize: 12,
                  letterSpacing: 0.4,
                }}
              >
                <Pill tone="warn" variant="soft" withDot={false}>
                  Demo data
                </Pill>
                <span>
                  No live brief yet — BRIEF returned no headlines (start the
                  sidecar / check the news provider). Copy below is illustrative
                  only and not yet wired to live editorial.
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
                    <span title={item.text}>{item.text}</span>
                  </div>
                ))}
              </div>
            </>
          )}
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
            <svg
              className="terminal-gauge__arc"
              viewBox="0 0 96 52"
              aria-hidden="true"
              focusable="false"
            >
              {/* Two 90° arcs of a 44px-radius circle centred at the needle
                  pivot (48,48): red = [-90°, 0°] bearish, green = [0°, +90°]
                  bullish, exactly matching sentimentNeedleAngle's scale. */}
              <path className="terminal-gauge__arc-neg" d="M 4 48 A 44 44 0 0 1 48 4" />
              <path className="terminal-gauge__arc-pos" d="M 48 4 A 44 44 0 0 1 92 48" />
            </svg>
            <span
              className="terminal-gauge__needle"
              data-testid="sentiment-needle"
              style={{
                transform: `rotate(${sentimentNeedleAngle(sentimentScore)}deg)`,
              }}
            />
          </div>
          <div role="status" aria-live="polite">
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
                  className="terminal-action terminal-action--retry"
                  data-testid="sentiment-retry"
                  aria-label="Retry sentiment fetch"
                  onClick={sentimentRetry}
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
                    className={`${toneClass("terminal-change", sentimentScore)} terminal-grid-numeric`}
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
              {moverGainers.map((mover) => (
                <MoverRow key={`g-${mover.symbol}`} mover={mover} />
              ))}
              {moverGainers.length === 0 && moversAreDemo && (
                <DemoMoverRows kind="gainer" />
              )}
            </div>
            <div>
              <span className="terminal-panel__meta">Losers</span>
              {moverLosers.map((mover) => (
                <MoverRow key={`l-${mover.symbol}`} mover={mover} />
              ))}
              {moverLosers.length === 0 && moversAreDemo && (
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
            <div
              className="terminal-watchlist__loading"
              role="status"
              aria-live="polite"
              aria-label="Loading watchlist"
              data-testid="watchlist-loading"
            >
              <Skeleton height={30} />
              <Skeleton height={30} />
              <Skeleton height={30} />
            </div>
          ) : watchEmpty ? (
            <div
              className="terminal-empty"
              data-testid="watchlist-empty-state"
              style={{ padding: 16 }}
            >
              {showFirstRunCard && (
                <FirstRunCard
                  onAnswered={onFirstRunAnswered}
                  onWatchlistSeeded={setSavedWatchlist}
                />
              )}
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
                  // role="row" must live on a non-button element — a
                  // <button role="row"> is an invalid ARIA override (the
                  // button's implicit role conflicts with row). Use a
                  // focusable div with explicit keyboard activation.
                  <div
                    key={row.symbol}
                    className="terminal-watchlist__row"
                    role="row"
                    tabIndex={0}
                    aria-label={`View ${row.symbol}${
                      row.name && row.name !== row.symbol ? ` (${row.name})` : ""
                    } — last ${row.last}, change ${formatPct(row.change)}`}
                    onClick={() => navigate(`/symbol/${row.symbol}/DES`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        navigate(`/symbol/${row.symbol}/DES`);
                      }
                    }}
                  >
                    <span className="terminal-watchlist__symbol" role="gridcell">
                      <strong>{row.symbol}</strong>
                      <small title={row.name}>{row.name}</small>
                    </span>
                    <span role="gridcell" title={row.sector}>
                      {row.sector}
                    </span>
                    <span role="gridcell" className="terminal-grid-numeric">
                      {row.bid}
                    </span>
                    <span role="gridcell" className="terminal-grid-numeric">
                      {row.ask}
                    </span>
                    <span role="gridcell" className="terminal-grid-numeric">
                      {row.last}
                    </span>
                    <span
                      role="gridcell"
                      className={`${toneClass("terminal-change", row.change)} terminal-grid-numeric`}
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
                    <span role="gridcell" className="terminal-grid-numeric">
                      {row.volume}
                    </span>
                    <span role="gridcell" className="terminal-grid-numeric">
                      {row.notional}
                    </span>
                  </div>
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
              <span className="terminal-panel__header-actions">
                <span>{index.length || "--"} registered</span>
                <button
                  type="button"
                  className={`terminal-quick-edit${quickEditing ? " is-active" : ""}`}
                  data-testid="quick-functions-edit"
                  aria-pressed={quickEditing}
                  title={quickEditing ? "Finish editing quick functions" : "Edit quick functions"}
                  aria-label={quickEditing ? "Finish editing quick functions" : "Edit quick functions"}
                  onClick={() => {
                    setQuickEditing((value) => !value);
                    setQuickQuery("");
                  }}
                >
                  <span aria-hidden>{quickEditing ? "✓" : "⌁"}</span>
                </button>
              </span>
            </div>
            <div className="terminal-command-grid">
              {quickCodes.map((code, i) => {
                const fn = functionByCode.get(code) ?? fallbackEntry(code);
                return (
                  <button
                    key={`${i}-${code}`}
                    type="button"
                    className={`terminal-command${quickEditing && i === quickSlot ? " is-editing" : ""}`}
                    aria-label={
                      quickEditing
                        ? `Replace ${code} — ${fn.name}`
                        : `Open ${code} — ${fn.name}`
                    }
                    onClick={() =>
                      quickEditing ? setQuickSlot(i) : navigate(`/fn/${code}`)
                    }
                  >
                    <strong>{code}</strong>
                    <span title={fn.name}>{quickEditing ? "replace" : shortName(fn)}</span>
                    {nativeCodes.has(code) && !quickEditing && <em>N</em>}
                  </button>
                );
              })}
            </div>
            {quickEditing && (
              <div className="terminal-quick-editor" data-testid="quick-functions-editor">
                <div className="terminal-quick-editor__row">
                  <span className="terminal-quick-editor__hint">
                    Slot {quickSlot + 1} — pick a function
                  </span>
                  <button
                    type="button"
                    className="terminal-quick-editor__reset"
                    onClick={() => {
                      setQuickCodes([...QUICK_CODES]);
                      setQuickEditing(false);
                    }}
                  >
                    Reset deck
                  </button>
                </div>
                <input
                  className="terminal-quick-editor__input"
                  placeholder="Type a code or name…"
                  value={quickQuery}
                  onChange={(event) => setQuickQuery(event.target.value)}
                  aria-label="Search functions to assign"
                />
                <div
                  className="terminal-quick-editor__list"
                  role="listbox"
                  aria-label="Function candidates"
                >
                  {quickMatches.map((entry) => (
                    <button
                      key={entry.code}
                      type="button"
                      role="option"
                      className="terminal-quick-editor__option"
                      onClick={() => assignQuickCode(entry.code)}
                    >
                      <strong>{entry.code}</strong>
                      <span>{entry.name}</span>
                    </button>
                  ))}
                  {quickMatches.length === 0 && (
                    <span className="terminal-quick-editor__empty">
                      No matching function
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="terminal-panel terminal-panel--exposure">
            <div className="terminal-panel__header">
              <h3>Exposure</h3>
              <span>
                {exposureRows.length
                  ? engineRoot
                    ? "engine attached"
                    : "engine pending"
                  : exposureTape.length
                    ? "no positions — live tape"
                    : "no positions"}
              </span>
            </div>
            {exposureRows.length ? (
              <div className="terminal-exposure" data-testid="exposure-positions">
                {exposureRows.map(([label, value]) => (
                  <ExposureLine
                    key={label}
                    label={label}
                    value={value}
                    total={totals?.market_value ?? 0}
                  />
                ))}
              </div>
            ) : exposureTape.length ? (
              // No portfolio book yet — keep the panel ALIVE with the
              // watchlist's live cross-asset breadth instead of a dead empty
              // state. Header copy marks it as a tape, not exposure.
              <div className="terminal-exposure" data-testid="exposure-live-tape">
                {exposureTape.map((row) => (
                  <div
                    className="terminal-exposure__line"
                    key={row.label}
                    data-asset={assetKey(row.label)}
                  >
                    <div>
                      <strong>{assetLabel(row.label)}</strong>
                      <span>
                        {row.count} sym
                        {row.change == null
                          ? " — -"
                          : ` — ${formatPct(row.change)}`}
                      </span>
                    </div>
                    <span className="terminal-exposure__track" aria-hidden>
                      <span
                        className="terminal-exposure__fill"
                        data-asset={assetKey(row.label)}
                        style={{
                          width:
                            row.change == null
                              ? "0%"
                              : `${Math.min(100, Math.max(4, Math.abs(row.change) * 20))}%`,
                        }}
                      />
                    </span>
                  </div>
                ))}
                <AddPositionForm onAdded={() => portfolio.refetch()} />
              </div>
            ) : (
              <div className="terminal-empty">
                <strong>No local exposure rows</strong>
                <span>Add positions below or open PORT to attach a book.</span>
                <AddPositionForm onAdded={() => portfolio.refetch()} />
              </div>
            )}
          </div>
        </aside>
      </section>
    </main>
  );
}

/**
 * U10 (Lane D, 2026-09-08): one KPI tile as its own component so the
 * tick-flash hook can observe the tile's numeric price across renders.
 * Identical markup/testids to the previous inline JSX — the only addition
 * is the `wx-tick-flash--up|down` class on the value cell while a flash is
 * active (450 ms background pulse; reduced-motion users get no animation —
 * the keyframes only exist under `prefers-reduced-motion: no-preference`).
 */
function MarketTileButton({ tile }: { tile: MarketTile }) {
  const flash = useTickFlash(tile.price ?? null);
  const flashClass = flash ? ` wx-tick-flash--${flash}` : "";
  return (
    <button
      type="button"
      className="terminal-market-tile"
      data-testid={`kpi-tile-${tile.symbol}`}
      data-demo={tile.demo ? "1" : "0"}
      aria-label={`View ${tile.label} (${tile.symbol})${
        tile.demo ? " — demo placeholder" : ""
      }`}
      onClick={() => navigate(`/symbol/${tile.symbol}/DES`)}
    >
      <span className="terminal-market-tile__top">
        <strong>{tile.symbol}</strong>
        <span title={tile.label}>{tile.label}</span>
      </span>
      <span
        className={`terminal-market-tile__value terminal-grid-numeric${flashClass}`}
        data-testid={`kpi-tile-${tile.symbol}-value`}
      >
        {tile.value}
      </span>
      <span
        className={`${toneClass("terminal-change", tile.change ?? 0)} terminal-grid-numeric`}
      >
        {tile.change == null ? formatMissing : formatPct(tile.change)}
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
  );
}

/**
 * U9 (Lane D, 2026-09-08): one-time first-run desk setup. Compact chooser
 * over the EXISTING builtin presets (`lib/builtinPresets.ts`) plus a
 * starter-watchlist seed through the existing serialized `addSymbol`
 * queue (`lib/first-run.ts`). Every action — including Skip — records the
 * answer so the card is offered exactly once. No new persistence schema;
 * the flag is a plain `showme.*` localStorage key.
 */
export function FirstRunCard({
  onAnswered,
  onWatchlistSeeded,
}: {
  onAnswered: () => void;
  onWatchlistSeeded: (rows: WatchlistRow[]) => void;
}) {
  const [seeding, setSeeding] = useState(false);
  const [startingKaos, setStartingKaos] = useState(false);
  // Markets Overview first — it is the recommended one-click desk.
  const ordered = useMemo(() => {
    const primary = BUILTIN_PRESETS.filter((p) => p.id === "markets-overview");
    const rest = BUILTIN_PRESETS.filter((p) => p.id !== "markets-overview");
    return [...primary, ...rest];
  }, []);

  const acceptPreset = (id: string) => {
    markFirstRunDone();
    onAnswered();
    loadBuiltinPreset(id);
  };

  // KAOS Multibot is THE default bot (frozen contract §D). The action runs
  // through the EXISTING bot-store create flow only (startKaosBot): it
  // reopens the saved KAOS Multibot when one exists, otherwise opens a new
  // draft preseeded with engine "kaos" + crypto/NASDAQ venues in shadow
  // mode. Enabling and going live stay explicit user actions in BOT.
  const startKaos = useCallback(async () => {
    setStartingKaos(true);
    try {
      const outcome = await startKaosBot();
      markFirstRunDone();
      onAnswered();
      toast.success(
        outcome === "opened-existing"
          ? "KAOS Multibot opened"
          : "New KAOS Multibot draft",
        "Scans crypto + NASDAQ venues. Shadow mode until you enable live.",
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error("Could not open KAOS Multibot", msg);
    } finally {
      setStartingKaos(false);
    }
  }, [onAnswered]);

  const seedWatchlist = useCallback(async () => {
    setSeeding(true);
    try {
      const rows = await seedStarterWatchlist();
      markFirstRunDone();
      onWatchlistSeeded(rows);
      onAnswered();
    } catch (e) {
      // Seeding failed: surface it and leave the card up so the desk can
      // retry — the run is NOT marked done on a failed setup action.
      const msg = e instanceof Error ? e.message : String(e);
      toast.error("Could not seed the starter watchlist", msg);
    } finally {
      setSeeding(false);
    }
  }, [onAnswered, onWatchlistSeeded]);

  const skip = () => {
    markFirstRunDone();
    onAnswered();
  };

  return (
    <div className="wx-firstrun" data-testid="first-run-card">
      <h4 className="wx-firstrun__title">Set up your desk</h4>
      <p className="wx-firstrun__body">
        Start KAOS — the default bot that scans crypto and NASDAQ venues —
        load a ready-made multi-pane desk, seed a starter watchlist, or skip;
        you can rearrange everything later from the ⌘ Layout menu.
      </p>
      <div className="wx-firstrun__actions">
        <button
          type="button"
          className="wx-firstrun__btn wx-firstrun__btn--primary"
          data-testid="first-run-start-kaos"
          disabled={startingKaos}
          onClick={() => void startKaos()}
        >
          <strong>{startingKaos ? "Opening…" : "Start KAOS"}</strong>
          <span>
            KAOS Multibot — scans crypto + NASDAQ. Shadow mode until you
            enable live.
          </span>
        </button>
        {ordered.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className="wx-firstrun__btn"
            data-testid={`first-run-preset-${preset.id}`}
            onClick={() => acceptPreset(preset.id)}
          >
            <strong>{preset.label}</strong>
            <span>{preset.description}</span>
          </button>
        ))}
        <button
          type="button"
          className="wx-firstrun__btn"
          data-testid="first-run-seed"
          disabled={seeding}
          onClick={() => void seedWatchlist()}
        >
          <strong>{seeding ? "Seeding…" : "Seed starter watchlist"}</strong>
          <span>AAPL MSFT NVDA SPY QQQ + crypto majors, live quotes</span>
        </button>
      </div>
      <button
        type="button"
        className="wx-firstrun__skip"
        data-testid="first-run-skip"
        onClick={skip}
      >
        Skip — don't ask again
      </button>
    </div>
  );
}

function MoverRow({ mover }: { mover: MoverRowData }) {
  // Demo rows carry no real tape — show the missing sentinel for both price
  // and change so the placeholder never looks like a live quote. The DEMO
  // pill + neutral tone make the placeholder state unambiguous.
  const changeDisplay = mover.demo ? formatMissing : formatPct(mover.change);
  return (
    <button
      type="button"
      className="terminal-mover-row"
      data-testid={`mover-row-${mover.symbol}`}
      data-demo={mover.demo ? "1" : "0"}
      aria-label={`View ${mover.symbol} — ${mover.price}, ${changeDisplay}${
        mover.demo ? " (demo placeholder)" : ""
      }`}
      onClick={() => navigate(`/symbol/${mover.symbol}/DES`)}
    >
      <strong>{mover.symbol}</strong>
      <span className="terminal-grid-numeric">{mover.price}</span>
      <span
        className={`${toneClass(
          "terminal-change",
          mover.demo ? 0 : mover.change,
        )} terminal-grid-numeric`}
      >
        {changeDisplay}
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
 * DEMO_MOVERS array so users see both sides of the panel. Demo rows keep
 * `change: 0` (no fabricated tick); MoverRow renders the missing sentinel for
 * the change column so the placeholder never looks like a real move.
 */
function DemoMoverRows({ kind }: { kind: "gainer" | "loser" }) {
  const slice = kind === "gainer"
    ? DEMO_MOVERS.slice(0, 4)
    : DEMO_MOVERS.slice(4);
  return (
    <>
      {slice.map((m) => (
        <MoverRow key={`demo-${kind}-${m.symbol}`} mover={m} />
      ))}
    </>
  );
}

/**
 * Semantic asset-class key for the fixed exposure-bar palette (owner
 * 2026-09-16: bars must NOT change with the theme template - the class of
 * each row has to be readable in every theme). Synonyms fold to one key.
 */
function assetKey(label: string): string {
  const slug = String(label || "").trim().toLowerCase();
  if (!slug) return "other";
  if (slug.includes("crypto")) return "crypto";
  if (slug.includes("equit") || slug.includes("stock")) return "equity";
  if (slug.includes("fx") || slug.includes("forex") || slug.includes("curr")) return "fx";
  if (slug.includes("bond") || slug.includes("fixed")) return "bond";
  if (slug.includes("commod")) return "commodity";
  if (slug.includes("index")) return "index";
  if (slug.includes("etf") || slug.includes("fund")) return "etf";
  return "other";
}

/** Display label for exposure rows (source data is lowercase - "crypto"). */
function assetLabel(label: string): string {
  const text = String(label || "").trim();
  if (!text) return text;
  return text.charAt(0).toUpperCase() + text.slice(1);
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
        <strong>{assetLabel(label)}</strong>
        <span>
          {formatCurrency(value, { compact: true })} / {pct.toFixed(1)}%
        </span>
      </div>
      <span className="terminal-exposure__track" aria-hidden>
        <span
          className="terminal-exposure__fill"
          data-asset={assetKey(label)}
          style={{ width: `${pct}%` }}
        />
      </span>
    </div>
  );
}

/**
 * Manual position entry for the local portfolio book
 * (``POST /api/portfolio/positions``). The welcome-page exposure panel is
 * read-only otherwise, and before this route existed there was NO way to
 * attach a paper book at all — the empty state only pointed at PORT. Adding
 * a position persists it to ``runtime/portfolio.json``; PORT then marks it
 * with live prices, so exposure rows are real from the first entry.
 */
function AddPositionForm({ onAdded }: { onAdded: () => void }) {
  const [symbol, setSymbol] = useState("");
  const [quantity, setQuantity] = useState("");
  const [avgCost, setAvgCost] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const sym = symbol.trim().toUpperCase();
    const qty = Number(quantity);
    const cost = Number(avgCost);
    if (!sym || !Number.isFinite(qty) || qty <= 0 || !Number.isFinite(cost) || cost < 0) {
      setError("symbol, a positive qty and a non-negative cost are required");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await sidecarFetch<{ ok: boolean }>("/api/portfolio/positions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym, quantity: qty, avg_cost: cost }),
      });
      setSymbol("");
      setQuantity("");
      setAvgCost("");
      toast.success(
        `${sym} added to the portfolio book`,
        "Exposure marks update with live prices.",
      );
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="terminal-exposure__add" data-testid="exposure-add-form" onSubmit={submit}>
      <input
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="SYMBOL"
        aria-label="Position symbol"
        maxLength={24}
        spellCheck={false}
      />
      <input
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        placeholder="QTY"
        aria-label="Position quantity"
        inputMode="decimal"
      />
      <input
        value={avgCost}
        onChange={(e) => setAvgCost(e.target.value)}
        placeholder="COST"
        aria-label="Average cost"
        inputMode="decimal"
      />
      <button type="submit" className="terminal-action" disabled={busy}>
        {busy ? "…" : "Add"}
      </button>
      {error && (
        <span className="terminal-exposure__add-error" role="alert">
          {error}
        </span>
      )}
    </form>
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
          position.weight_pct != null ? `${position.weight_pct.toFixed(1)}% wt` : formatMissing,
        notional: notionalValue != null ? formatSignedCurrency(notionalValue) : formatMissing,
      };
    });
}

/**
 * Overlay real tick histories onto watch rows (see `useTickTrend`).
 * Matching is case-insensitive on symbol. Rows without a recorded series
 * keep their builder-supplied `trend` (usually `[]` → placeholder) — never
 * fabricated. Returns the same array reference when nothing attaches, so
 * downstream memos stay stable while histories are still empty.
 */
export function attachTrends(
  rows: WatchRow[],
  trends: Record<string, number[]>,
): WatchRow[] {
  if (rows.length === 0) return rows;
  let changed = false;
  const out = rows.map((row) => {
    const series = trends[row.symbol.toUpperCase()];
    if (series && series.length > 0 && series !== row.trend) {
      changed = true;
      return { ...row, trend: series };
    }
    return row;
  });
  return changed ? out : rows;
}

/**
 * Build watchlist rows from a saved-symbol list when no portfolio is
 * attached. Quote-only path — `bid`/`ask` come from the live snapshot,
 * never fabricated. `trend` stays empty here; the component overlays real
 * tick histories via `attachTrends` + `useTickTrend`.
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
      volume:
        quote?.snapshot?.volume != null
          ? formatCompactNumber(quote.snapshot.volume, { fixedDigits: 2 })
          : formatMissing,
      notional: notionalValue != null ? formatSignedCurrency(notionalValue) : formatMissing,
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
      // U10: raw price kept alongside the formatted value so the tile
      // component can flash on real numeric change (not on re-format).
      price: q.price,
      // Missing changePct stays null (renders "—") rather than faking a
      // flat 0.00% day on a live price.
      change: q.changePct ?? null,
      demo: false,
    };
  });
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
  const suffix = mentions > 0 ? ` / ${mentions.toLocaleString("en-US")} mentions` : "";
  return `SENTIMENT / 24H${suffix}`;
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
      <div className="terminal-newsflow" role="list" aria-live="polite" aria-busy={top.state === "loading"}>
        {top.state === "idle" && (
          <div className="terminal-newsflow__placeholder" role="status">
            Engine offline — start the sidecar to stream live headlines.
          </div>
        )}
        {top.state === "loading" && !items.length && (
          <div className="terminal-newsflow__placeholder" role="status">
            Fetching headlines…
          </div>
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
          // role="listitem" must wrap the interactive element, not sit on it
          // — putting it on the <a>/<button> overrides their link/button
          // semantics. Keep the list item as a div and nest the control.
          if (href) {
            return (
              <div key={key} role="listitem" className="terminal-newsflow__listitem">
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="terminal-newsflow__item"
                  title={title}
                >
                  {content}
                </a>
              </div>
            );
          }
          return (
            <div key={key} role="listitem" className="terminal-newsflow__listitem">
              <button
                type="button"
                className="terminal-newsflow__item"
                onClick={() => navigate("/fn/TOP")}
                title={title}
              >
                {content}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
