/**
 * NI / CN — topic-news and company-news headline drawers.
 *
 * Bloomberg-grade news intelligence: header with symbol focus + sentiment
 * score badge, two-column layout (feed left, AI synthesis right with
 * Bull / Bear / Catalysts sections), and a 24h sentiment timeline strip.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  Empty,
  Field,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  StatCard,
} from "@/design-system";
import { runFunction, FunctionCallError } from "@/lib/functions";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { useAppStore } from "@/lib/store";
import { isInTauri } from "@/lib/tauri";
import { relativeTimeLabel, sortNewsNewestFirst } from "@/lib/time";
import { SymbolBar } from "@/shell/SymbolBar";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { toast } from "@/lib/toast";
import {
  fetchVeryfinderBatch,
  recommendedVeryfinderSampleForNews,
  type VeryfinderBatchItem,
  type VeryfinderOverlay,
  type VeryfinderTone,
} from "@/lib/veryfinder";
import {
  FunctionControlGroup,
  LoadStatePill,
  NewsLimitControl,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import {
  NEWS_LIMITS,
  type NewsLimit,
  usePersistentOption,
} from "./function-control-state";
import { XSenChip } from "./XSenChip";
import type { FunctionPaneProps } from "./registry-types";

interface NIArticle {
  title?: string;
  headline?: string;
  summary?: string;
  source?: string;
  url?: string;
  link?: string;
  published_at?: string;
  publishedAt?: string;
  published_on?: string;
  published?: string;
  date?: string;
  datetime?: string;
  time?: string;
  ts?: string;
  symbols?: string[];
  symbol?: string;
  category?: string;
  severity?: string;
  importance_score?: number;
  relevance_score?: number;
  importance_reasons?: string[];
  matched_terms?: string[];
}

const REFRESH_MS = 90_000;
const FETCH_NEWS_LIMIT = Math.max(...NEWS_LIMITS);
const TOPIC_PRESETS = ["MACRO", "FED", "EARN", "CHIPS", "OIL", "BANKS", "TECH", "CRYPTO"] as const;
type TopicPreset = (typeof TOPIC_PRESETS)[number];
type LoadState = "idle" | "loading" | "ok" | "error";

export function NIPane({ code, symbol }: FunctionPaneProps) {
  const upperCode = code.toUpperCase();
  const topicMode = upperCode === "NI";
  // 2026-05-11 hotfix: in CN (company news) mode fall back to a default
  // equity symbol so palette-cold renders pull headlines immediately.
  // Topic mode (NI) keeps the existing "MACRO" default for `topicText`.
  const effectiveSymbol = topicMode
    ? symbol
    : symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const [topicText, setTopicText] = useState("MACRO");
  const [articles, setArticles] = useState<NIArticle[] | null>(null);
  const [veryfinderMap, setVeryfinderMap] = useState<Record<string, VeryfinderOverlay>>({});
  const [veryfinderState, setVeryfinderState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [limit, setLimit] = usePersistentOption<NewsLimit>(
    `showme.${topicMode ? "ni-topic" : "cn"}-news-limit`,
    NEWS_LIMITS,
    50,
  );
  const [tick, setTick] = useState(0);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const sidecarPort = useAppStore((s) => s.sidecarPort);
  const waitingForSidecar = isInTauri() && sidecarPort == null;
  const requestLabel = topicMode ? topicText.trim() : effectiveSymbol;
  const veryfinderNotifiedBatch = useRef("");

  useEffect(() => {
    const currentTopic = topicText.trim();
    const currentLabel = topicMode ? currentTopic : effectiveSymbol;
    if (!currentLabel) {
      setArticles(null);
      setError(null);
      setState("idle");
      return;
    }
    if (waitingForSidecar) {
      setArticles(null);
      setError(null);
      setState("loading");
      return;
    }
    let cancelled = false;
    setError(null);
    setArticles(null);
    setVeryfinderMap({});
    setVeryfinderState("idle");
    setState("loading");
    const fnCode = topicMode ? "NI" : "CN";
    const liveParams = { limit: FETCH_NEWS_LIMIT, live: true, news_timeout: 6, timeout: 6 };
    const topicParams = { ...liveParams, topic: currentTopic, query: currentTopic };
    const requestNews = (params: Record<string, unknown>) =>
      runFunction<unknown>(fnCode, {
        symbol: topicMode ? undefined : effectiveSymbol,
        params,
        timeoutMs: 18_000,
      }).catch(async (err) => {
        if (!topicMode && err instanceof FunctionCallError && err.status === 404) {
          return runFunction<unknown>("NI", {
            symbol: effectiveSymbol,
            params: { ...params, topic: effectiveSymbol },
          });
        }
        throw err;
      });

    requestNews(topicMode ? topicParams : liveParams)
      .then(async (res) => {
        const items = normalize(res.data);
        const hasOnlyPlaceholders =
          items.length > 0 &&
          items.every((item) => {
            const status = String((item as { status?: unknown }).status ?? "").toLowerCase();
            return status === "provider_unavailable" || status === "news_feed_empty";
          });
        const looksEmpty = items.length === 0 || hasOnlyPlaceholders;
        const sourcesUnavailable = res.sources?.some(
          (source) => String(source).toLowerCase() === "no_live_source",
        );
        if (!cancelled && looksEmpty && sourcesUnavailable) {
          await delay(600);
          const retryParams = { ...liveParams, news_timeout: 10, timeout: 10, deep: true };
          return requestNews(
            topicMode
              ? { ...retryParams, topic: currentTopic, query: currentTopic }
              : retryParams,
          );
        }
        return res;
      })
      .then((res) => {
        if (cancelled) return;
        const nextArticles = normalize(res.data);
        setArticles(nextArticles);
        setVeryfinderState(nextArticles.length ? "loading" : "idle");
        setState("ok");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [code, topicMode, effectiveSymbol, tick, waitingForSidecar, sidecarPort, topicText]);

  useEffect(() => {
    if (!articles?.length || waitingForSidecar) {
      setVeryfinderMap({});
      setVeryfinderState(articles?.length ? "loading" : "idle");
      return;
    }
    const sorted = sortNewsNewestFirst(articles, articleTimestamp);
    const items: VeryfinderBatchItem[] = sorted.map((article, index) => ({
      key: articleKey(article, index),
      title: article.title,
      headline: article.headline,
      summary: article.summary,
      source: article.source,
      url: article.url,
      link: article.link,
      category: article.category,
      symbol: article.symbol,
      sample: recommendedVeryfinderSampleForNews(article, topicMode ? undefined : effectiveSymbol),
    }));
    if (!items.length) {
      setVeryfinderMap({});
      setVeryfinderState("idle");
      return;
    }
    let cancelled = false;
    setVeryfinderState("loading");
    fetchVeryfinderBatch({
      items,
      symbol: topicMode ? undefined : effectiveSymbol,
      topic: topicMode ? topicText.trim() : undefined,
      sample: 25,
      source: "auto",
      engine: "rules",
      limit: items.length,
    })
      .then((payload) => {
        if (cancelled) return;
        const next: Record<string, VeryfinderOverlay> = {};
        for (const item of payload.items ?? []) {
          next[item.key] = item.overlay;
        }
        setVeryfinderMap(next);
        setVeryfinderState(payload.ok ? "ok" : "error");
        const batchId = items.map((item) => `${item.key}:${item.sample}`).join("|");
        if (payload.ok && batchId && veryfinderNotifiedBatch.current !== batchId) {
          veryfinderNotifiedBatch.current = batchId;
          toast.success("Veryfinder news inference ready", `${payload.items?.length ?? 0} headline(s) scored with article-level tweet targets.`);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setVeryfinderMap({});
        setVeryfinderState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [articles, topicMode, topicText, effectiveSymbol, waitingForSidecar, sidecarPort]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const veryfinderTweetTarget = useMemo(
    () =>
      articles?.reduce(
        (sum, article) => sum + recommendedVeryfinderSampleForNews(article, topicMode ? undefined : effectiveSymbol),
        0,
      ) ?? 0,
    [articles, topicMode, effectiveSymbol],
  );
  const veryfinderIsBlocking =
    Boolean(articles?.length) && (veryfinderState === "idle" || veryfinderState === "loading");
  const effectiveState: LoadState = state === "ok" && veryfinderIsBlocking ? "loading" : state;

  // Aggregate sentiment — average of veryfinder direction scores, mapped -1..+1
  const sentimentScore = useMemo(() => {
    const overlays = Object.values(veryfinderMap).filter((o) => o.ok);
    if (!overlays.length) return null;
    let sum = 0;
    let count = 0;
    for (const o of overlays) {
      const s = Number(o.social_score ?? 0);
      if (Number.isFinite(s) && Number(o.unique_accounts ?? 0) > 0) {
        // social_score is -100..+100 → /100 → -1..+1
        sum += Math.max(-1, Math.min(1, s / 100));
        count++;
      }
    }
    return count > 0 ? sum / count : null;
  }, [veryfinderMap]);

  // Impact distribution for KPI ribbon
  const impactStats = useMemo(() => {
    const list = articles ?? [];
    const bull = list.filter((a) => {
      const k = articleKey(a, list.indexOf(a));
      const o = veryfinderMap[k];
      return o?.ok && Number(o.social_score ?? 0) > 12;
    }).length;
    const bear = list.filter((a) => {
      const k = articleKey(a, list.indexOf(a));
      const o = veryfinderMap[k];
      return o?.ok && Number(o.social_score ?? 0) < -12;
    }).length;
    const high = list.filter((a) => Number(a.importance_score ?? 0) >= 70).length;
    return { bull, bear, high };
  }, [articles, veryfinderMap]);

  const sortedArticles = useMemo(
    () =>
      articles ? sortNewsNewestFirst(articles, articleTimestamp).slice(0, limit) : [],
    [articles, limit],
  );

  const selectedArticle = useMemo(() => {
    if (!selectedKey) return sortedArticles[0] ?? null;
    return sortedArticles.find((a, i) => articleKey(a, i) === selectedKey) ?? sortedArticles[0] ?? null;
  }, [sortedArticles, selectedKey]);

  const synthesis = useMemo(
    () => buildSynthesis(sortedArticles, veryfinderMap),
    [sortedArticles, veryfinderMap],
  );

  const timeline = useMemo(() => buildTimeline(sortedArticles, veryfinderMap), [sortedArticles, veryfinderMap]);

  const body = !requestLabel ? (
    <Empty
      title={topicMode ? "Enter a topic" : "Pick a symbol"}
      body={topicMode ? "NI searches recent headlines by topic." : `${code} tails recent headlines for one ticker.`}
      icon="⌖"
    />
  ) : error ? (
    <Empty title="Function error" body={error} icon="!" />
  ) : effectiveState === "loading" || articles == null ? (
    <LoadingNews
      label={requestLabel}
      phase={veryfinderIsBlocking ? "veryfinder" : "headlines"}
      headlineCount={articles?.length ?? 0}
      tweetTarget={veryfinderTweetTarget}
    />
  ) : sortedArticles.length === 0 ? (
    <Empty title="No headlines yet" body={`No news payload for ${requestLabel} in last ${limit}.`} />
  ) : (
    <div style={twoColumnLayout}>
      <section style={feedColumn}>
        <ArticleList
          articles={sortedArticles}
          setFocusedTarget={setFocusedTarget}
          veryfinderMap={veryfinderMap}
          veryfinderState={veryfinderState}
          fallbackSymbol={topicMode ? undefined : effectiveSymbol}
          selectedKey={selectedKey ?? articleKey(sortedArticles[0]!, 0)}
          onSelect={setSelectedKey}
        />
        <SentimentTimeline buckets={timeline} />
      </section>
      <aside style={synthesisColumn}>
        <AISynthesisCard synthesis={synthesis} selectedArticle={selectedArticle} />
      </aside>
    </div>
  );

  return (
    <div className="u-pane-host--bb">
      <Pane>
        <PaneHeader
          code={code}
          title={topicMode ? `News intelligence — ${topicText.trim() || "topic"}` : `Company news — ${effectiveSymbol ?? ""}`}
          subtitle={
            effectiveState === "loading" && requestLabel
              ? veryfinderIsBlocking
                ? `scanning evidence for ${requestLabel} · ${articles?.length ?? 0} headline(s)`
                : `loading ${requestLabel} · fetching latest ${FETCH_NEWS_LIMIT}`
              : articles
                ? `${Math.min(articles.length, limit)}/${articles.length} shown`
                : "polling every 90s"
          }
          trailing={
            <FunctionControlGroup>
              {requestLabel ? (
                <Pill tone="accent" variant="soft" withDot={false}>
                  {topicMode ? "topic" : "symbol"} · {requestLabel}
                </Pill>
              ) : null}
              <SentimentScoreBadge score={sentimentScore} />
              {!topicMode ? <XSenChip symbol={effectiveSymbol} compact /> : null}
              <NewsLimitControl value={limit} onChange={setLimit} disabled={effectiveState === "loading"} />
              <LoadStatePill state={effectiveState} />
              <RefreshButton
                loading={effectiveState === "loading"}
                onClick={() => setTick((t) => t + 1)}
                title="Refresh headlines"
              />
            </FunctionControlGroup>
          }
        />
        {/* KPI ribbon */}
        {articles && articles.length > 0 ? (
          <section style={kpiRibbon}>
            <StatCard
              label="Headlines"
              value={String(articles.length)}
              caption={`shown ${Math.min(articles.length, limit)}`}
              tone="neutral"
            />
            <StatCard
              label="Sentiment"
              value={sentimentScore == null ? "—" : `${sentimentScore >= 0 ? "+" : ""}${sentimentScore.toFixed(2)}`}
              caption={sentimentScore == null ? "no signal" : sentimentScore > 0.18 ? "bullish bias" : sentimentScore < -0.18 ? "bearish bias" : "neutral"}
              tone={sentimentScore == null ? "neutral" : sentimentScore > 0.18 ? "positive" : sentimentScore < -0.18 ? "negative" : "neutral"}
            />
            <StatCard
              label="Bull / Bear"
              value={`${impactStats.bull} / ${impactStats.bear}`}
              caption="vf signal split"
              tone={impactStats.bull > impactStats.bear ? "positive" : impactStats.bear > impactStats.bull ? "negative" : "neutral"}
            />
            <StatCard
              label="High impact"
              value={String(impactStats.high)}
              caption="score ≥ 70"
              tone={impactStats.high > 0 ? "negative" : "neutral"}
            />
          </section>
        ) : null}
        {topicMode ? (
          <section style={topicBar}>
            <Field
              label="Topic"
              value={topicText}
              onChange={(e) => setTopicText(e.target.value)}
              placeholder="FED, earnings, crypto liquidity..."
              hint="Topic text is sent as topic/query; it is not treated as a ticker."
              onKeyDown={(e) => {
                if (e.key === "Enter") setTick((t) => t + 1);
              }}
            />
            <SegmentedControl
              label="TOPIC"
              value={TOPIC_PRESETS.includes(topicText as TopicPreset) ? topicText : ""}
              options={TOPIC_PRESETS}
              onChange={(next) => {
                setTopicText(String(next));
                setTick((t) => t + 1);
              }}
              disabled={effectiveState === "loading"}
            />
          </section>
        ) : (
          <SymbolBar code={code} symbol={effectiveSymbol} />
        )}
        <PaneBody className="ni-pane-body">
          {body}
        </PaneBody>
        <PaneFooter>
          <span>refresh · {REFRESH_MS / 1000}s</span>
          <span>last · show {limit}</span>
          <span>cached · {articles?.length ?? 0} news</span>
          <span>veryfinder · {veryfinderState}</span>
          <span>{topicMode ? `topic · ${topicText || "—"}` : `symbol · ${symbol ?? "—"}`}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function SentimentScoreBadge({ score }: { score: number | null }) {
  if (score == null) {
    return (
      <Pill tone="muted" variant="soft" withDot={false}>
        sentiment · —
      </Pill>
    );
  }
  const clamped = Math.max(-1, Math.min(1, score));
  const tone = clamped > 0.18 ? "positive" : clamped < -0.18 ? "negative" : "warn";
  const sign = clamped >= 0 ? "+" : "";
  // Inline mini-bar
  return (
    <span
      title={`Aggregate sentiment ${clamped.toFixed(2)} (-1..+1)`}
      className={`ni-sent-badge ni-sent-badge--${tone}`}
    >
      <span className="ni-sent-badge__label">sentiment</span>
      <span className="ni-sent-badge__track">
        <span
          className="ni-sent-badge__fill"
          style={{
            ["--u-left" as string]: clamped >= 0 ? "50%" : `${50 + clamped * 50}%`,
            ["--u-width" as string]: `${Math.abs(clamped) * 50}%`,
          }}
        />
        <span className="ni-sent-badge__mid" />
      </span>
      <strong>
        {sign}
        {clamped.toFixed(2)}
      </strong>
    </span>
  );
}

