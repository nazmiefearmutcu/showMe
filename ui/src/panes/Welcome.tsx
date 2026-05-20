import { useEffect, useMemo, useState } from "react";
import { Pill, Skeleton, Sparkline } from "@/design-system";
import { listNativeCodes } from "@/functions/registry";
import { navigate } from "@/lib/router";
import type { FunctionEntry } from "@/lib/sidecar";
import { useAppStore } from "@/lib/store";
import { useFunction } from "@/lib/useFunction";
import {
  formatDateStamp,
  formatNewsTimestamp,
  formatTime,
  useTimezone,
} from "@/lib/timezone";

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
  label: string;
  value: string;
  change: number;
  detail: string;
}

interface WatchRow {
  symbol: string;
  name: string;
  sector: string;
  bid: string;
  ask: string;
  last: string;
  change: number;
  trend: number[];
  volume: string;
  cap: string;
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

const MARKET_STRIP: MarketTile[] = [
  {
    symbol: "SPX",
    label: "S&P 500",
    value: "5,214.51",
    change: 0.42,
    detail: "cash index",
  },
  {
    symbol: "NDX",
    label: "Nasdaq 100",
    value: "18,804",
    change: 0.73,
    detail: "mega-cap bid",
  },
  {
    symbol: "BTC",
    label: "Bitcoin",
    value: "69,633",
    change: -0.92,
    detail: "crypto beta",
  },
  { symbol: "US10Y", label: "10Y yield", value: "4.2833", change: 0.02, detail: "rates" },
  { symbol: "DXY", label: "Dollar", value: "105.58", change: -0.08, detail: "fx" },
  { symbol: "VIX", label: "Volatility", value: "13.43", change: -0.46, detail: "risk" },
  { symbol: "WTI", label: "Crude", value: "77.80", change: 0.34, detail: "energy" },
  { symbol: "XAU", label: "Gold", value: "2,409.07", change: 0.21, detail: "metal" },
  { symbol: "EURUSD", label: "Euro", value: "1.0832", change: -0.06, detail: "fx" },
];

const DEFAULT_WATCHLIST: WatchRow[] = [
  {
    symbol: "AAPL",
    name: "Apple Inc.",
    sector: "Tech",
    bid: "224.16",
    ask: "224.19",
    last: "224.94",
    change: 1.42,
    trend: makeTrend(3),
    volume: "53.4M",
    cap: "3.45T",
  },
  {
    symbol: "NVDA",
    name: "NVIDIA Corp.",
    sector: "Semi",
    bid: "938.38",
    ask: "938.44",
    last: "934.92",
    change: 2.61,
    trend: makeTrend(6),
    volume: "42.1M",
    cap: "2.31T",
  },
  {
    symbol: "MSFT",
    name: "Microsoft",
    sector: "Tech",
    bid: "432.04",
    ask: "432.09",
    last: "433.76",
    change: 0.84,
    trend: makeTrend(9),
    volume: "21.6M",
    cap: "3.21T",
  },
  {
    symbol: "TSLA",
    name: "Tesla Inc.",
    sector: "Auto",
    bid: "182.36",
    ask: "182.42",
    last: "179.04",
    change: -1.84,
    trend: makeTrend(16),
    volume: "92.4M",
    cap: "581B",
  },
  {
    symbol: "META",
    name: "Meta Platforms",
    sector: "Tech",
    bid: "472.14",
    ask: "472.22",
    last: "473.13",
    change: 1.05,
    trend: makeTrend(22),
    volume: "14.2M",
    cap: "1.20T",
  },
  {
    symbol: "GOOG",
    name: "Alphabet Inc.",
    sector: "Tech",
    bid: "168.08",
    ask: "168.13",
    last: "166.12",
    change: -0.36,
    trend: makeTrend(28),
    volume: "18.8M",
    cap: "2.08T",
  },
  {
    symbol: "AMZN",
    name: "Amazon.com",
    sector: "Retail",
    bid: "184.60",
    ask: "184.65",
    last: "187.41",
    change: -0.21,
    trend: makeTrend(34),
    volume: "32.4M",
    cap: "1.92T",
  },
  {
    symbol: "BRK.B",
    name: "Berkshire B",
    sector: "Finance",
    bid: "414.16",
    ask: "414.24",
    last: "401.15",
    change: 0.12,
    trend: makeTrend(40),
    volume: "3.4M",
    cap: "896B",
  },
  {
    symbol: "JPM",
    name: "JPMorgan Chase",
    sector: "Finance",
    bid: "202.36",
    ask: "202.43",
    last: "195.99",
    change: 0.62,
    trend: makeTrend(46),
    volume: "9.1M",
    cap: "583B",
  },
  {
    symbol: "BTC",
    name: "Bitcoin",
    sector: "Crypto",
    bid: "68,338",
    ask: "68,344",
    last: "69,633",
    change: -0.92,
    trend: makeTrend(55),
    volume: "24.1B",
    cap: "1.34T",
  },
  {
    symbol: "ETH",
    name: "Ethereum",
    sector: "Crypto",
    bid: "3,273.50",
    ask: "3,274.50",
    last: "3,278.65",
    change: 1.12,
    trend: makeTrend(61),
    volume: "12.4B",
    cap: "393B",
  },
  {
    symbol: "EURUSD",
    name: "EUR / USD",
    sector: "FX",
    bid: "1.0819",
    ask: "1.0821",
    last: "1.0832",
    change: -0.08,
    trend: makeTrend(67),
    volume: "128B",
    cap: "-",
  },
];

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
const MOVERS = [
  { symbol: "NVDA", price: "938.44", change: 2.61 },
  { symbol: "AMD", price: "168.42", change: 2.18 },
  { symbol: "COIN", price: "218.60", change: 1.94 },
  { symbol: "AAPL", price: "224.18", change: 1.42 },
  { symbol: "TSLA", price: "182.40", change: -1.84 },
  { symbol: "BTC", price: "68,340", change: -0.92 },
  { symbol: "INTC", price: "31.20", change: -0.74 },
  { symbol: "AMZN", price: "184.62", change: -0.21 },
];

export function Welcome() {
  const status = useAppStore((s) => s.sidecarStatus);
  const engineRoot = useAppStore((s) => s.engineRoot);
  const port = useAppStore((s) => s.sidecarPort);
  const index = useAppStore((s) => s.functionIndex);
  const nativeCodes = useMemo(() => new Set(listNativeCodes()), []);
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
  const dynamicWatchRows = useMemo(() => buildPortfolioWatchRows(positions), [positions]);
  const watchRows = dynamicWatchRows.length ? dynamicWatchRows : DEFAULT_WATCHLIST;
  const tz = useTimezone();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  const session = marketSession(now);
  const dateStamp = formatDateStamp(now, tz);
  const localTime = formatTime(now, { tz });
  const tzLabel = tz.split("/").pop()?.replace(/_/g, " ") ?? tz;
  const totalMarketValue = money(totals?.market_value);

  return (
    <main className="terminal-home showme-home" aria-labelledby="terminal-home-heading">
      <section className="terminal-home__masthead showme-home__section showme-home__section--0">
        <div className="terminal-home__headline-wrap">
          <p className="terminal-home__eyebrow">
            OVERVIEW / {dateStamp} / {localTime} {tzLabel.toUpperCase()} / {session.toUpperCase()}
          </p>
          <h2 id="terminal-home-heading" className="terminal-home__headline">
            MARKETS ARE QUIET. <span>CONVICTION IS NOT.</span>
          </h2>
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
        {MARKET_STRIP.map((tile) => (
          <button
            key={tile.symbol}
            type="button"
            className="terminal-market-tile"
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
          </button>
        ))}
      </section>

      <section className="terminal-home__layout showme-home__section showme-home__section--2">
        <div className="terminal-panel terminal-panel--brief">
          <div className="terminal-panel__header">
            <h3>Today's brief - AI narrative</h3>
            <span>Portfolio {totalMarketValue}</span>
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
          <div className="terminal-gauge" aria-label="Sentiment cautiously bullish">
            <span className="terminal-gauge__arc" />
            <span className="terminal-gauge__needle" />
          </div>
          <div>
            <span className="terminal-panel__meta">SENTIMENT / 24H</span>
            <strong>Cautiously Bullish</strong>
            <span className="terminal-change terminal-change--positive">+32%</span>
          </div>
        </div>

        <div className="terminal-panel terminal-panel--movers">
          <div className="terminal-panel__header">
            <h3>Today's movers</h3>
            <span>S&P 500</span>
          </div>
          <div className="terminal-movers-grid">
            <div>
              <span className="terminal-panel__meta">Gainers</span>
              {MOVERS.filter((m) => m.change > 0).map((mover) => (
                <MoverRow key={mover.symbol} mover={mover} />
              ))}
            </div>
            <div>
              <span className="terminal-panel__meta">Losers</span>
              {MOVERS.filter((m) => m.change < 0).map((mover) => (
                <MoverRow key={mover.symbol} mover={mover} />
              ))}
            </div>
          </div>
        </div>

        <div className="terminal-panel terminal-panel--watchlist">
          <div className="terminal-panel__header">
            <h3>Watchlist</h3>
            <span>
              {watchRows.length} symbols /{" "}
              {positions.length ? "live portfolio" : "sample deck"}
            </span>
          </div>
          {portfolio.state === "loading" ? (
            <div className="terminal-watchlist__loading">
              <Skeleton height={22} />
              <Skeleton height={22} />
              <Skeleton height={22} />
            </div>
          ) : (
            <div className="terminal-watchlist" role="table" aria-label="Watchlist">
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
                <span role="columnheader">Mkt cap</span>
              </div>
              {watchRows.map((row) => (
                <button
                  key={row.symbol}
                  type="button"
                  className="terminal-watchlist__row"
                  role="row"
                  onClick={() => navigate(`/symbol/${row.symbol}/DES`)}
                >
                  <span className="terminal-watchlist__symbol" role="cell">
                    <strong>{row.symbol}</strong>
                    <small>{row.name}</small>
                  </span>
                  <span role="cell">{row.sector}</span>
                  <span role="cell">{row.bid}</span>
                  <span role="cell">{row.ask}</span>
                  <span role="cell">{row.last}</span>
                  <span role="cell" className={toneClass("terminal-change", row.change)}>
                    {formatPct(row.change)}
                  </span>
                  <span role="cell" className="terminal-watchlist__spark">
                    <Sparkline
                      values={row.trend}
                      width={78}
                      height={24}
                      tone={row.change >= 0 ? "positive" : "negative"}
                      ariaLabel={`${row.symbol} trend`}
                    />
                  </span>
                  <span role="cell">{row.volume}</span>
                  <span role="cell">{row.cap}</span>
                </button>
              ))}
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

function MoverRow({ mover }: { mover: { symbol: string; price: string; change: number } }) {
  return (
    <button
      type="button"
      className="terminal-mover-row"
      onClick={() => navigate(`/symbol/${mover.symbol}/DES`)}
    >
      <strong>{mover.symbol}</strong>
      <span>{mover.price}</span>
      <span className={toneClass("terminal-change", mover.change)}>
        {formatPct(mover.change)}
      </span>
    </button>
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

function buildPortfolioWatchRows(positions: PortfolioPosition[]): WatchRow[] {
  return [...positions]
    .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))
    .slice(0, 12)
    .map((position, index) => {
      const pnl = position.unrealized_pnl ?? 0;
      const mv = Math.max(1, position.market_value ?? 0);
      const change = mv > 0 ? (pnl / mv) * 100 : 0;
      const last = position.market_value ? money(position.market_value) : "-";
      return {
        symbol: position.symbol,
        name: position.asset_class ?? "Portfolio position",
        sector: position.asset_class ?? "Asset",
        bid: money(position.market_value),
        ask: money((position.market_value ?? 0) + Math.abs(pnl) * 0.03),
        last,
        change,
        trend: makeTrend(index * 7 + 5),
        volume: position.weight_pct != null ? `${position.weight_pct.toFixed(1)}% wt` : "-",
        cap: signedMoney(position.unrealized_pnl),
      };
    });
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

function makeTrend(seed: number, n = 18): number[] {
  const values: number[] = [];
  let value = 48 + (seed % 11);
  for (let i = 0; i < n; i += 1) {
    value += Math.sin((i + seed) * 0.62) * 4.4 + Math.cos((seed + i) * 0.23) * 1.7;
    values.push(Number(Math.max(18, Math.min(86, value)).toFixed(2)));
  }
  return values;
}

function toneClass(base: string, value: number): string {
  if (value > 0) return `${base} ${base}--positive`;
  if (value < 0) return `${base} ${base}--negative`;
  return `${base} ${base}--neutral`;
}

function formatPct(value: number): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}%`;
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

function marketSession(date: Date): string {
  const utcHour = date.getUTCHours();
  if (utcHour >= 13 && utcHour < 20) return "open";
  if (utcHour >= 20 && utcHour < 22) return "after-hours";
  return "pre-open";
}

// formatDateStamp moved to lib/timezone.ts so the masthead, statusbar,
// and newsflow all share one wall clock anchored at the user's tz.

function NewsflowPanel({ ready, tz }: { ready: boolean; tz: string }) {
  const top = useFunction<TopResponse>({
    code: "TOP",
    params: { query: "market", limit: 24, days: 7 },
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
