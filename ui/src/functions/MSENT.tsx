/**
 * MSENT — Market Sentiment.
 *
 * Fear & Greed (CNN, 0-100 with components and 90-day history), crypto Fear &
 * Greed, VIX term structure, social buzz rank table and a news-sentiment card
 * for one ticker. Every section renders from the awareness snapshot it came
 * with; a section that awareness returns as null shows its own empty state
 * (no default gauge value is ever drawn). The news card reads the SOSC
 * function for the chosen ticker.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Sparkline,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { PaneState } from "@/design-system/PaneState";
import { useFunction } from "@/lib/useFunction";
import { loadWatchlist, subscribeWatchlist, type WatchlistRow } from "@/lib/watchlist";
import { isGaugeStale } from "@/lib/sentiment-store";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";
import { AwarenessUnavailable } from "./awareness/AwarenessUnavailable";
import { ProviderHealthStrip } from "./awareness/ProviderHealthStrip";
import type { AwarenessMeta, AwarenessProvider } from "./awareness/types";
import {
  FearGreedGauge,
  fearGreedZone,
  formatSignedDelta,
  formatUtcStamp,
} from "./awareness/FearGreedGauge";
import { TermStructureChart, nearTermAboveSpot } from "./awareness/TermStructureChart";
import { SentimentBars } from "./awareness/SentimentBars";

interface HistoryPoint {
  ts: string;
  value: number;
}

interface CnnComponent {
  key: string;
  label: string;
  score: number | null;
  rating?: string | null;
  as_of?: string | null;
}

interface CnnBlock {
  score: number;
  rating?: string | null;
  as_of: string;
  previous_close?: number | null;
  previous_1_week?: number | null;
  previous_1_month?: number | null;
  previous_1_year?: number | null;
  components?: CnnComponent[];
  history?: HistoryPoint[];
}

interface CryptoBlock {
  score: number;
  rating?: string | null;
  as_of?: string | null;
  history?: HistoryPoint[];
}

interface VixBlock {
  vix: number | null;
  vix9d: number | null;
  vix3m: number | null;
  as_of?: string | null;
  term_ratio?: number | null;
  structure?: "contango" | "backwardation" | null;
}

interface SocialRow {
  ticker: string;
  name?: string | null;
  rank: number | null;
  mentions: number | null;
  mention_change_pct: number | null;
  rank_change: number | null;
  as_of?: string | null;
}

interface MsentData {
  status?: string;
  reason?: string | null;
  cnn?: CnnBlock | null;
  crypto?: CryptoBlock | null;
  vix?: VixBlock | null;
  social?: { stocks?: SocialRow[]; crypto?: SocialRow[] };
  sources?: unknown;
  meta?: AwarenessMeta;
}

interface NewsSeriesBucket {
  ts: string;
  mean: number | null;
  count?: number;
}

interface SoscNews {
  count?: number;
  weighted_mean?: number | null;
  positive_share?: number | null;
  negative_share?: number | null;
  momentum_z?: number | null;
  dispersion?: number | null;
  latest_at?: string | null;
  publishers?: string[] | number;
  series?: NewsSeriesBucket[];
}

interface SoscData {
  status?: string;
  reason?: string | null;
  news?: SoscNews;
  gdelt_tone?: HistoryPoint[];
}

const DEFAULT_TICKER_COUNT = 5;

/** Watchlist symbols, upper-cased, kept current when the watchlist changes. */
function useWatchlistSymbols(): string[] {
  const [rows, setRows] = useState<WatchlistRow[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => {
      loadWatchlist()
        .then((next) => {
          if (alive) setRows(next);
        })
        .catch(() => undefined);
    };
    load();
    const unsubscribe = subscribeWatchlist(load);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, []);
  return useMemo(
    () => rows.map((r) => r.symbol.trim().toUpperCase()).filter(Boolean),
    [rows],
  );
}