interface SynthesisData {
  bull: Array<{ text: string; cite: number }>;
  bear: Array<{ text: string; cite: number }>;
  catalysts: Array<{ text: string; cite: number }>;
}

function buildSynthesis(
  articles: NIArticle[],
  veryfinderMap: Record<string, VeryfinderOverlay>,
): SynthesisData {
  const bull: Array<{ text: string; cite: number }> = [];
  const bear: Array<{ text: string; cite: number }> = [];
  const catalysts: Array<{ text: string; cite: number }> = [];
  articles.forEach((a, i) => {
    const cite = i + 1;
    const overlay = veryfinderMap[articleKey(a, i)];
    const score = overlay?.ok ? Number(overlay.social_score ?? 0) : null;
    const headline = a.title ?? a.headline ?? "(untitled)";
    const importance = Number(a.importance_score ?? 0);
    if (score != null && score > 18) {
      bull.push({ text: truncate(cleanSummary(headline), 120), cite });
    } else if (score != null && score < -18) {
      bear.push({ text: truncate(cleanSummary(headline), 120), cite });
    }
    if (importance >= 70 || a.severity === "high" || a.severity === "critical") {
      catalysts.push({ text: truncate(cleanSummary(headline), 120), cite });
    }
  });
  return {
    bull: bull.slice(0, 5),
    bear: bear.slice(0, 5),
    catalysts: catalysts.slice(0, 5),
  };
}