export function MSENTPane({ code }: FunctionPaneProps) {
  const { state, data, error, refetch } = useFunction<MsentData>({
    code,
    params: { history_days: 90 },
  });
  const payload = data?.data;
  const status = payload?.status ?? "—";
  const isUnavailable = status === "provider_unavailable";
  const providers = payload?.meta?.providers ?? [];

  const watch = useWatchlistSymbols();
  const tickerOptions = useMemo(
    () => Array.from(new Set(watch)).slice(0, DEFAULT_TICKER_COUNT),
    [watch],
  );
  const [picked, setPicked] = useState<string | null>(null);
  const ticker = picked ?? tickerOptions[0] ?? null;

  const sosc = useFunction<SoscData>({
    code: "SOSC",
    symbol: ticker ?? undefined,
    params: { window: "7d" },
    enabled: !!ticker,
  });

  const body = isUnavailable ? (
    <AwarenessUnavailable
      reason={payload?.reason ?? null}
      onRetry={refetch}
      subject="market sentiment"
    />
  ) : (
    <PaneState state={state} error={error} empty={false} onRetry={refetch} loadingRows={8}>
      <div className="aw-msent">
        <FearGreedCard cnn={payload?.cnn ?? null} providers={providers} />
        <ComponentsCard cnn={payload?.cnn ?? null} providers={providers} />
        <CryptoCard crypto={payload?.crypto ?? null} providers={providers} />
        <VixCard vix={payload?.vix ?? null} providers={providers} />
        <SocialCard
          social={payload?.social ?? null}
          providers={providers}
          selected={ticker}
          onPick={setPicked}
        />
        <NewsCard
          ticker={ticker}
          tickerOptions={tickerOptions}
          onPick={setPicked}
          sosc={sosc}
        />
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Market Sentiment"
          subtitle={`Fear & Greed · VIX · social buzz · ${ticker ?? "no ticker"}`}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh market sentiment"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {!isUnavailable && payload?.meta ? (
            <ProviderHealthStrip
              providers={providers}
              feedHealth={payload.meta.feed_health}
              generatedAt={payload.meta.generated_at}
            />
          ) : null}
          {body}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "awareness:sentiment"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ──────────────────────────────────────────────────────── */

/** Honest per-section note: the provider failure if awareness reports one. */
function sectionNote(providers: AwarenessProvider[], fallback: string): string {
  const failing = providers.find((p) => p.status === "degraded" || p.status === "down");
  if (failing) {
    return `${failing.provider} ${failing.status}${failing.last_error ? `: ${failing.last_error}` : ""}`;
  }
  return fallback;
}

function Card({
  id,
  title,
  className,
  asOf,
  children,
}: {
  id: string;
  title: string;
  className?: string;
  asOf?: string | null;
  children: ReactNode;
}) {
  return (
    <section className={`aw-card ${className ?? ""}`} aria-labelledby={id}>
      <h3 id={id} className="aw-card__title">
        {title}
      </h3>
      {children}
      {asOf !== undefined ? (
        <p className="aw-card__asof">{asOf ? `as of ${asOf}` : "as of —"}</p>
      ) : null}
    </section>
  );
}

function Empty({ id, title, note }: { id: string; title: string; note: string }) {
  return (
    <Card id={id} title={title}>
      <p className="aw-card__empty">No data yet. {note}</p>
    </Card>
  );
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function fmtSigned(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const rounded = Number(v.toFixed(digits));
  if (rounded === 0) return (0).toFixed(digits);
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(digits)}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
}

function ratingColor(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "var(--text-mute)";
  return fearGreedZone(score).color;
}

function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  return `${d.getUTCDate()} ${months[d.getUTCMonth()]}`;
}