function AISynthesisCard({
  synthesis,
  selectedArticle,
}: {
  synthesis: SynthesisData;
  selectedArticle: NIArticle | null;
}) {
  return (
    <Card variant="elev-2">
      <CardHeader trailing={<Pill tone="accent" variant="soft" withDot={false}>AI</Pill>}>
        Synthesis
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-12">
          {selectedArticle ? (
            <div style={selectedSummaryStyle}>
              <div style={selectedKickerStyle}>NOW READING</div>
              <strong style={selectedTitleStyle}>
                {selectedArticle.title ?? selectedArticle.headline ?? "(untitled)"}
              </strong>
              {selectedArticle.summary ? (
                <p style={selectedExcerptStyle}>
                  {truncate(cleanSummary(selectedArticle.summary), 220)}
                </p>
              ) : null}
            </div>
          ) : null}
          <SynthSection
            title="Bull"
            tone="positive"
            items={synthesis.bull}
            emptyText="No bullish signal in this window."
          />
          <SynthSection
            title="Bear"
            tone="negative"
            items={synthesis.bear}
            emptyText="No bearish signal in this window."
          />
          <SynthSection
            title="Catalysts"
            tone="warn"
            items={synthesis.catalysts}
            emptyText="No high-impact catalysts."
          />
        </div>
      </CardBody>
    </Card>
  );
}

function SynthSection({
  title,
  tone,
  items,
  emptyText,
}: {
  title: string;
  tone: "positive" | "negative" | "warn";
  items: Array<{ text: string; cite: number }>;
  emptyText: string;
}) {
  return (
    <div>
      <header style={synthSectionHeader}>
        <Pill tone={tone} variant="soft" withDot={false}>
          {title}
        </Pill>
        <span className="ni-section-count">{items.length}</span>
      </header>
      {items.length === 0 ? (
        <p style={synthEmpty}>{emptyText}</p>
      ) : (
        <ul style={synthList}>
          {items.map((item, i) => (
            <li key={i} style={synthListItem}>
              <span style={citationChipStyle} title={`citation [${item.cite}]`}>
                [{item.cite}]
              </span>
              <span>{item.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface TimelineBucket {
  hour: number; // 0..23 (relative, 23 = newest)
  count: number;
  posScore: number;
  negScore: number;
}

function buildTimeline(
  articles: NIArticle[],
  veryfinderMap: Record<string, VeryfinderOverlay>,
): TimelineBucket[] {
  const buckets: TimelineBucket[] = Array.from({ length: 24 }, (_, i) => ({
    hour: i,
    count: 0,
    posScore: 0,
    negScore: 0,
  }));
  const now = Date.now();
  articles.forEach((a, i) => {
    const ts = articleTimestamp(a);
    const parsed = ts ? Date.parse(ts) : NaN;
    if (!Number.isFinite(parsed)) return;
    const hoursAgo = (now - parsed) / 3_600_000;
    if (hoursAgo < 0 || hoursAgo > 24) return;
    const idx = Math.max(0, Math.min(23, 23 - Math.floor(hoursAgo)));
    buckets[idx].count += 1;
    const overlay = veryfinderMap[articleKey(a, i)];
    if (overlay?.ok) {
      const s = Number(overlay.social_score ?? 0);
      if (s > 0) buckets[idx].posScore += s;
      else if (s < 0) buckets[idx].negScore += Math.abs(s);
    }
  });
  return buckets;
}

function SentimentTimeline({ buckets }: { buckets: TimelineBucket[] }) {
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));
  const totalEvents = buckets.reduce((sum, b) => sum + b.count, 0);
  return (
    <section style={timelineWrap}>
      <header style={timelineHeader}>
        <span style={timelineLabel}>24H sentiment timeline</span>
        <span className="ni-section-count">{totalEvents} events</span>
      </header>
      <div style={timelineBars}>
        {buckets.map((b, i) => {
          const height = (b.count / maxCount) * 28;
          const tone =
            b.posScore > b.negScore
              ? "var(--positive)"
              : b.negScore > b.posScore
                ? "var(--negative)"
                : "var(--text-mute)";
          return (
            <span
              key={i}
              title={`${24 - i}h ago · ${b.count} events`}
              className={`ni-timeline-bar${b.count > 0 ? "" : " ni-timeline-bar--empty"}`}
              style={{
                ["--u-height" as string]: `${Math.max(2, height)}px`,
                ["--u-bg" as string]: b.count > 0 ? tone : "var(--border-subtle)",
              }}
            />
          );
        })}
      </div>
      <footer style={timelineAxis}>
        <span>-24h</span>
        <span>-12h</span>
        <span>now</span>
      </footer>
    </section>
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

const NEWS_PIPELINE_STEPS = [
  {
    title: "Headlines",
    status: "fetching",
    detail: "Live company headlines, source timestamps, direct links.",
  },
  {
    title: "Symbol map",
    status: "normalizing",
    detail: "Ticker aliases, company names, crypto suffixes, query terms.",
  },
  {
    title: "Social window",
    status: "sizing",
    detail: "Efficient min-tweet target and newest evidence window.",
  },
  {
    title: "Search",
    status: "probing",
    detail: "Public web/news/social rows, recency filter, source fallback.",
  },
  {
    title: "Dedupe",
    status: "hashing",
    detail: "Unique-account vote, duplicate rows and stale evidence dropped.",
  },
  {
    title: "Inference",
    status: "scoring",
    detail: "Sentiment, action, market view, impact label, render payload.",
  },
] as const;

const NEWS_PIPELINE_LOGS = [
  "news.fetch: requesting latest headline batch",
  "symbol.resolve: matching ticker, aliases, and source tags",
  "window.size: assigning min tweet target per article",
  "source.search: querying public web/news/social evidence",
  "recency.filter: dropping stale rows before scoring",
  "account.dedupe: one visible vote per source/account",
  "inference.run: sentiment, action, view, impact",
  "render.queue: cards update as soon as rows finish",
] as const;

function LoadingNews({
  label,
  phase = "headlines",
  headlineCount = 0,
  tweetTarget = 0,
}: {
  label: string;
  phase?: "headlines" | "veryfinder";
  headlineCount?: number;
  tweetTarget?: number;
}) {
  const waitingForVeryfinder = phase === "veryfinder";
  return (
    <div aria-live="polite" style={newsLoadShell}>
      <style>{newsLoadAnimationCss}</style>
      <div className="showme-news-scanline" />
      <div style={newsLoadHeader}>
        <div className="u-min-w-0">
          <div style={newsLoadKicker}>
            {waitingForVeryfinder ? "Veryfinder evidence pipeline" : "News + Veryfinder pipeline"}
          </div>
          <strong style={newsLoadTitle}>
            {waitingForVeryfinder ? `Scanning evidence for ${label}` : `Building live view for ${label}`}
          </strong>
          <p style={newsLoadText}>
            {waitingForVeryfinder
              ? `Headline batch is ready (${headlineCount} rows). Keeping the loading screen open while Veryfinder collects the newest usable evidence, filters stale rows, dedupes sources, and scores every card. Target window: ${tweetTarget} evidence rows.`
              : "Fetching headlines first, then rolling each item through source search, recency filtering, unique-account dedupe, and sentiment/action inference. Rows appear when each article has enough usable evidence or a clear source-capacity note."}
          </p>
        </div>
        <div style={newsLoadDial} title="Pipeline activity">
          <span style={newsLoadDialCenter}>VF</span>
          {Array.from({ length: 12 }).map((_, index) => (
            <span
              key={index}
              className="showme-news-orbit-dot"
              style={{ transform: `rotate(${index * 30}deg) translateY(-34px)` }}
            />
          ))}
        </div>
      </div>

      <div style={newsLoadRail} className="showme-news-data-rail">
        <span style={newsLoadRailLabel}>packet rail</span>
        <span style={newsLoadRailValue}>
          {waitingForVeryfinder
            ? "headline batch ready -&gt; newest evidence -&gt; scored cards"
            : "headline rows -&gt; evidence rows -&gt; scored cards"}
        </span>
      </div>

      <div style={newsLoadSteps}>
        {NEWS_PIPELINE_STEPS.map((step, index) => (
          <div key={step.title} style={newsLoadStep}>
            <div style={newsLoadStepIndex}>{index + 1}</div>
            <div className="u-min-w-0">
              <strong style={newsLoadStepTitle}>{step.title}</strong>
              <span style={newsLoadStepStatus}>{step.status}</span>
              <small style={newsLoadStepDetail}>{step.detail}</small>
            </div>
          </div>
        ))}
      </div>

      <div style={newsLoadTelemetryGrid}>
        <div style={newsLoadTerminal}>
          <div style={newsLoadTerminalHeader}>
            <span>live pipeline log</span>
            <strong>streaming</strong>
          </div>
          <div style={newsLoadLogList}>
            {NEWS_PIPELINE_LOGS.map((line, index) => (
              <div
                key={line}
                className="showme-news-log-line"
                style={{ animationDelay: `${index * 220}ms` }}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <code>{line}</code>
              </div>
            ))}
          </div>
        </div>
        <div style={newsLoadStatusPanel}>
          <div style={newsLoadStatusRow}>
            <strong>Why this can take time</strong>
            <span>Veryfinder waits for usable evidence instead of filling cards with stale rows.</span>
          </div>
          <div style={newsLoadStatusRow}>
            <strong>Slow-source behavior</strong>
            <span>If a provider is late, ShowMe keeps the search alive, records the source-capacity note, and renders partial rows.</span>
          </div>
          <div style={newsLoadStatusRow}>
            <strong>Freshness rule</strong>
            <span>Known old evidence is filtered before scoring, so the view stays recent.</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ArticleList({
  articles,
  setFocusedTarget,
  veryfinderMap,
  veryfinderState,
  fallbackSymbol,
  selectedKey,
  onSelect,
}: {
  articles: NIArticle[];
  setFocusedTarget: (code: string, symbol?: string) => void;
  veryfinderMap: Record<string, VeryfinderOverlay>;
  veryfinderState: LoadState;
  fallbackSymbol?: string;
  selectedKey: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="ni-feed-list">
      {articles.map((a, i) => {
        const key = articleKey(a, i);
        const veryfinder = veryfinderMap[key];
        const tweetTarget = recommendedVeryfinderSampleForNews(a, fallbackSymbol);
        const isSelected = key === selectedKey;
        return (
          <article
            key={key}
            onClick={() => onSelect(key)}
            style={feedRowStyle(isSelected)}
          >
            <div style={feedRowDot}>
              <SentimentDot overlay={veryfinder} />
              <span style={feedRowIndex}>{i + 1}</span>
            </div>
            <div className="u-min-w-0">
              <div style={articleHead}>
                <strong className="ni-feed-title">
                  {a.title ?? a.headline ?? "(untitled)"}
                </strong>
              </div>
              {a.summary ? (
                <p style={summaryStyle}>{truncate(cleanSummary(a.summary), 180)}</p>
              ) : null}
              <div style={articleMeta}>
                {a.source ? (
                  <Pill tone="muted" variant="soft" withDot={false}>
                    {a.source}
                  </Pill>
                ) : null}
                {a.category ? <span style={tinyMute}>{a.category}</span> : null}
                {a.importance_score != null ? (
                  <Pill
                    tone={a.severity === "critical" || a.severity === "high" ? "negative" : "muted"}
                    variant="soft"
                    withDot={false}
                  >
                    impact {Number(a.importance_score).toFixed(0)}
                  </Pill>
                ) : null}
                {veryfinder ? <VeryfinderImpactPill overlay={veryfinder} /> : null}
                {!veryfinder && veryfinderState === "loading" && i < 3 ? (
                  <Pill tone="muted" variant="soft" withDot={false}>
                    vf scanning {tweetTarget}
                  </Pill>
                ) : null}
                {(a.symbols ?? (a.symbol ? [a.symbol] : [])).slice(0, 3).map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="btn btn--ghost"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      setFocusedTarget("DES", s);
                      navigate(`/symbol/${s}/DES`);
                    }}
                    style={symbolButton}
                  >
                    {s}
                  </button>
                ))}
                <span className="u-flex-1" />
                <span style={tinyMute}>{tsLabel(a) ?? ""}</span>
                {(a.url ?? a.link) ? (
                  <a
                    href={a.url ?? a.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(ev) => ev.stopPropagation()}
                    className="ni-feed-source"
                  >
                    source ↗
                  </a>
                ) : null}
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function SentimentDot({ overlay }: { overlay?: VeryfinderOverlay }) {
  if (!overlay?.ok) {
    return <span className="ni-feed-dot ni-feed-dot--empty" />;
  }
  const s = Number(overlay.social_score ?? 0);
  const color =
    s > 12 ? "var(--positive)" : s < -12 ? "var(--negative)" : "var(--warn)";
  return (
    <span
      className="ni-feed-dot"
      style={{ ["--u-color" as string]: color }}
    />
  );
}

function VeryfinderImpactPill({ overlay }: { overlay: VeryfinderOverlay }) {
  if (!overlay.ok) {
    return (
      <Pill tone="warn" variant="soft" withDot={false}>
        vf error
      </Pill>
    );
  }
  if ((overlay.dominant_view?.label ?? "") === "no_data" || Number(overlay.unique_accounts ?? 0) <= 0) {
    return (
      <Pill tone="muted" variant="soft" withDot={false}>
        vf no match
      </Pill>
    );
  }
  const vfScore = formatInt(veryfinderDisplayScore(overlay));
  const directionScore = formatSignedInt(overlay.social_score);
  const view = overlay.dominant_view?.display ?? "social";
  const confidence = Math.round(Number(overlay.dominant_view?.score ?? 0) * 100);
  const source = veryfinderSourceLabel(overlay);
  const title = [
    overlay.meaning,
    `vf impact score: ${vfScore}`,
    `direction score: ${directionScore}`,
    `query: ${overlay.query ?? "n/a"}`,
    `source: ${source}`,
    `unique accounts: ${overlay.unique_accounts ?? "n/a"}`,
    overlay.top_mood ? `mood: ${overlay.top_mood.label}` : null,
    overlay.top_action ? `action: ${overlay.top_action.label}` : null,
  ].filter(Boolean).join("\n");
  return (
    <span title={title}>
      <Pill tone={veryfinderTone(overlay.tone)} variant="soft" withDot={false}>
        vf {vfScore} {view} {confidence}%
      </Pill>
    </span>
  );
}

function veryfinderSourceLabel(overlay: VeryfinderOverlay): string {
  if (overlay.fallback_mode === "article_context" || overlay.source === "news_proxy") {
    const from = overlay.source_fallback_from ? ` after ${overlay.source_fallback_from}` : "";
    return `news context proxy${from}`;
  }
  return overlay.fixture_mode ? "fixture source" : overlay.source ?? "source —";
}

function veryfinderDisplayScore(overlay: VeryfinderOverlay): number {
  const explicit = Number(overlay.impact_score);
  if (Number.isFinite(explicit)) return Math.round(explicit);
  const confidence = Number(overlay.dominant_view?.score);
  if (Number.isFinite(confidence) && Number(overlay.unique_accounts ?? 0) > 0) {
    return Math.round(Math.max(0, Math.min(1, confidence)) * 100);
  }
  return Math.abs(Math.round(Number(overlay.social_score ?? 0)));
}

function articleKey(a: NIArticle, index: number): string {
  return [
    a.url ?? a.link ?? "",
    a.title ?? a.headline ?? "",
    articleTimestamp(a) ?? "",
    String(index),
  ].join("|");
}

function formatSignedInt(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const n = Math.round(Number(value));
  return n > 0 ? `+${n}` : String(n);
}

function formatInt(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function veryfinderTone(tone?: VeryfinderTone): "positive" | "negative" | "warn" | "muted" | "neutral" {
  if (tone === "positive" || tone === "negative" || tone === "warn" || tone === "muted") {
    return tone;
  }
  return "neutral";
}

function normalize(payload: unknown): NIArticle[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as NIArticle[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.items ?? o.articles ?? o.news ?? o.headlines;
    if (Array.isArray(items)) return items as NIArticle[];
  }
  return [];
}

function cleanSummary(value: string): string {
  try {
    const doc = new DOMParser().parseFromString(value, "text/html");
    const text = doc.body.textContent?.replace(/\s+/g, " ").trim();
    if (text) return text;
  } catch {
    // Fall back to a lightweight strip below.
  }
  return value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

function truncate(value: string, max: number): string {
  return value.length > max ? value.slice(0, max) + "…" : value;
}

function tsLabel(a: NIArticle): string | null {
  return relativeTimeLabel(articleTimestamp(a));
}

function articleTimestamp(a: NIArticle): string | null | undefined {
  return (
    a.published_at ??
    a.publishedAt ??
    a.published_on ??
    a.published ??
    a.date ??
    a.datetime ??
    a.time ??
    a.ts
  );
}

// ─── styles ────────────────────────────────────────────────────────────

const kpiRibbon: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 8,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "color-mix(in srgb, var(--surface) 80%, transparent)",
};

const topicBar: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(220px, 1fr) auto",
  gap: 8,
  alignItems: "end",
  padding: "0 14px 10px",
  borderBottom: "1px solid var(--border-subtle)",
};

const twoColumnLayout: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 6fr) minmax(0, 4fr)",
  gap: 0,
  height: "100%",
  minHeight: 0,
};

const feedColumn: CSSProperties = {
  minWidth: 0,
  minHeight: 0,
  overflow: "auto",
  padding: "10px 12px",
  borderRight: "1px solid var(--border-subtle)",
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const synthesisColumn: CSSProperties = {
  minWidth: 0,
  minHeight: 0,
  overflow: "auto",
  padding: "10px 12px",
  background: "color-mix(in srgb, var(--bg) 70%, transparent)",
};

const feedRowStyle = (selected: boolean): CSSProperties => ({
  display: "grid",
  gridTemplateColumns: "32px minmax(0, 1fr)",
  gap: 8,
  padding: "10px 10px 10px 8px",
  background: selected ? "var(--surface-2)" : "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderLeft: selected ? "2px solid var(--accent)" : "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  cursor: "pointer",
  transition: "background var(--motion-fast), border-color var(--motion-fast)",
});

const feedRowDot: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 6,
  paddingTop: 4,
};

const feedRowIndex: CSSProperties = {
  fontSize: 9,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.04em",
};

const articleHead: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 6,
  flexWrap: "wrap",
  marginBottom: 4,
};

const articleMeta: CSSProperties = {
  display: "flex",
  gap: 6,
  alignItems: "center",
  flexWrap: "wrap",
  marginTop: 4,
};

const summaryStyle: CSSProperties = {
  margin: "0 0 4px",
  fontSize: 11,
  color: "var(--text-secondary)",
  lineHeight: 1.5,
};

const symbolButton: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  padding: "1px 6px",
  height: 18,
  color: "var(--accent)",
};

const tinyMute: CSSProperties = {
  fontSize: 10,
  color: "var(--text-mute)",
};

const selectedSummaryStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: "10px 12px",
  background: "var(--accent-soft)",
  border: "1px solid color-mix(in srgb, var(--accent) 38%, transparent)",
  borderRadius: "var(--radius-md)",
};

const selectedKickerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--accent)",
};

const selectedTitleStyle: CSSProperties = {
  fontSize: 13,
  color: "var(--text-primary)",
  lineHeight: 1.4,
};

const selectedExcerptStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  lineHeight: 1.5,
  color: "var(--text-secondary)",
};

const synthSectionHeader: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 6,
  marginBottom: 6,
};

const synthEmpty: CSSProperties = {
  margin: 0,
  fontSize: 11,
  color: "var(--text-mute)",
  fontStyle: "italic",
};

const synthList: CSSProperties = {
  margin: 0,
  padding: 0,
  display: "flex",
  flexDirection: "column",
  gap: 6,
  listStyle: "none",
};

const synthListItem: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto 1fr",
  gap: 6,
  alignItems: "start",
  fontSize: 11,
  color: "var(--text-primary)",
  lineHeight: 1.5,
};

const citationChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  minWidth: 22,
  height: 16,
  padding: "0 4px",
  borderRadius: 3,
  background: "var(--accent-soft)",
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  fontWeight: 600,
};

const timelineWrap: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: "10px 12px",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
};

const timelineHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};

const timelineLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const timelineBars: CSSProperties = {
  display: "flex",
  alignItems: "flex-end",
  gap: 4,
  height: 32,
};

const timelineAxis: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontSize: 9,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.04em",
};

const newsLoadShell: CSSProperties = {
  position: "relative",
  overflow: "hidden",
  display: "grid",
  gap: 14,
  padding: 14,
  margin: 14,
  border: "1px solid color-mix(in srgb, var(--accent) 42%, transparent)",
  borderRadius: "var(--radius-md)",
  background: [
    "linear-gradient(135deg, var(--accent-soft), color-mix(in srgb, var(--accent) 5%, transparent))",
    "radial-gradient(circle at 86% 12%, var(--accent-soft), transparent 24%)",
    // Session 16 BugHunt: previously baked a raw light-mode overlay
    // (color-mix with the literal "white" channel) which was invisible
    // on Papyrus / wrong tone on Matrix. The scrim tokens flip per
    // preset so the highlight tracks the active theme.
    "linear-gradient(180deg, var(--scrim-low), transparent)",
  ].join(", "),
  boxShadow: "inset 0 1px 0 var(--scrim-low), var(--shadow-elev-3)",
};

const newsLoadHeader: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(320px, 1fr) 86px",
  gap: 18,
  alignItems: "center",
  position: "relative",
  zIndex: 1,
};