function SparkBlock({ history, label }: { history: HistoryPoint[]; label: string }) {
  const values = history.map((h) => h.value).filter((v) => Number.isFinite(v));
  if (values.length < 2) return null;
  return (
    <div>
      <div className="aw-spark">
        <Sparkline
          values={values}
          width={300}
          height={96}
          tone="neutral"
          ariaLabel={label}
        />
      </div>
      <div
        className="aw-mono"
        style={{
          fontSize: 9,
          color: "var(--text-mute)",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>{shortDate(history[0]?.ts)}</span>
        <span>{shortDate(history[history.length - 1]?.ts)}</span>
      </div>
    </div>
  );
}

/* ── cards ────────────────────────────────────────────────────────── */

function FearGreedCard({
  cnn,
  providers,
}: {
  cnn: CnnBlock | null;
  providers: AwarenessProvider[];
}) {
  if (!cnn || !Number.isFinite(cnn.score)) {
    return (
      <Empty
        id="msent-fg"
        title="Fear & Greed"
        note={sectionNote(providers, "Awareness has no CNN Fear & Greed snapshot.")}
      />
    );
  }
  const zone = fearGreedZone(cnn.score);
  const delta =
    cnn.previous_close == null || !Number.isFinite(cnn.previous_close)
      ? null
      : cnn.score - cnn.previous_close;
  const prev: Array<[string, number | null | undefined]> = [
    ["Previous close", cnn.previous_close],
    ["1 week", cnn.previous_1_week],
    ["1 month", cnn.previous_1_month],
    ["1 year", cnn.previous_1_year],
  ];
  return (
    <Card id="msent-fg" title="Fear & Greed" className="aw-card--fg" asOf={cnn.as_of}>
      <div style={{ display: "grid", justifyItems: "center", gap: 4 }}>
        <FearGreedGauge score={cnn.score} size="hero" testId="msent-fg-gauge" />
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span className="aw-mood__score">{Math.round(cnn.score)}</span>
          <strong style={{ color: zone.color }}>{cnn.rating ?? zone.label}</strong>
        </div>
        <span className="aw-mono" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
          {delta == null ? "—" : `${formatSignedDelta(delta)} vs previous close`}
        </span>
      </div>
      <dl className="aw-figure-row">
        {prev.map(([label, v]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd style={{ color: ratingColor(v) }}>{fmtNum(v, 1)}</dd>
          </div>
        ))}
      </dl>
      {cnn.history && cnn.history.length > 1 ? (
        <SparkBlock history={cnn.history} label="Fear and Greed, 90 days" />
      ) : null}
    </Card>
  );
}

function ComponentsCard({
  cnn,
  providers,
}: {
  cnn: CnnBlock | null;
  providers: AwarenessProvider[];
}) {
  const components = cnn?.components ?? [];
  if (components.length === 0) {
    return (
      <Empty
        id="msent-components"
        title="Components"
        note={sectionNote(providers, "No component breakdown returned.")}
      />
    );
  }
  return (
    <Card id="msent-components" title="Components">
      <ul className="aw-components">
        {components.map((c) => {
          const color = ratingColor(c.score);
          const width = c.score == null ? 0 : Math.max(0, Math.min(100, c.score));
          return (
            <li key={c.key}>
              <span>{c.label}</span>
              <span className="aw-bar" aria-hidden="true">
                <span
                  className="aw-bar__fill"
                  style={{ width: `${width}%`, background: color }}
                />
              </span>
              <span style={{ color, fontSize: 10 }}>
                {c.rating ?? (c.score == null ? "—" : fearGreedZone(c.score).label)}
              </span>
              <span className="aw-mono">{fmtNum(c.score, 0)}</span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function CryptoCard({
  crypto,
  providers,
}: {
  crypto: CryptoBlock | null;
  providers: AwarenessProvider[];
}) {
  if (!crypto || !Number.isFinite(crypto.score)) {
    return (
      <Empty
        id="msent-crypto"
        title="Crypto Fear & Greed"
        note={sectionNote(providers, "No crypto Fear & Greed reading.")}
      />
    );
  }
  const history = crypto.history ?? [];
  const last = history[history.length - 1];
  const prev = history[history.length - 2];
  const delta = last && prev ? last.value - prev.value : null;
  const zone = fearGreedZone(crypto.score);
  return (
    <Card id="msent-crypto" title="Crypto Fear & Greed" asOf={crypto.as_of ?? null}>
      <div style={{ display: "grid", justifyItems: "center", gap: 4 }}>
        <FearGreedGauge score={crypto.score} testId="msent-crypto-gauge" />
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span className="aw-mood__score" style={{ fontSize: 24 }}>
            {Math.round(crypto.score)}
          </span>
          <strong style={{ color: zone.color }}>{crypto.rating ?? zone.label}</strong>
        </div>
        <span className="aw-mono" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
          {delta == null ? "—" : `${formatSignedDelta(delta)} vs yesterday`}
        </span>
      </div>
      {history.length > 1 ? (
        <SparkBlock history={history.slice(-30)} label="Crypto Fear and Greed, 30 days" />
      ) : null}
    </Card>
  );
}

function VixCard({
  vix,
  providers,
}: {
  vix: VixBlock | null;
  providers: AwarenessProvider[];
}) {
  if (!vix || (vix.vix == null && vix.vix9d == null && vix.vix3m == null)) {
    return (
      <Empty
        id="msent-vix"
        title="VIX term structure"
        note={sectionNote(providers, "No VIX term structure returned.")}
      />
    );
  }
  const ratio =
    vix.term_ratio != null && Number.isFinite(vix.term_ratio)
      ? vix.term_ratio
      : vix.vix != null && vix.vix3m != null && vix.vix3m !== 0
        ? vix.vix / vix.vix3m
        : null;
  const structureLabel =
    vix.structure === "contango"
      ? "Contango"
      : vix.structure === "backwardation"
        ? "Backwardation"
        : null;
  const warn = nearTermAboveSpot(vix.vix9d, vix.vix);
  return (
    <Card id="msent-vix" title="VIX term structure">
      <TermStructureChart vix9d={vix.vix9d} vix={vix.vix} vix3m={vix.vix3m} />
      <div className="aw-ts-meta">
        {structureLabel ? <span className="aw-badge">{structureLabel}</span> : null}
        <span>VIX / VIX3M {fmtNum(ratio, 3)}</span>
      </div>
      {warn ? (
        <p className="aw-note--warn" role="note">
          9-day above spot: near-term event risk
        </p>
      ) : null}
      <p className="aw-card__asof">CBOE daily closes{vix.as_of ? `, ${vix.as_of}` : ""}</p>
    </Card>
  );
}

function SocialCard({
  social,
  providers,
  selected,
  onPick,
}: {
  social: MsentData["social"] | null;
  providers: AwarenessProvider[];
  selected: string | null;
  onPick: (ticker: string) => void;
}) {
  const [kind, setKind] = useState<"stocks" | "crypto">("stocks");
  const rows = social?.[kind] ?? [];
  return (
    <Card id="msent-social" title="Social buzz">
      <div className="aw-chip-row" role="group" aria-label="Social universe">
        {(["stocks", "crypto"] as const).map((k) => (
          <button
            key={k}
            type="button"
            className="aw-toggle"
            aria-pressed={kind === k}
            onClick={() => setKind(k)}
          >
            {k}
          </button>
        ))}
      </div>
      {rows.length === 0 ? (
        <p className="aw-card__empty">
          No {kind} social rows. {sectionNote(providers, "Awareness returned none.")}
        </p>
      ) : (
        <table className="aw-social">
          <thead>
            <tr>
              <th scope="col">Rank</th>
              <th scope="col">Ticker</th>
              <th scope="col">Mentions</th>
              <th scope="col">24h</th>
              <th scope="col">Rank Δ</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const change = r.mention_change_pct;
              const rankDelta = r.rank_change ?? 0;
              return (
                <tr
                  key={r.ticker}
                  aria-current={selected === r.ticker ? "true" : undefined}
                >
                  <td>{r.rank ?? "—"}</td>
                  <td>
                    <button
                      type="button"
                      className="aw-link"
                      onClick={() => onPick(r.ticker)}
                      style={{
                        background: "none",
                        border: 0,
                        padding: 0,
                        font: "inherit",
                        cursor: "pointer",
                      }}
                    >
                      {r.ticker}
                    </button>
                  </td>
                  <td>{r.mentions == null ? "—" : r.mentions.toLocaleString("en-US")}</td>
                  <td
                    style={{
                      color:
                        change == null
                          ? undefined
                          : change >= 0
                            ? "var(--positive)"
                            : "var(--negative)",
                    }}
                  >
                    {fmtPct(change)}
                  </td>
                  <td>
                    {rankDelta > 0
                      ? `▲${rankDelta}`
                      : rankDelta < 0
                        ? `▼${Math.abs(rankDelta)}`
                        : "="}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function NewsCard({
  ticker,
  tickerOptions,
  onPick,
  sosc,
}: {
  ticker: string | null;
  tickerOptions: string[];
  onPick: (ticker: string) => void;
  sosc: { state: string; data?: { data?: SoscData } | null; error?: unknown };
}) {
  const payload = sosc.data?.data;
  const news = payload?.news;
  const series = news?.series ?? [];
  const tone = payload?.gdelt_tone ?? [];
  const publishers =
    news?.publishers == null
      ? null
      : Array.isArray(news.publishers)
        ? news.publishers.length
        : news.publishers;

  let content: ReactNode;
  if (!ticker) {
    content = (
      <p className="aw-card__empty">Add a watchlist symbol to see its news sentiment.</p>
    );
  } else if (sosc.state === "loading" || sosc.state === "idle") {
    content = <p className="aw-card__empty">Loading news sentiment for {ticker}…</p>;
  } else if (sosc.state === "error") {
    content = (
      <p className="aw-card__empty">
        News sentiment failed: {String(sosc.error ?? "unknown error")}
      </p>
    );
  } else if (payload?.status === "provider_unavailable") {
    content = (
      <p className="aw-card__empty">
        {payload.reason ?? "News sentiment provider unavailable."}
      </p>
    );
  } else if (series.length === 0 || (news?.count ?? 0) === 0) {
    content = (
      <p className="aw-card__empty">No scored news for {ticker} in the last 7 days.</p>
    );
  } else {
    content = (
      <div style={{ display: "grid", gap: 8 }}>
        <SentimentBars
          series={series.map((s) => ({ ts: s.ts, mean: s.mean }))}
          tone={tone}
          toneLabel="GDELT tone, native scale"
          ariaLabel={`${ticker} news sentiment buckets with GDELT tone`}
        />
        <dl className="aw-stat-grid">
          <div>
            <dt>Quality-weighted mean</dt>
            <dd>{fmtSigned(news?.weighted_mean, 2)}</dd>
          </div>
          <div>
            <dt>Articles</dt>
            <dd>{news?.count ?? "—"}</dd>
          </div>
          <div>
            <dt>Positive share</dt>
            <dd>
              {news?.positive_share == null
                ? "—"
                : `${Math.round(news.positive_share * 100)}%`}
            </dd>
          </div>
          <div>
            <dt>Negative share</dt>
            <dd>
              {news?.negative_share == null
                ? "—"
                : `${Math.round(news.negative_share * 100)}%`}
            </dd>
          </div>
          <div>
            <dt>Momentum z (30 d)</dt>
            <dd>{fmtSigned(news?.momentum_z, 2)}</dd>
          </div>
          <div>
            <dt>Dispersion</dt>
            <dd>{fmtNum(news?.dispersion, 2)}</dd>
          </div>
          <div>
            <dt>Publishers</dt>
            <dd>{publishers ?? "—"}</dd>
          </div>
        </dl>
      </div>
    );
  }

  return (
    <section className="aw-card aw-card--news" aria-labelledby="msent-news">
      <h3 id="msent-news" className="aw-card__title">
        News sentiment{ticker ? ` — ${ticker}` : ""}
      </h3>
      <div className="aw-chip-row" role="group" aria-label="News sentiment ticker">
        {tickerOptions.map((t) => (
          <button
            key={t}
            type="button"
            className="aw-toggle"
            aria-pressed={t === ticker}
            onClick={() => onPick(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {content}
      <p className="aw-card__asof">
        {news?.latest_at
          ? `latest article ${formatUtcStamp(news.latest_at)}${isGaugeStale(news.latest_at) ? " stale" : ""}`
          : ticker
            ? "no scored articles yet"
            : ""}
      </p>
    </section>
  );
}