const newsLoadKicker: CSSProperties = {
  fontSize: 10,
  color: "var(--accent)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontFamily: "JetBrains Mono, monospace",
};

const newsLoadTitle: CSSProperties = {
  display: "block",
  marginTop: 5,
  color: "var(--text-primary)",
  fontSize: 20,
  letterSpacing: 0,
};

const newsLoadText: CSSProperties = {
  margin: "8px 0 0",
  color: "var(--text-secondary)",
  fontSize: 12,
  lineHeight: 1.55,
  maxWidth: 920,
};

const newsLoadDial: CSSProperties = {
  position: "relative",
  width: 78,
  height: 78,
  borderRadius: "50%",
  border: "1px solid color-mix(in srgb, var(--accent) 28%, transparent)",
  background:
    "radial-gradient(circle, var(--accent-soft), color-mix(in srgb, var(--bg) 45%, transparent) 58%, transparent 60%)",
  boxShadow: "0 0 22px color-mix(in srgb, var(--accent) 20%, transparent)",
  display: "grid",
  placeItems: "center",
  animation: "showme-news-dial 4.8s linear infinite",
};

const newsLoadDialCenter: CSSProperties = {
  width: 36,
  height: 36,
  borderRadius: "50%",
  display: "grid",
  placeItems: "center",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--accent)",
  background: "color-mix(in srgb, var(--bg) 36%, transparent)",
  border: "1px solid color-mix(in srgb, var(--accent) 30%, transparent)",
  animation: "showme-news-dial-core 1.6s ease-in-out infinite",
};

const newsLoadRail: CSSProperties = {
  position: "relative",
  zIndex: 1,
  minHeight: 34,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
  padding: "8px 10px",
  border: "1px solid color-mix(in srgb, var(--accent) 22%, transparent)",
  borderRadius: "var(--radius-sm)",
  background: "color-mix(in srgb, var(--bg) 18%, transparent)",
  overflow: "hidden",
};

const newsLoadRailLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--accent)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const newsLoadRailValue: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--text-secondary)",
  overflowWrap: "anywhere",
};

const newsLoadSteps: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
  gap: 8,
  position: "relative",
  zIndex: 1,
};

const newsLoadStep: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "28px minmax(0, 1fr)",
  alignItems: "start",
  gap: 10,
  minHeight: 78,
  padding: "10px 11px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  // Session 16 BugHunt: scrim tokens make the step card visible under
  // Papyrus (cream) and Matrix (phosphor) instead of the prior
  // dark-mode-only white overlay.
  background: "linear-gradient(180deg, var(--scrim-low), transparent)",
  color: "var(--text-secondary)",
  fontSize: 11,
  boxShadow: "inset 0 1px 0 var(--scrim-low)",
};

const newsLoadStepIndex: CSSProperties = {
  width: 24,
  height: 24,
  borderRadius: "50%",
  display: "grid",
  placeItems: "center",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--accent)",
  background: "var(--accent-soft)",
  border: "1px solid color-mix(in srgb, var(--accent) 22%, transparent)",
};

const newsLoadStepTitle: CSSProperties = {
  display: "block",
  color: "var(--text-primary)",
  fontSize: 11,
  lineHeight: 1.25,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
};

const newsLoadStepStatus: CSSProperties = {
  display: "block",
  marginTop: 4,
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
};

const newsLoadStepDetail: CSSProperties = {
  display: "block",
  marginTop: 5,
  color: "var(--text-secondary)",
  lineHeight: 1.35,
};

const newsLoadTelemetryGrid: CSSProperties = {
  position: "relative",
  zIndex: 1,
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 10,
};

const newsLoadTerminal: CSSProperties = {
  minHeight: 152,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "color-mix(in srgb, var(--bg) 38%, transparent)",
  overflow: "hidden",
};

const newsLoadTerminalHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 10,
  padding: "8px 10px",
  borderBottom: "1px solid var(--border-subtle)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
};

const newsLoadLogList: CSSProperties = {
  display: "grid",
  gap: 5,
  padding: 10,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

const newsLoadStatusPanel: CSSProperties = {
  display: "grid",
  gap: 8,
  minWidth: 0,
};

const newsLoadStatusRow: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "9px 10px",
  border: "1px solid color-mix(in srgb, var(--warn) 18%, transparent)",
  borderRadius: "var(--radius-sm)",
  background: "color-mix(in srgb, var(--warn) 4%, transparent)",
  color: "var(--text-secondary)",
  fontSize: 11,
};

const newsLoadAnimationCss = `
@keyframes showme-news-rail {
  from { background-position: 0 0; }
  to { background-position: 56px 0; }
}
@keyframes showme-news-scan {
  0% { transform: translateY(-100%); opacity: 0; }
  18% { opacity: 0.18; }
  100% { transform: translateY(520px); opacity: 0; }
}
@keyframes showme-news-dial {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
@keyframes showme-news-dial-core {
  0%, 100% { box-shadow: 0 0 0 transparent; }
  50% { box-shadow: 0 0 18px color-mix(in srgb, var(--accent) 35%, transparent); }
}
@keyframes showme-news-log {
  0%, 18% { opacity: 0.32; transform: translateX(-4px); }
  35%, 100% { opacity: 1; transform: translateX(0); }
}
.showme-news-scanline {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(180deg, transparent, var(--accent-soft), transparent);
  height: 80px;
  animation: showme-news-scan 4.8s linear infinite;
}
.showme-news-orbit-dot {
  position: absolute;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--accent) 70%, transparent);
  box-shadow: 0 0 10px color-mix(in srgb, var(--accent) 55%, transparent);
}
.showme-news-data-rail::after {
  content: "";
  position: absolute;
  inset: 0;
  opacity: 0.28;
  background-image: repeating-linear-gradient(
    -45deg,
    transparent,
    transparent 10px,
    color-mix(in srgb, var(--accent) 28%, transparent) 10px,
    color-mix(in srgb, var(--accent) 28%, transparent) 18px
  );
  background-size: 56px 56px;
  animation: showme-news-rail 900ms linear infinite;
}
.showme-news-log-line {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 9px;
  color: var(--text-secondary);
  animation: showme-news-log 1.8s ease-in-out infinite alternate;
}
.showme-news-log-line span {
  color: var(--text-mute);
}
.showme-news-log-line code {
  color: var(--text-secondary);
  white-space: normal;
}
`;
